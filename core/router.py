"""意图路由与自动选模。规则优先，永远有兜底；不依赖任何 LLM 也能跑。"""
from __future__ import annotations

import re

from .catalog import ModelCatalog, ModelEntry
from .errors import RoutingError
from .types import (
    KIND_AUTO,
    KIND_EDIT,
    KIND_REFERENCE,
    KIND_SELFIE,
    KIND_TEXT2IMG,
    ImageRequest,
)

#: 有参考图时，哪些说法算“改这张图”而不是“照这张另画一张”
#: 都是“局部改”的说法：颜色、衣服、头发、去掉/加上某个东西。
_EDIT_PATTERNS = [
    r"改成|换成|改为|变成|变为|去掉|删掉|去除|抹掉|加个|加一个|修改|编辑|改一下|把.{0,12}(?:换|改|变)成",
    r"\bedit\b|\bremove\b|\breplace\b|\bmodify\b|\binpaint\b",
]
#: 有参考图时，哪些说法算“参考这张画新的”
_REFERENCE_PATTERNS = [
    r"参考|以这张|照着|照这张|按照这张|按这张|仿照|拿这张|用这张|画她|画他|画这个|换场景|换个场景|新姿势|换个姿势",
    r"\breference\b|\bbased on\b|\blike this\b|\bsame (?:person|character)\b|\bnew pose\b",
]
#: 改动落在“背景/场景/构图/姿势”这类整张画面的东西上——img2img 低重绘改不动，
#: 只能按参考图重画。所以这些词优先判成 reference。
_SCENE_PATTERNS = [
    r"(?:换|改|变|重画|重做|新)(?:个|一个)?(?:背景|场景|构图|姿势|动作|视角|镜头|环境)",
    r"(?:背景|场景|构图|姿势|动作|视角|镜头|环境)[^，。]{0,6}(?:换|改|变)成",
    r"(?:change|swap|replace)[^,.]{0,20}\b(?:background|scene|pose)\b",
    r"\b(?:new|another)\s+(?:background|scene|pose)\b",
]
#: 没有参考图时，哪些说法算“要她本人出镜”
_SELFIE_PATTERNS = [
    r"自拍|拍一张|拍张|拍照|来一张|看看你|你现在的样子|你的样子|出镜|合影|发张照",
    r"\bselfie\b|\btake a photo\b|\bshow me you\b",
]

#: 自动选模的风格提示词 → 模型 key（先匹配先生效）
_STYLE_HINTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"像素|pixel|8bit|8-bit", re.I), "pixel"),
    (re.compile(r"写实|照片|photoreal|realistic|真人", re.I), "xxmix"),
    (re.compile(r"赛璐璐|cel\s*shad|动画截图", re.I), "fabricated"),
    (re.compile(r"通透|平涂|flat\s*color|清爽", re.I), "novaflat"),
    (re.compile(r"甜|明亮|bright|pastel|马卡龙", re.I), "lemon"),
    (re.compile(r"柔光|肤感|soft\s*light|柔焦", re.I), "miao"),
    (re.compile(r"干净|清漫|简洁", re.I), "cat"),
    (re.compile(r"华丽|厚涂|细节满|ornate", re.I), "obsession"),
]


def _matches(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


def pick_image_kind(text: str) -> str:
    """有参考图时按原话判断链路：改图(edit) 还是照着重画(reference)。

    优先级（先后即结果）：
    1. 场景类改动（背景/场景/构图/姿势…）→ reference：edit 只重绘 30%~45%，
       改不动整张画面的结构，硬走 edit 只会得到“几乎没变”的图。
    2. 局部改动（改成/换成/去掉/加个…）→ edit：这类正是 img2img 擅长的。
    3. 参考锚点（参考这张/照着/以这张…）→ reference。
    4. 都没有 → reference（带图默认照着重画）。
    """
    body = str(text or "")
    if _matches(_SCENE_PATTERNS, body):
        return KIND_REFERENCE
    if _matches(_EDIT_PATTERNS, body):
        return KIND_EDIT
    if _matches(_REFERENCE_PATTERNS, body):
        return KIND_REFERENCE
    return KIND_REFERENCE


def route_kind(request: ImageRequest) -> str:
    """决定这次走哪条链路：selfie / edit / reference / text2img。"""
    explicit = request.resolved_kind()
    if explicit != KIND_AUTO:
        return explicit

    text = str(request.prompt or "")
    if request.references:
        return pick_image_kind(text)
    return KIND_SELFIE if _matches(_SELFIE_PATTERNS, text) else KIND_TEXT2IMG


def correct_kind(kind: str, request: ImageRequest) -> str:
    """纠正“显式选了 edit、其实该照着重画”的情况。

    模型经常把“参考这张图，把背景换成海边”当成 edit（因为句子里有“换成”），
    但背景/场景/构图这类改造走 edit 是不动的。判据：
    有参考图 + （场景类改动 或 参考锚点）→ 改判 reference。
    局部改动（把衣服改成白色、头发换成黑色）仍然留在 edit，那是它擅长的活。
    除了 prompt，也看用户原话（hint）——模型会把“参考这张”从 prompt 里省掉。
    """
    if kind != KIND_EDIT or not request.references:
        return kind
    text = f"{request.prompt or ''} {getattr(request, 'hint', '') or ''}"
    if _matches(_SCENE_PATTERNS, text) or _matches(_REFERENCE_PATTERNS, text):
        # 场景类改动一定改判；纯参考锚点也要改判，除非同时有明确的局部改写词
        if _matches(_SCENE_PATTERNS, text):
            return KIND_REFERENCE
        if _matches(_REFERENCE_PATTERNS, text) and not _matches(_EDIT_PATTERNS, text):
            return KIND_REFERENCE
    return kind


#: 点名模型时的引导词：用/拿/换成/改成/要/model=
_NAME_LEAD_RE = re.compile(r"(?:用|拿|换成|改成|要|模型=)\s*([a-z0-9_\-]+)", re.I)
#: 「xxx风格 / xxx画风」
_NAME_STYLE_RE = re.compile(r"([a-z0-9_\-]+)\s*(?:风格|画风)", re.I)


def _name_in_hint(entry: ModelEntry, hint: str) -> str:
    """用户原话里是否点名了这个模型，返回命中的词。

    - 中文别名：直接子串命中（“柔光”“像素”这种词不会误伤）
    - 英文 key：必须带引导词（用 cat / cat 风格 / model=cat），
      否则 `cat girl` 这种普通 tag 会把 `cat` 模型误命中
    """
    if not hint:
        return ""
    for candidate in [entry.key, *entry.aliases]:
        name = str(candidate or "").strip()
        if len(name) < 2:
            continue
        if name.isascii():
            pattern = re.escape(name)
            if _NAME_LEAD_RE.search(hint) and re.search(
                rf"(?:用|拿|换成|改成|要|模型=)\s*{pattern}(?![a-z0-9])", hint, re.I
            ):
                return name
            if _NAME_STYLE_RE.search(hint) and re.search(
                rf"{pattern}\s*(?:风格|画风)", hint, re.I
            ):
                return name
        elif name in hint:
            return name
    return ""


def select_model(
    catalog: ModelCatalog,
    prompt: str,
    explicit: str = "",
    hint: str = "",
) -> tuple[ModelEntry, str]:
    """选模型，返回 (模型, 选择理由)。

    优先级：显式指定 > 原话里点名模型 > 风格关键词 > 默认。
    模型名只看用户原话，不看翻译后的英文 tag——`cat girl` 会误命中 `cat` 模型。
    """
    if explicit:
        return catalog.get(explicit), "explicit"

    for entry in catalog.items():
        hit = _name_in_hint(entry, hint)
        if hit:
            return entry, f"name:{hit}"

    text = f"{prompt or ''} {hint or ''}".strip()

    for pattern, key in _STYLE_HINTS:
        if not pattern.search(text):
            continue
        try:
            return catalog.get(key), f"style:{pattern.pattern[:24]}"
        except RoutingError:
            continue  # 该风格对应模型被停用，继续往下匹配
    return catalog.get(""), "default"

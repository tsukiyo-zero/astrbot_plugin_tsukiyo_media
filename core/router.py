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
_EDIT_PATTERNS = [
    r"改成|换成|改为|去掉|删掉|去除|抹掉|加个|加一个|修改|编辑|改一下|把.{0,12}(?:换|改)成",
    r"\bedit\b|\bchange\b|\bremove\b|\breplace\b|\bmodify\b|\binpaint\b",
]
#: 有参考图时，哪些说法算“参考这张画新的”
_REFERENCE_PATTERNS = [
    r"参考|以这张|照着|照这张|按照这张|按这张|仿照|画她|画他|画这个|换场景|换个场景|新姿势|换个姿势",
    r"\breference\b|\bbased on\b|\blike this\b|\bsame (?:person|character)\b|\bnew pose\b",
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


def route_kind(request: ImageRequest) -> str:
    """决定这次走哪条链路：selfie / edit / reference / text2img。"""
    explicit = request.resolved_kind()
    if explicit != KIND_AUTO:
        return explicit

    text = str(request.prompt or "")
    if request.references:
        # 有图：默认按“参考这张”处理，命中改写词才走 edit。
        return KIND_EDIT if _matches(_EDIT_PATTERNS, text) else KIND_REFERENCE
    return KIND_SELFIE if _matches(_SELFIE_PATTERNS, text) else KIND_TEXT2IMG


def correct_kind(kind: str, request: ImageRequest) -> str:
    """纠正“显式选了 edit、描述其实是在画新场景”的情况。

    模型经常把“参考这张图，画一张在海边散步”当成 edit。判据：
    有参考图 + 描述里是“参考/照着/换场景” + 没有“改成/换成/去掉”这类改写词。
    除了 prompt，也看用户原话（hint）——模型可能把“参考这张”从 prompt 里省掉了。
    """
    if kind != KIND_EDIT or not request.references:
        return kind
    text = f"{request.prompt or ''} {getattr(request, 'hint', '') or ''}"
    if _matches(_EDIT_PATTERNS, text):
        return kind
    if _matches(_REFERENCE_PATTERNS, text):
        return KIND_REFERENCE
    return kind


def _name_in_text(entry: ModelEntry, text: str) -> str:
    """模型 key/别名是否出现在文本里；返回命中的那个词，没命中返回空串。

    英文按词边界匹配（避免 `cat` 命中 `concatenate`），中文按子串匹配。
    """
    lowered = text.casefold()
    for candidate in [entry.key, *entry.aliases]:
        name = str(candidate or "").strip()
        if len(name) < 2:
            continue
        if name.isascii():
            if re.search(rf"(?<![a-z0-9]){re.escape(name.casefold())}(?![a-z0-9])", lowered):
                return name
        elif name in text:
            return name
    return ""


def select_model(
    catalog: ModelCatalog,
    prompt: str,
    explicit: str = "",
    hint: str = "",
) -> tuple[ModelEntry, str]:
    """选模型，返回 (模型, 选择理由)。

    优先级：显式指定 > 文本里点名了模型 > 风格关键词 > 默认。
    hint 是用户原话——模型翻译成英文 tag 后，画风词（“像素”“柔光”）容易丢，原话更可靠。
    """
    if explicit:
        return catalog.get(explicit), "explicit"

    text = f"{prompt or ''} {hint or ''}".strip()
    if text:
        for entry in catalog.items():
            hit = _name_in_text(entry, text)
            if hit:
                return entry, f"name:{hit}"

    for pattern, key in _STYLE_HINTS:
        if not pattern.search(text):
            continue
        try:
            return catalog.get(key), f"style:{pattern.pattern[:24]}"
        except RoutingError:
            continue  # 该风格对应模型被停用，继续往下匹配
    return catalog.get(""), "default"

"""意图路由与自动选模。规则优先，永远有兜底；不依赖任何 LLM 也能跑。"""
from __future__ import annotations

import re

from .catalog import ModelCatalog, ModelEntry
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


def select_model(
    catalog: ModelCatalog,
    prompt: str,
    explicit: str = "",
) -> tuple[ModelEntry, str]:
    """选模型，返回 (模型, 选择理由)。显式指定优先，其次风格关键词，最后默认。"""
    if explicit:
        return catalog.get(explicit), "explicit"
    for pattern, key in _STYLE_HINTS:
        if key in catalog.keys() and pattern.search(prompt or ""):
            return catalog.get(key), f"style:{pattern.pattern[:24]}"
    return catalog.get(catalog.default_key), "default"

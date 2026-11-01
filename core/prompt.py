"""提示词清洗与拼装。

原则：
1. 只做“去噪”，不改用户原意；
2. 每一段都记录来源，出问题能一眼看出是谁加进来的；
3. 工作流里的作者词由 binder 负责拼接，这里只产出“我们这一层”的词。
"""
from __future__ import annotations

import re

from .types import KIND_SELFIE, PromptBundle

#: 纯标签前缀：只去掉标签本身，保留后面的 tag
_LABELS = (
    "Positive prompt:",
    "Negative prompt:",
    "User image request:",
    "Scene preset:",
    "Concrete wardrobe specification:",
)

#: 规则段落：整段丢弃（从标题起到下一个标题或结尾）
_RULE_SECTIONS = (
    "Reference and wardrobe ruling:",
    "Composition and continuity:",
    "Image edit contract:",
    "Subject-count boundary:",
    "Camera portrait composition:",
)

#: ComfyUI 不认识的负权重语法 -1.5::xxx::
_NEG_WEIGHT_RE = re.compile(r"-?\d+(?:\.\d+)?::[^:]*::")
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_MULTI_SPACE_RE = re.compile(r"\s{2,}")
_MULTI_COMMA_RE = re.compile(r"\s*,\s*")


def _strip_rule_sections(text: str) -> str:
    """删掉“给模型看的规则段落”，但保留纯标签后面的 tag。"""
    value = text
    for label in _LABELS:
        value = re.sub(re.escape(label) + r"\s*", " ", value, flags=re.I)
    headings = "|".join(re.escape(h) for h in _RULE_SECTIONS)
    value = re.sub(
        rf"(?:{headings}).*?(?=(?:{headings})|$)",
        " ",
        value,
        flags=re.S | re.I,
    )
    return value


def strip_cjk_clauses(text: str) -> str:
    """CLIP 读不懂中文：整句含中文就丢弃该子句。"""
    pieces = re.split(r"[；;，,。\n]+", text)
    kept = [p.strip() for p in pieces if p.strip() and not _CJK_RE.search(p)]
    return ", ".join(kept)


def sanitize(text: str, *, drop_cjk: bool = False) -> str:
    """通用清洗：去规则段、去负权重语法、去标签噪声、压空白。"""
    value = str(text or "")
    if not value:
        return ""
    value = value.replace("\r", "\n")
    value = _strip_rule_sections(value)
    value = _NEG_WEIGHT_RE.sub(" ", value)
    value = re.sub(r"`{1,3}", " ", value)
    value = value.strip()
    if drop_cjk:
        value = strip_cjk_clauses(value)
    value = _MULTI_COMMA_RE.sub(", ", value)
    value = _MULTI_SPACE_RE.sub(" ", value)
    value = re.sub(r"(?:,\s*){2,}", ", ", value)
    return value.strip(" ,.;\n")


def join_parts(parts: list[str]) -> str:
    """按顺序拼接，去掉空段与重复段。"""
    seen: set[str] = set()
    out: list[str] = []
    for raw in parts:
        piece = str(raw or "").strip(" ,")
        if not piece:
            continue
        key = piece.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(piece)
    return ", ".join(out)


def build_prompt(
    *,
    user_prompt: str,
    kind: str,
    identity_prompt: str = "",
    fixed_prompt: str = "",
    global_negative: str = "",
    extra_positive: str = "",
    extra_negative: str = "",
    drop_cjk: bool = False,
) -> PromptBundle:
    """产出本次要追加到工作流里的正/负向词。"""
    parts: list[tuple[str, str]] = []

    if kind == KIND_SELFIE and identity_prompt:
        parts.append(("identity", sanitize(identity_prompt, drop_cjk=False)))
    if fixed_prompt:
        parts.append(("fixed", sanitize(fixed_prompt)))
    if user_prompt:
        parts.append(("user", sanitize(user_prompt, drop_cjk=drop_cjk)))
    if extra_positive:
        parts.append(("extra", sanitize(extra_positive, drop_cjk=drop_cjk)))

    positive = join_parts([text for _name, text in parts])

    negatives = [sanitize(global_negative)] if global_negative else []
    if extra_negative:
        negatives.append(sanitize(extra_negative))
    negative = join_parts(negatives)

    return PromptBundle(positive=positive, negative=negative, parts=parts)

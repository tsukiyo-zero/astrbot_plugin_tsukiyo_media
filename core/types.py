"""纯数据类型：不依赖 AstrBot，可单独测试。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

KIND_AUTO = "auto"
KIND_TEXT2IMG = "text2img"
KIND_SELFIE = "selfie"
KIND_EDIT = "edit"
KIND_REFERENCE = "reference"

VALID_KINDS = (KIND_TEXT2IMG, KIND_SELFIE, KIND_EDIT, KIND_REFERENCE)
#: 需要用户提供参考图的类型
REFERENCE_KINDS = (KIND_EDIT, KIND_REFERENCE)

_KIND_ALIASES = {
    "": KIND_AUTO,
    "auto": KIND_AUTO,
    "文生图": KIND_TEXT2IMG,
    "text2img": KIND_TEXT2IMG,
    "t2i": KIND_TEXT2IMG,
    "生成": KIND_TEXT2IMG,
    "自拍": KIND_SELFIE,
    "selfie": KIND_SELFIE,
    "拍照": KIND_SELFIE,
    "编辑": KIND_EDIT,
    "edit": KIND_EDIT,
    "改图": KIND_EDIT,
    "参考": KIND_REFERENCE,
    "reference": KIND_REFERENCE,
    "img2img": KIND_REFERENCE,
    "图生图": KIND_REFERENCE,
}


def normalize_kind(value: Any) -> str:
    """把各种写法（中英文/别名）归一成内部 kind。未知值返回 auto。"""
    text = str(value or "").strip().lower()
    return _KIND_ALIASES.get(text, KIND_AUTO)


@dataclass
class ImageRequest:
    """一次生图请求。插件对外只有一个入参对象。"""

    prompt: str = ""
    kind: str = KIND_AUTO
    model_key: str = ""
    references: list[str] = field(default_factory=list)
    width: int = 0
    height: int = 0
    seed: int = -1
    caption: str = ""
    extra_positive: str = ""
    extra_negative: str = ""
    source: str = ""
    #: 用户原话（只用于判断链路，不参与提示词）
    hint: str = ""

    def resolved_kind(self) -> str:
        return normalize_kind(self.kind)


@dataclass
class PromptBundle:
    """拼装好的正/负向词，并保留来源，便于排查“谁塞了什么”。"""

    positive: str = ""
    negative: str = ""
    parts: list[tuple[str, str]] = field(default_factory=list)

    def describe(self) -> str:
        return " | ".join(f"{name}={len(text)}" for name, text in self.parts)


@dataclass
class ImagePlan:
    """路由与选模完成后、提交前的中转结果。"""

    kind: str = KIND_TEXT2IMG
    workflow: str = ""
    model_key: str = ""
    prompt: PromptBundle = field(default_factory=PromptBundle)
    width: int = 0
    height: int = 0
    seed: int = -1
    ipadapter_weight: float | None = None
    denoise: float | None = None
    sampler_override: dict[str, Any] | None = None
    references: list[str] = field(default_factory=list)


@dataclass
class GenerationResult:
    """一次生图的最终结果。to_receipt() 给 LLM 工具返回 JSON 用。"""

    ok: bool = False
    kind: str = ""
    model_key: str = ""
    workflow: str = ""
    paths: list[str] = field(default_factory=list)
    elapsed_ms: int = 0
    prompt_id: str = ""
    seed: int = -1
    positive: str = ""
    negative: str = ""
    error: str = ""
    sent: bool = False

    def to_receipt(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "kind": self.kind,
            "model_key": self.model_key,
            "workflow": self.workflow,
            "paths": list(self.paths),
            "elapsed_ms": self.elapsed_ms,
            "prompt_id": self.prompt_id,
            "seed": self.seed,
            "sent": self.sent,
            "error": self.error[:400],
        }

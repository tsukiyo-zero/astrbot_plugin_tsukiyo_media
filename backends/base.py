"""后端抽象：所有生成后端（ComfyUI / 在线 API）都要满足这个契约。

v0.1 只有 ComfyUI 一个实现，`ImagePipeline` 仍直接持有 `ComfyUIClient`；
v0.2 起 `ImagePipeline` 只依赖本文件里的 `MediaBackend`，从而做到“换后端不改流水线”。

为什么要提前定：插件的定位是低耦合 + 可扩展（本地 ComfyUI、在线 API），
如果让 pipeline 直接长在 ComfyUI 的 submit/wait/fetch 上，接第二个后端时必然要拆它。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

#: 能力标签，供路由和 UI 查询
CAP_TEXT2IMG = "text2img"
CAP_SELFIE = "selfie"
CAP_EDIT = "edit"
CAP_REFERENCE = "reference"

MODALITY_IMAGE = "image"


@dataclass
class Asset:
    """一个产物（图片）。"""

    path: Path
    modality: str = MODALITY_IMAGE
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"path": str(self.path), "modality": self.modality, "meta": dict(self.meta)}


@dataclass
class RenderPlan:
    """后端无关的渲染指令：要什么，而不是怎么调 HTTP。"""

    workflow: str = ""
    positive: str = ""
    negative: str = ""
    width: int = 0
    height: int = 0
    seed: int = -1
    references: list[str] = field(default_factory=list)
    identity_image: str = ""
    source_image: str = ""
    prompt_mode: str = "append"
    ipadapter_weight: float | None = None
    denoise: float | None = None
    sampler_override: dict[str, Any] = field(default_factory=dict)
    modality: str = MODALITY_IMAGE
    backend_options: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class MediaBackend(Protocol):
    """后端契约。实现方只需保证这四样，流水线不关心内部协议。"""

    name: str
    capabilities: set[str]

    async def health(self) -> dict[str, Any]:
        """返回可用状态、版本、显存/队列等诊断信息。"""
        ...

    async def render(self, plan: RenderPlan) -> list[Asset]:
        """执行一次渲染，返回产物列表。"""
        ...

    async def close(self) -> None:
        """释放连接。"""
        ...

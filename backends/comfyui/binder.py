"""工作流绑定：靠“图结构”定位节点，不写死 node id、不依赖节点标题。

定位规则：
- sampler   = 唯一的 KSampler / KSamplerAdvanced
- positive / negative = 顺着 sampler 的 positive / negative 连线反查
- latent    = 顺着 sampler 的 latent_image 连线；EmptyLatentImage 或 VAEEncode
- save      = 唯一的 SaveImage
- 参考图    = 从 IPAdapter 的 image 输入往上找 LoadImage（身份参考）
              从 VAEEncode 的 pixels 输入往上找 LoadImage（图生图的源图）

这样作者换工作流、重排节点、改标题，插件都不用改代码。
"""
from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field
from typing import Any

from ...core.errors import BindError

_SAMPLERS = {"KSampler", "KSamplerAdvanced"}
_SAVERS = {"SaveImage"}
_EMPTY_LATENT = {"EmptyLatentImage"}
_VAE_ENCODE = {"VAEEncode", "VAEEncodeForInpaint"}
_IPADAPTER = {"IPAdapterAdvanced", "IPAdapter", "IPAdapterApply"}
_SCALES = {"ImageScale", "ImageScaleBy", "ImageScaleToTotalPixels"}
_LOADERS = {"LoadImage"}


def _nodes(workflow: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(nid): node
        for nid, node in workflow.items()
        if isinstance(node, dict) and "class_type" in node
    }


def _link(value: Any) -> str:
    """ComfyUI 的连线表示：[node_id, output_index]。"""
    if isinstance(value, (list, tuple)) and value and isinstance(value[0], (str, int)):
        return str(value[0])
    return ""


def _inputs(node: dict[str, Any]) -> dict[str, Any]:
    inputs = node.get("inputs")
    return inputs if isinstance(inputs, dict) else {}


def _walk_upstream(
    nodes: dict[str, dict[str, Any]],
    start: str,
    targets: set[str],
    *,
    max_depth: int = 8,
) -> str:
    """从 start 往上走单链输入，找到第一个 class_type 属于 targets 的节点。"""
    current = start
    seen: set[str] = set()
    for _ in range(max_depth):
        if not current or current in seen or current not in nodes:
            return ""
        seen.add(current)
        node = nodes[current]
        if node.get("class_type") in targets:
            return current
        # 只沿着第一个“连线型”输入上溯（ImageScale/VAEEncode 都是单链）
        nxt = ""
        for value in _inputs(node).values():
            nxt = _link(value)
            if nxt:
                break
        current = nxt
    return ""


def _unique(nodes: dict[str, dict[str, Any]], classes: set[str], role: str) -> str:
    hits = [nid for nid, node in nodes.items() if node.get("class_type") in classes]
    if not hits:
        raise BindError(f"工作流里找不到 {role} 节点（期望 class_type ∈ {sorted(classes)}）")
    if len(hits) > 1:
        raise BindError(f"工作流里有 {len(hits)} 个 {role} 节点，无法确定用哪个：{hits}")
    return hits[0]


@dataclass
class WorkflowRoles:
    """一个工作流里各功能节点的 id。"""

    sampler: str
    positive: str
    negative: str
    save: str
    checkpoint: str = ""
    empty_latent: str = ""
    vae_encode: str = ""
    image_scale: str = ""
    identity_ref: str = ""
    source_image: str = ""
    ipadapter: str = ""

    def as_dict(self) -> dict[str, str]:
        return {k: v for k, v in self.__dict__.items() if v}


def resolve_roles(workflow: dict[str, Any]) -> WorkflowRoles:
    """解析工作流结构，得到角色 → 节点 id 的映射。"""
    nodes = _nodes(workflow)
    if not nodes:
        raise BindError("工作流不是 ComfyUI API 格式（需要 节点id → {class_type, inputs}）")

    sampler = _unique(nodes, _SAMPLERS, "采样器（KSampler）")
    sampler_inputs = _inputs(nodes[sampler])

    positive = _link(sampler_inputs.get("positive"))
    negative = _link(sampler_inputs.get("negative"))
    if not positive or positive not in nodes:
        raise BindError("顺不到采样器的正向输入节点")
    if not negative or negative not in nodes:
        raise BindError("顺不到采样器的负向输入节点")

    save = _unique(nodes, _SAVERS, "保存节点（SaveImage）")

    latent_link = _link(sampler_inputs.get("latent_image"))
    latent_cls = nodes[latent_link].get("class_type") if latent_link in nodes else ""
    empty_latent = latent_link if latent_cls in _EMPTY_LATENT else ""
    vae_encode = latent_link if latent_cls in _VAE_ENCODE else ""

    image_scale = ""
    source_image = ""
    if vae_encode:
        pixels = _link(_inputs(nodes[vae_encode]).get("pixels"))
        if pixels and pixels in nodes and nodes[pixels].get("class_type") in _SCALES:
            image_scale = pixels
            source_image = _walk_upstream(nodes, pixels, _LOADERS)
        elif pixels and pixels in nodes and nodes[pixels].get("class_type") in _LOADERS:
            source_image = pixels

    ipadapter = ""
    identity_ref = ""
    for nid, node in nodes.items():
        if node.get("class_type") in _IPADAPTER:
            ipadapter = nid
            image_link = _link(_inputs(node).get("image"))
            if image_link:
                identity_ref = _walk_upstream(nodes, image_link, _LOADERS)
            break

    checkpoint = ""
    ckpts = [nid for nid, node in nodes.items() if node.get("class_type") == "CheckpointLoaderSimple"]
    if len(ckpts) == 1:
        checkpoint = ckpts[0]

    return WorkflowRoles(
        sampler=sampler,
        positive=positive,
        negative=negative,
        save=save,
        checkpoint=checkpoint,
        empty_latent=empty_latent,
        vae_encode=vae_encode,
        image_scale=image_scale,
        identity_ref=identity_ref,
        source_image=source_image,
        ipadapter=ipadapter,
    )


@dataclass
class BindValues:
    """要写进工作流的本次参数。空值 = 保持工作流原样。"""

    positive: str = ""
    negative: str = ""
    width: int = 0
    height: int = 0
    seed: int = -1
    filename_prefix: str = "tsukiyo"
    prompt_mode: str = "append"  # append | replace
    ipadapter_weight: float | None = None
    denoise: float | None = None
    sampler_override: dict[str, Any] = field(default_factory=dict)
    identity_image: str = ""
    source_image: str = ""


_ALLOWED_SAMPLER_KEYS = ("steps", "cfg", "sampler_name", "scheduler")


def _merge_text(existing: Any, addition: str, mode: str) -> str:
    """合并作者词与本次词：append 时按逗号去重，避免两遍 quality 词。"""
    base = str(existing or "").strip(" ,\n")
    extra = str(addition or "").strip(" ,\n")
    if not extra:
        return base
    if not base:
        return extra
    if str(mode).lower() == "replace":
        return extra

    seen: set[str] = set()
    merged: list[str] = []
    for chunk in f"{base}, {extra}".split(","):
        piece = chunk.strip()
        if not piece:
            continue
        key = piece.casefold()
        if key in seen:
            continue
        seen.add(key)
        merged.append(piece)
    return ", ".join(merged)


def apply_values(
    workflow: dict[str, Any],
    roles: WorkflowRoles,
    values: BindValues,
) -> dict[str, dict[str, Any]]:
    """按角色回填参数，返回可直接 POST /prompt 的 prompt 字典。"""
    wf = copy.deepcopy(workflow)
    nodes = _nodes(wf)

    # 正向 / 负向
    pos_node = nodes[roles.positive]
    pos_node.setdefault("inputs", {})["text"] = _merge_text(
        _inputs(pos_node).get("text"), values.positive, values.prompt_mode
    )
    neg_node = nodes[roles.negative]
    neg_node.setdefault("inputs", {})["text"] = _merge_text(
        _inputs(neg_node).get("text"), values.negative, values.prompt_mode
    )

    # 采样参数
    sampler = nodes[roles.sampler]
    sampler_inputs = sampler.setdefault("inputs", {})
    sampler_inputs["seed"] = int(values.seed) if values.seed >= 0 else random.randrange(0, 2**32)
    for key, val in (values.sampler_override or {}).items():
        if key in _ALLOWED_SAMPLER_KEYS and val not in (None, ""):
            sampler_inputs[key] = val
    if values.denoise is not None and "denoise" in sampler_inputs:
        sampler_inputs["denoise"] = float(values.denoise)

    # 尺寸
    if values.width > 0 and values.height > 0:
        if roles.empty_latent:
            latent_inputs = nodes[roles.empty_latent].setdefault("inputs", {})
            latent_inputs["width"] = int(values.width)
            latent_inputs["height"] = int(values.height)
        elif roles.image_scale:
            scale_inputs = nodes[roles.image_scale].setdefault("inputs", {})
            scale_inputs["width"] = int(values.width)
            scale_inputs["height"] = int(values.height)

    # IP-Adapter 权重
    if roles.ipadapter and values.ipadapter_weight is not None:
        nodes[roles.ipadapter].setdefault("inputs", {})["weight"] = float(values.ipadapter_weight)

    # 参考图 / 源图
    if roles.identity_ref and values.identity_image:
        nodes[roles.identity_ref].setdefault("inputs", {})["image"] = values.identity_image
    if roles.source_image and values.source_image:
        nodes[roles.source_image].setdefault("inputs", {})["image"] = values.source_image

    # 落盘前缀（只影响 ComfyUI 侧文件名）
    nodes[roles.save].setdefault("inputs", {})["filename_prefix"] = values.filename_prefix or "tsukiyo"

    return {
        nid: {"class_type": node.get("class_type", ""), "inputs": _inputs(node)}
        for nid, node in nodes.items()
    }

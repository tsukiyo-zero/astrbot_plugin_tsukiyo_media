"""流水线：路由 → 选模 → 拼词 → 绑定 → 提交 → 取图 → 落盘。

这一层不 import AstrBot，也不 import 任何陪伴类插件；只依赖 core 与 backends。
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from ..backends.comfyui.binder import BindValues, apply_values, resolve_roles
from ..backends.comfyui.client import ComfyUIClient
from .catalog import ModelCatalog
from .errors import BackendError, BindError, ConfigError, RoutingError, WorkflowNotFound
from .imaging import compress_image_bytes

HISTORY_LIMIT = 60
from .prompt import build_prompt
from .router import route_kind, select_model
from .types import (
    KIND_EDIT,
    KIND_REFERENCE,
    KIND_SELFIE,
    KIND_TEXT2IMG,
    GenerationResult,
    ImageRequest,
)


@dataclass
class KindProfile:
    """某一类出图的固定参数（来自配置）。"""

    workflow: str = ""
    fixed_prompt: str = ""
    identity_prompt: str = ""
    identity_image: str = ""
    ipadapter_weight: float | None = None
    denoise: float | None = None
    width: int = 0
    height: int = 0


@dataclass
class PipelineSettings:
    negative_prompt: str = ""
    prompt_mode: str = "append"
    strip_cjk: bool = False
    max_concurrent: int = 1
    filename_prefix: str = "tsukiyo"
    job_timeout: float = 180.0
    profiles: dict[str, KindProfile] = field(default_factory=dict)


class ImagePipeline:
    def __init__(
        self,
        *,
        client: ComfyUIClient,
        catalog: ModelCatalog,
        settings: PipelineSettings,
        workflow_dir: Path,
        output_dir: Path,
        history_path: Path | None = None,
    ) -> None:
        self.client = client
        self.catalog = catalog
        self.settings = settings
        self.workflow_dir = Path(workflow_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._workflow_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._semaphore = asyncio.Semaphore(max(1, int(settings.max_concurrent)))
        self.history: list[GenerationResult] = []
        self.history_path = Path(history_path) if history_path else None
        self.records: list[dict[str, Any]] = []
        self._load_history()

    # ---------- 历史持久化 ----------
    def _load_history(self) -> None:
        if self.history_path is None:
            return
        try:
            raw = json.loads(self.history_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - 首次运行/损坏都当空
            self.records = []
            return
        self.records = [item for item in raw if isinstance(item, dict)][-HISTORY_LIMIT:]

    def _save_history(self, result: GenerationResult, request: ImageRequest | None = None) -> None:
        if self.history_path is None:
            return
        record = result.to_receipt()
        record["ts"] = int(time.time())
        record["positive"] = result.positive[:4000]
        record["negative"] = result.negative[:2000]
        if request is not None:
            # 供"重跑"用：原始请求，而不是最终的拼接结果
            record["request"] = {
                "prompt": request.prompt,
                "kind": request.kind,
                "model_key": request.model_key,
                "width": request.width,
                "height": request.height,
                "seed": request.seed,
                "extra_negative": request.extra_negative,
                "references": list(request.references[:1]),
            }
        self.records = (self.records + [record])[-HISTORY_LIMIT:]
        try:
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.history_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self.records, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.history_path)
        except OSError:
            pass

    # ---------- 资源 ----------
    def workflow_path(self, name: str) -> Path:
        candidate = Path(name)
        path = candidate if candidate.is_absolute() else (self.workflow_dir / name)
        if not path.exists():
            raise WorkflowNotFound(f"工作流不存在：{path}")
        return path

    def load_workflow(self, name: str) -> dict[str, Any]:
        import json

        path = self.workflow_path(name)
        mtime = path.stat().st_mtime
        cached = self._workflow_cache.get(name)
        if cached and cached[0] == mtime:
            return cached[1]
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"工作流不是合法 JSON：{path}（{exc}）") from exc
        if not isinstance(data, dict) or not data:
            raise ConfigError(f"工作流内容异常：{path}")
        self._workflow_cache[name] = (mtime, data)
        return data

    # ---------- 规划 ----------
    def build_plan(self, request: ImageRequest) -> tuple[str, Any, KindProfile]:
        """返回 (kind, 工作流名, profile)。"""
        kind = route_kind(request)
        if kind in (KIND_EDIT, KIND_REFERENCE) and not request.references:
            raise RoutingError("这条链路需要你先发一张图（或引用一张图）")

        profile = self.settings.profiles.get(kind) or KindProfile()
        if kind == KIND_TEXT2IMG:
            entry, _reason = select_model(self.catalog, request.prompt, request.model_key)
            workflow = entry.workflow
            profile = KindProfile(
                workflow=workflow,
                fixed_prompt=profile.fixed_prompt,
                width=int(entry.author_params.get("width") or 0),
                height=int(entry.author_params.get("height") or 0),
            )
            return kind, entry, profile

        if not profile.workflow:
            raise ConfigError(f"配置里缺少 {kind} 的工作流")

        # 自拍 / 参考图 / 编辑：工作流结构固定（带 IP-Adapter 或 img2img），
        # 但底模与作者参数可以跟着所选模型走；没显式选模型就保持 profile 原样。
        entry = None
        model_key = str(request.model_key or "").strip()
        if model_key:
            entry = self.catalog.get(model_key)
            params = entry.author_params or {}
            profile = replace(
                profile,
                width=int(params.get("width") or profile.width or 0),
                height=int(params.get("height") or profile.height or 0),
            )
        return kind, entry, profile

    def checkpoint_of(self, workflow_name: str) -> str:
        """读某个工作流用的底模文件名；读不到就返回空（保持专用工作流原样）。"""
        try:
            workflow = self.load_workflow(workflow_name)
            roles = resolve_roles(workflow)
        except (WorkflowNotFound, ConfigError, BindError):
            return ""
        if not roles.checkpoint:
            return ""
        return str(workflow.get(roles.checkpoint, {}).get("inputs", {}).get("ckpt_name") or "")

    # ---------- 主流程 ----------
    async def generate(self, request: ImageRequest, on_submit=None) -> GenerationResult:
        started = time.monotonic()
        result = GenerationResult(seed=int(request.seed), kind=request.resolved_kind())
        try:
            async with self._semaphore:
                await self._run(request, result, on_submit=on_submit)
        except (RoutingError, WorkflowNotFound, ConfigError, BackendError) as exc:
            result.ok = False
            result.error = str(exc)
        except Exception as exc:  # pragma: no cover - 兜底，不让插件崩
            result.ok = False
            result.error = f"{type(exc).__name__}: {exc}"
        finally:
            result.elapsed_ms = int((time.monotonic() - started) * 1000)
            self.history = (self.history + [result])[-10:]
            self._save_history(result, request)
        return result

    async def _run(self, request: ImageRequest, result: GenerationResult, on_submit=None) -> None:
        kind, entry, profile = self.build_plan(request)
        result.kind = kind
        result.model_key = entry.key if entry else (request.model_key or kind)
        result.workflow = profile.workflow

        bundle = build_prompt(
            user_prompt=request.prompt,
            kind=kind,
            identity_prompt=profile.identity_prompt,
            fixed_prompt=profile.fixed_prompt,
            global_negative=self.settings.negative_prompt,
            extra_positive=request.extra_positive,
            extra_negative=request.extra_negative,
            drop_cjk=self.settings.strip_cjk,
        )
        result.positive = bundle.positive
        result.negative = bundle.negative

        workflow = self.load_workflow(profile.workflow)
        roles = resolve_roles(workflow)

        identity_image = ""
        source_image = ""
        if request.references:
            reference_name = await self._upload_reference(request.references[0])
            if kind == KIND_EDIT:
                source_image = reference_name
            else:
                identity_image = reference_name
        elif kind == KIND_SELFIE and profile.identity_image:
            identity_image = await self._upload_reference(profile.identity_image)

        width = int(request.width or profile.width or 0)
        height = int(request.height or profile.height or 0)

        # 专用链路选了模型时，把底模换成该模型工作流里的 checkpoint
        ckpt_name = ""
        if entry is not None and kind != KIND_TEXT2IMG:
            ckpt_name = self.checkpoint_of(entry.workflow)

        values = BindValues(
            positive=bundle.positive,
            negative=bundle.negative,
            width=width,
            height=height,
            seed=int(request.seed),
            filename_prefix=self.settings.filename_prefix,
            prompt_mode=self.settings.prompt_mode,
            ipadapter_weight=profile.ipadapter_weight,
            denoise=profile.denoise,
            sampler_override=(entry.author_params if entry else {}),
            identity_image=identity_image,
            source_image=source_image,
            ckpt_name=ckpt_name,
        )
        prompt = apply_values(workflow, roles, values)
        result.seed = int(prompt[roles.sampler]["inputs"]["seed"])
        # 记录“真正提交给 ComfyUI 的全文”，方便和 /history 对照审计
        result.positive = str(prompt[roles.positive]["inputs"].get("text") or "")
        result.negative = str(prompt[roles.negative]["inputs"].get("text") or "")

        prompt_id = await self.client.submit(prompt)
        result.prompt_id = prompt_id
        if on_submit is not None:
            try:
                on_submit(prompt_id)
            except Exception:  # noqa: BLE001 - 回调失败不影响出图
                pass
        outputs = await self.client.wait(prompt_id, timeout=self.settings.job_timeout)
        result.paths = await self._save_outputs(outputs, prompt_id)
        if not result.paths:
            raise BackendError("ComfyUI 执行完成但没有返回图片")
        result.ok = True

    # ---------- 取图落盘 ----------
    async def _save_outputs(self, outputs: dict[str, Any], prompt_id: str) -> list[str]:
        saved: list[str] = []
        stamp = time.strftime("%Y%m%d_%H%M%S")
        for _node_id, node_out in (outputs or {}).items():
            if not isinstance(node_out, dict):
                continue
            for image in node_out.get("images") or ():
                if not isinstance(image, dict):
                    continue
                filename = str(image.get("filename") or "")
                if not filename:
                    continue
                data = await self.client.fetch(
                    filename,
                    subfolder=str(image.get("subfolder") or ""),
                    folder_type=str(image.get("type") or "output"),
                )
                suffix = Path(filename).suffix or ".png"
                target = self.output_dir / f"tsukiyo_{stamp}_{prompt_id[:8]}_{uuid.uuid4().hex[:6]}{suffix}"
                target.write_bytes(data)
                saved.append(str(target))
        return saved

    async def _upload_reference(self, path: str) -> str:
        source = Path(str(path))
        if not source.exists():
            raise RoutingError(f"参考图不存在：{source}")
        data = source.read_bytes()
        name = source.name
        compressed, suffix = compress_image_bytes(data)
        if compressed is not data and suffix:
            data = compressed
            name = source.stem + suffix
        return await self.client.upload_image(data, name)

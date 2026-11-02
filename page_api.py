"""插件 Web API：给 views/studio 页面提供状态、生成、历史、图片读取。

AstrBot 的插件视图通过 bridge 调用这些接口，路由前缀固定为 /<插件名>。
"""
from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import time
from pathlib import Path
from typing import Any

from astrbot.api import logger

from .backends.comfyui.binder import resolve_roles
from .core.imaging import compress_image_bytes
from .core.types import ImageRequest, normalize_kind

PLUGIN_NAME = "astrbot_plugin_tsukiyo_media"

#: 设置页允许写入的配置字段（其余一律忽略，避免误改）
CONFIG_WHITELIST: dict[str, set[str]] = {
    "comfyui": {"base_url", "connect_timeout_seconds", "job_timeout_seconds", "poll_interval_seconds"},
    "generation": {"negative_prompt", "prompt_mode", "strip_non_english", "max_concurrent", "filename_prefix"},
    "paths": {"workflow_dir", "output_dir", "host_data_dir"},
    "selfie": {"workflow", "fixed_prompt", "identity_prompt", "reference_image", "ipadapter_weight", "width", "height"},
    "reference": {"workflow", "fixed_prompt", "ipadapter_weight", "width", "height"},
    "edit": {"workflow", "fixed_prompt", "denoise", "width", "height"},
    "delivery": {"allow_private", "allow_group", "group_block_nsfw"},
}

try:  # AstrBot >= 4.16 提供 astrbot.api.web
    from astrbot.api.web import error_response, file_response, json_response, request, stream_response

    WEB_API_AVAILABLE = True
except Exception:  # pragma: no cover - 老版本降级
    WEB_API_AVAILABLE = False
    error_response = file_response = json_response = stream_response = None  # type: ignore[assignment]
    request = None  # type: ignore[assignment]


def _as_list(value: Any) -> list[str]:
    """接受数组或逗号分隔字符串，统一成去空的字符串数组。"""
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.replace("，", ",").split(",") if item.strip()]
    return []


class PageAPI:
    """把插件能力暴露成 Web API。持有 plugin 引用，不复制状态。"""

    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin

    # ------------------------------------------------------------------ 注册
    def register(self, context: Any) -> bool:
        if not WEB_API_AVAILABLE:
            logger.warning("[TsukiyoMedia] 当前 AstrBot 版本没有 astrbot.api.web，跳过插件页面 API")
            return False
        register = getattr(context, "register_web_api", None)
        if not callable(register):
            logger.warning("[TsukiyoMedia] 当前 AstrBot 版本不支持 register_web_api，跳过插件页面")
            return False
        routes = (
            ("/status", self.status, ["GET"], "生成后端状态与模型列表"),
            ("/generate", self.generate, ["POST"], "提交一次生成"),
            ("/upload", self.upload, ["POST"], "上传参考图"),
            ("/history", self.history, ["GET"], "最近生成记录"),
            ("/file", self.file, ["GET"], "读取生成产物"),
            ("/settings", self.settings, ["GET"], "读取设置"),
            ("/settings", self.save_settings, ["POST"], "保存设置"),
            ("/models", self.save_models, ["POST"], "保存模型开关/默认/工作流"),
            ("/workflows", self.workflows, ["GET"], "工作流文件列表"),
            ("/workflows/inspect", self.inspect_workflow, ["GET"], "读取工作流作者参数"),
            ("/workflows/notes", self.save_workflow_notes, ["POST"], "保存工作流说明"),
            ("/workflows/upload", self.upload_workflow, ["POST"], "上传工作流 JSON"),
            ("/progress", self.progress, ["GET"], "生成进度 SSE"),
            ("/generate/stream", self.generate_stream, ["POST"], "生成并推送进度 SSE"),
            ("/test", self.test_backend, ["POST"], "测试后端连接"),
        )
        for path, handler, methods, desc in routes:
            register(f"/{PLUGIN_NAME}{path}", handler, methods, desc)
        logger.info("[TsukiyoMedia] 插件页面 API 已注册：/%s/*", PLUGIN_NAME)
        return True

    # ------------------------------------------------------------------ 接口
    async def status(self):
        plugin = self.plugin
        payload: dict[str, Any] = {
            "ok": True,
            "models": plugin.api.list_models() if plugin.api else [],
            "default_model": plugin.api.default_model if plugin.api else "",
            "defaults": {
                "negative": (plugin.pipeline.settings.negative_prompt if plugin.pipeline else ""),
                "prompt_mode": (plugin.pipeline.settings.prompt_mode if plugin.pipeline else "append"),
            },
            "backend": {"online": False, "error": ""},
        }
        try:
            stats = await plugin.client.system_stats()
            queue = await plugin.client.queue_state()
            device = (stats.get("devices") or [{}])[0]
            payload["backend"] = {
                "online": True,
                "version": (stats.get("system") or {}).get("comfyui_version", ""),
                "vram_total_gb": round(float(device.get("vram_total") or 0) / (1024**3), 1),
                "vram_free_gb": round(float(device.get("vram_free") or 0) / (1024**3), 1),
                "running": len(queue.get("queue_running") or ()),
                "pending": len(queue.get("queue_pending") or ()),
            }
        except Exception as exc:  # noqa: BLE001 - 页面需要看到失败原因
            payload["backend"] = {"online": False, "error": str(exc)[:300]}
        return json_response(payload)

    async def generate(self):
        payload = await request.json(default={})
        prompt = str(payload.get("prompt") or "").strip()
        if not prompt:
            return error_response("prompt 不能为空", status_code=400)
        plugin = self.plugin
        if plugin.pipeline is None:
            return error_response("插件尚未初始化", status_code=503)
        reference_path = str(payload.get("reference_path") or "").strip()
        req = ImageRequest(
            prompt=prompt,
            kind=normalize_kind(payload.get("kind") or "auto"),
            model_key=str(payload.get("model_key") or ""),
            references=[reference_path] if reference_path else [],
            width=int(payload.get("width") or 0),
            height=int(payload.get("height") or 0),
            seed=int(payload.get("seed") or -1),
            extra_negative=str(payload.get("negative") or ""),
            extra_positive=str(payload.get("extra_positive") or ""),
            source="ui",
        )
        result = await plugin.pipeline.generate(req)
        data = result.to_receipt()
        data["kind"] = result.kind
        # 页面要显示“实际提交给 ComfyUI 的正负向词”，to_receipt 里没有这两项
        data["positive"] = result.positive
        data["negative"] = result.negative
        data["images"] = [self._image_info(path) for path in result.paths]
        return json_response(data)

    async def upload(self):
        """接收页面传上来的参考图（base64 JSON），存到插件数据目录，返回容器内路径。

        页面通过 bridge.apiPost 走 JSON，所以这里不做 multipart，直接收 base64。
        """
        plugin = self.plugin
        payload = await request.json(default={})
        raw = str(payload.get("data") or "")
        if not raw:
            return error_response("缺少 data（base64）", status_code=400)
        if "," in raw[:64]:  # 允许直接传 dataURL
            raw = raw.split(",", 1)[1]
        try:
            blob = base64.b64decode(raw, validate=False)
        except Exception:  # noqa: BLE001
            return error_response("base64 解码失败", status_code=400)
        if not blob:
            return error_response("空文件", status_code=400)
        if len(blob) > 20 * 1024 * 1024:
            return error_response("参考图超过 20MB", status_code=413)
        blob, compressed_suffix = compress_image_bytes(blob)
        suffix = Path(str(payload.get("filename") or "upload.png")).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            suffix = ".png"
        if compressed_suffix:
            suffix = compressed_suffix
        target_dir = plugin.reference_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"ui_{int(time.time() * 1000)}{suffix}"
        try:
            target.write_bytes(blob)
        except OSError as exc:
            return error_response(f"保存失败：{exc}", status_code=500)
        return json_response(
            {"ok": True, "path": str(target), "name": target.name, "size": target.stat().st_size}
        )

    async def history(self):
        plugin = self.plugin
        limit = request.query.get("limit", 12, type=int)
        items: list[dict[str, Any]] = []
        known: dict[str, dict[str, Any]] = {}
        if plugin.pipeline:
            for record in reversed(plugin.pipeline.records[-limit:]):
                for path in record.get("paths") or ():
                    known[str(path)] = record
        output_dir = plugin.pipeline.output_dir if plugin.pipeline else None
        if output_dir and output_dir.exists():
            files = sorted(
                (p for p in output_dir.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )[:limit]
            for path in files:
                info = self._image_info(str(path))
                info["receipt"] = known.get(str(path), {})
                items.append(info)
        return json_response({"ok": True, "items": items})

    async def progress(self):
        """SSE：轮询 ComfyUI 队列/历史，把排队与生成状态推给页面。"""
        prompt_id = request.query.get("prompt_id", "", type=str) or ""
        if not prompt_id:
            return error_response("缺少 prompt_id", status_code=400)
        client = self.plugin.client

        async def events():
            started = time.time()
            last_state = ""
            while True:
                elapsed = round(time.time() - started, 1)
                state = "unknown"
                payload: dict[str, Any] = {"elapsed": elapsed, "prompt_id": prompt_id}
                try:
                    entry = await client.history_entry(prompt_id)
                    if entry:
                        status = str((entry.get("status") or {}).get("status_str") or "")
                        state = "error" if status == "error" else "done"
                    else:
                        queue = await client.queue_state()
                        running = [item[1] for item in queue.get("queue_running") or [] if len(item) > 1]
                        pending = [item[1] for item in queue.get("queue_pending") or [] if len(item) > 1]
                        if prompt_id in running:
                            state = "running"
                        elif prompt_id in pending:
                            state = "queued"
                            payload["position"] = pending.index(prompt_id) + 1
                        else:
                            state = "waiting"
                except Exception as exc:  # noqa: BLE001
                    state = "error"
                    payload["error"] = str(exc)[:200]
                payload["state"] = state
                if state != last_state or state in {"running", "queued", "waiting"}:
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    last_state = state
                if state in {"done", "error"}:
                    return
                if elapsed > 600:
                    payload["state"] = "timeout"
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    return
                await asyncio.sleep(0.8)

        return stream_response(events())

    async def generate_stream(self):
        """POST + SSE：提交后立刻推 prompt_id，随后持续推排队/生成状态，最后推结果。"""
        payload = await request.json(default={})
        prompt = str(payload.get("prompt") or "").strip()
        if not prompt:
            return error_response("prompt 不能为空", status_code=400)
        plugin = self.plugin
        if plugin.pipeline is None:
            return error_response("插件尚未初始化", status_code=503)
        req = ImageRequest(
            prompt=prompt,
            kind=normalize_kind(payload.get("kind") or "auto"),
            model_key=str(payload.get("model_key") or ""),
            references=[str(payload.get("reference_path"))] if payload.get("reference_path") else [],
            width=int(payload.get("width") or 0),
            height=int(payload.get("height") or 0),
            seed=int(payload.get("seed") or -1),
            extra_negative=str(payload.get("negative") or ""),
            extra_positive=str(payload.get("extra_positive") or ""),
            source="ui",
        )
        client = plugin.client
        holder: dict[str, str] = {}

        def on_submit(prompt_id: str) -> None:
            holder["prompt_id"] = prompt_id

        task = asyncio.create_task(plugin.pipeline.generate(req, on_submit=on_submit))

        async def events():
            started = time.time()
            last = ""
            try:
                while not task.done():
                    elapsed = round(time.time() - started, 1)
                    prompt_id = holder.get("prompt_id", "")
                    state = "submitting"
                    extra: dict[str, Any] = {"elapsed": elapsed, "prompt_id": prompt_id}
                    if prompt_id:
                        try:
                            entry = await client.history_entry(prompt_id)
                            if entry:
                                status = str((entry.get("status") or {}).get("status_str") or "")
                                state = "error" if status == "error" else "finishing"
                            else:
                                queue = await client.queue_state()
                                running = [item[1] for item in queue.get("queue_running") or [] if len(item) > 1]
                                pending = [item[1] for item in queue.get("queue_pending") or [] if len(item) > 1]
                                if prompt_id in running:
                                    state = "running"
                                elif prompt_id in pending:
                                    state = "queued"
                                    extra["position"] = pending.index(prompt_id) + 1
                                else:
                                    state = "waiting"
                        except Exception as exc:  # noqa: BLE001
                            extra["poll_error"] = str(exc)[:160]
                    if state != last:
                        yield f"data: {json.dumps({'state': state, **extra}, ensure_ascii=False)}\n\n"
                        last = state
                    elif state in {"running", "queued", "waiting"} and int(elapsed) % 3 == 0:
                        yield f"data: {json.dumps({'state': state, **extra}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0.8)

                result = task.result()
                data = result.to_receipt()
                data["kind"] = result.kind
                data["images"] = [self._image_info(path) for path in result.paths]
                data["state"] = "done" if result.ok else "failed"
                data["elapsed_total"] = round(time.time() - started, 1)
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            except asyncio.CancelledError:
                task.cancel()
                raise
            except Exception as exc:  # noqa: BLE001
                yield f"data: {json.dumps({'state': 'failed', 'error': str(exc)[:300]}, ensure_ascii=False)}\n\n"

        return stream_response(events())

    async def file(self):
        plugin = self.plugin
        raw = request.query.get("path", "", type=str) or ""
        if not raw:
            return error_response("缺少 path", status_code=400)
        roots = []
        if plugin.pipeline:
            roots.append(plugin.pipeline.output_dir.resolve())
        roots.append(plugin.reference_dir.resolve())
        if not roots:
            return error_response("输出目录未初始化", status_code=503)
        try:
            target = Path(raw).expanduser().resolve()
        except OSError:
            return error_response("非法路径", status_code=400)
        if not any(target == root or root in target.parents for root in roots):
            return error_response("只允许读取插件自己的产物/参考图目录", status_code=403)
        if not target.is_file():
            return error_response("文件不存在", status_code=404)
        content_type = mimetypes.guess_type(target.name)[0] or "image/png"
        return file_response(target, filename=target.name, content_type=content_type)

    # ------------------------------------------------------------------ 设置
    async def settings(self):
        return json_response(self._settings_payload())

    async def save_settings(self):
        payload = await request.json(default={})
        patch = payload.get("config") if isinstance(payload, dict) else None
        if not isinstance(patch, dict) or not patch:
            return error_response("config 不能为空", status_code=400)
        filtered = self._filter_config(patch)
        if not filtered:
            return error_response("没有可保存的字段", status_code=400)
        try:
            await self.plugin.apply_patch(filtered)
        except Exception as exc:  # noqa: BLE001
            return error_response(f"保存失败：{exc}", status_code=500)
        return json_response(self._settings_payload())

    async def save_models(self):
        """整表保存：支持新增（upsert）、删除、改字段、切默认。

        payload = {"models": {key: {...}}, "delete": ["key"], "default": "key"}
        模型字段：label / workflow / enabled / aliases / tags / group / desc
        """
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("payload 必须是对象", status_code=400)
        catalog_path = Path(self.plugin.catalog.path)
        try:
            raw = json.loads(catalog_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            return error_response(f"读取 models.json 失败：{exc}", status_code=500)
        models = raw.get("models") or {}

        removed = payload.get("delete") or []
        if isinstance(removed, list):
            for key in removed:
                models.pop(str(key), None)

        patch = payload.get("models") or {}
        if isinstance(patch, dict):
            for key, item in patch.items():
                key = str(key or "").strip()
                if not key or not isinstance(item, dict):
                    continue
                existing = models.get(key)
                entry = dict(existing) if isinstance(existing, dict) else {}
                if "label" in item:
                    entry["label"] = str(item.get("label") or key)
                workflow = str(item.get("workflow") or "").strip()
                if workflow:
                    entry["workflow"] = workflow
                elif not entry.get("workflow"):
                    return error_response(f"模型 {key} 缺少 workflow", status_code=400)
                if "enabled" in item:
                    entry["enabled"] = bool(item["enabled"])
                if "group" in item:
                    group = str(item.get("group") or "").strip().lower()
                    entry["group"] = group if group in {"anime", "real", "other"} else ""
                if "desc" in item:
                    entry["desc"] = str(item.get("desc") or "").strip()[:80]
                if "aliases" in item:
                    entry["aliases"] = _as_list(item.get("aliases"))
                if "tags" in item:
                    entry["tags"] = _as_list(item.get("tags"))
                models[key] = entry

        if not models:
            return error_response("至少保留一个模型", status_code=400)

        default = str(payload.get("default") or "").strip()
        if default:
            if default not in models:
                return error_response(f"未知模型：{default}", status_code=400)
            raw["default"] = default
        elif raw.get("default") not in models:
            raw["default"] = next(iter(models))

        raw["models"] = models
        try:
            tmp = catalog_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            tmp.replace(catalog_path)
            self.plugin.catalog.load()
        except Exception as exc:  # noqa: BLE001
            return error_response(f"写入 models.json 失败：{exc}", status_code=500)
        return json_response(self._settings_payload())

    async def save_workflow_notes(self):
        """保存工作流文件的说明（存插件数据目录，不改工作流本身）。"""
        payload = await request.json(default={})
        notes = payload.get("notes") if isinstance(payload, dict) else None
        if not isinstance(notes, dict):
            return error_response("notes 必须是对象", status_code=400)
        clean = {str(k): str(v or "") for k, v in notes.items() if str(k).endswith(".json")}
        path = self._notes_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(clean, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            return error_response(f"写入说明失败：{exc}", status_code=500)
        return json_response(self._settings_payload())

    async def upload_workflow(self):
        """上传一个 ComfyUI API 格式工作流 JSON。"""
        payload = await request.json(default={})
        raw_b64 = str(payload.get("data") or "")
        if "," in raw_b64[:64]:
            raw_b64 = raw_b64.split(",", 1)[1]
        try:
            blob = base64.b64decode(raw_b64, validate=False)
        except Exception:  # noqa: BLE001
            return error_response("base64 解码失败", status_code=400)
        if not blob:
            return error_response("空文件", status_code=400)
        if len(blob) > 4 * 1024 * 1024:
            return error_response("工作流文件超过 4MB", status_code=413)
        try:
            data = json.loads(blob.decode("utf-8"))
        except Exception:  # noqa: BLE001
            return error_response("不是合法 JSON", status_code=400)
        if not isinstance(data, dict) or not any(
            isinstance(node, dict) and node.get("class_type") for node in data.values()
        ):
            return error_response("不是 ComfyUI API 格式（需要 节点id → {class_type, inputs}）", status_code=400)

        name = Path(str(payload.get("filename") or "workflow.json")).name
        if not name.endswith(".json"):
            name += ".json"
        workflow_dir = self.plugin.pipeline.workflow_dir if self.plugin.pipeline else self.plugin.root / "workflows"
        workflow_dir.mkdir(parents=True, exist_ok=True)
        target = workflow_dir / name
        if target.exists() and not bool(payload.get("overwrite")):
            return error_response(f"{name} 已存在，勾选覆盖再上传", status_code=409)
        try:
            target.write_bytes(blob)
        except OSError as exc:
            return error_response(f"写入失败：{exc}", status_code=500)
        return json_response({"ok": True, "name": name, **self._settings_payload()})

    async def inspect_workflow(self):
        """读取一个工作流的作者参数（steps/cfg/采样器/尺寸/IPA 权重/结构类型）。"""
        name = request.query.get("name", "", type=str) or ""
        if not name:
            return error_response("缺少 name", status_code=400)
        plugin = self.plugin
        if plugin.pipeline is None:
            return error_response("插件尚未初始化", status_code=503)
        try:
            workflow = plugin.pipeline.load_workflow(name)
            roles = resolve_roles(workflow)
        except Exception as exc:  # noqa: BLE001
            return error_response(f"解析工作流失败：{exc}", status_code=400)

        nodes = {nid: node for nid, node in workflow.items() if isinstance(node, dict)}
        sampler = (nodes.get(roles.sampler) or {}).get("inputs") or {}
        checkpoint = ""
        if roles.checkpoint:
            checkpoint = str(
                ((nodes.get(roles.checkpoint) or {}).get("inputs") or {}).get("ckpt_name") or ""
            )
        data: dict[str, Any] = {
            "ok": True,
            "name": name,
            "checkpoint": checkpoint,
            "steps": sampler.get("steps"),
            "cfg": sampler.get("cfg"),
            "sampler_name": sampler.get("sampler_name"),
            "scheduler": sampler.get("scheduler"),
            "denoise": sampler.get("denoise"),
            "width": None,
            "height": None,
            "ipadapter_weight": None,
            "has_identity_ref": bool(roles.identity_ref),
            "has_source_image": bool(roles.source_image),
            "mode": "img2img" if roles.vae_encode else "text2img",
        }
        if roles.empty_latent:
            latent = (nodes.get(roles.empty_latent) or {}).get("inputs") or {}
            data["width"], data["height"] = latent.get("width"), latent.get("height")
        elif roles.image_scale:
            scale = (nodes.get(roles.image_scale) or {}).get("inputs") or {}
            data["width"], data["height"] = scale.get("width"), scale.get("height")
        if roles.ipadapter:
            ipa = (nodes.get(roles.ipadapter) or {}).get("inputs") or {}
            data["ipadapter_weight"] = ipa.get("weight")
        return json_response(data)

    async def workflows(self):
        try:
            files = self._workflow_files()
        except Exception as exc:  # noqa: BLE001
            return error_response(str(exc), status_code=500)
        return json_response({"ok": True, "items": files})

    async def test_backend(self):
        try:
            stats = await self.plugin.client.system_stats()
            queue = await self.plugin.client.queue_state()
        except Exception as exc:  # noqa: BLE001
            return json_response({"ok": False, "error": str(exc)[:300]})
        device = (stats.get("devices") or [{}])[0]
        return json_response(
            {
                "ok": True,
                "version": (stats.get("system") or {}).get("comfyui_version", ""),
                "vram_total_gb": round(float(device.get("vram_total") or 0) / (1024**3), 1),
                "vram_free_gb": round(float(device.get("vram_free") or 0) / (1024**3), 1),
                "running": len(queue.get("queue_running") or ()),
                "pending": len(queue.get("queue_pending") or ()),
            }
        )

    # ------------------------------------------------------------------ 设置辅助
    def _settings_payload(self) -> dict[str, Any]:
        plugin = self.plugin
        cfg = plugin.config if isinstance(plugin.config, dict) else {}
        workflow_dir = plugin.pipeline.workflow_dir if plugin.pipeline else plugin.root / "workflows"
        return {
            "ok": True,
            "version": getattr(plugin, "_version", ""),
            "config": {
                section: {k: (cfg.get(section) or {}).get(k) for k in keys}
                for section, keys in CONFIG_WHITELIST.items()
            },
            "models": [
                {
                    "key": entry.key,
                    "label": entry.label,
                    "enabled": entry.enabled,
                    "workflow": entry.workflow,
                    "is_default": entry.key == plugin.catalog.default_key,
                    "tags": list(entry.tags),
                    "aliases": list(entry.aliases),
                    "group": entry.group,
                    "desc": entry.desc,
                    "author_params": dict(entry.author_params),
                }
                for entry in plugin.catalog.items()
            ],
            "workflows": self._workflow_files(),
            "workflow_usage": self._workflow_usage(),
            "workflow_notes": self._workflow_notes(),
            "backend": {
                "type": "comfyui",
                "label": "ComfyUI（本地 HTTP）",
                "base_url": str((cfg.get("comfyui") or {}).get("base_url") or ""),
            },
            "diagnostics": self._diagnostics(),
            "paths": {
                "workflow_dir": str(workflow_dir),
                "output_dir": str(plugin.pipeline.output_dir) if plugin.pipeline else "",
                "models_json": str(plugin.catalog.path),
                "reference_dir": str(plugin.reference_dir),
                "plugin_dir": str(plugin.root),
                "host_data_dir": cfg.get("paths", {}).get("host_data_dir", "") if isinstance(cfg.get("paths"), dict) else "",
                "host_workflow_dir": self._host_path(str(workflow_dir)),
                "host_plugin_dir": self._host_path(str(plugin.root)),
            },
        }

    def _notes_path(self) -> Path:
        return self.plugin.data_dir / "workflow_notes.json"

    def _workflow_notes(self) -> dict[str, str]:
        path = self._notes_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}

    def _workflow_usage(self) -> dict[str, list[str]]:
        """工作流文件 → 引用它的模型 key 列表，用来发现"孤儿"文件。"""
        usage: dict[str, list[str]] = {}
        for entry in self.plugin.catalog.items():
            usage.setdefault(entry.workflow, []).append(entry.key)
        return usage

    def _diagnostics(self) -> list[dict[str, str]]:
        """上手自检：把"新手最容易卡住的地方"直接列出来。"""
        plugin = self.plugin
        cfg = plugin.config if isinstance(plugin.config, dict) else {}
        items: list[dict[str, str]] = []

        def add(level: str, message: str) -> None:
            items.append({"level": level, "message": message})

        comfy = cfg.get("comfyui") if isinstance(cfg.get("comfyui"), dict) else {}
        base_url = str((comfy or {}).get("base_url") or "").strip()
        if not base_url:
            add("error", "没有填写 ComfyUI 地址，生成会直接失败。本机填写 http://127.0.0.1:8188；AstrBot 在 Docker 里请填 http://host.docker.internal:8188")
        elif base_url.startswith("http://127.0.0.1") and Path("/AstrBot").exists():
            add("warn", "当前 AstrBot 跑在容器里，127.0.0.1 指向容器自己而不是宿主机；通常需要改成 http://host.docker.internal:8188")

        workflow_dir = plugin.pipeline.workflow_dir if plugin.pipeline else None
        if workflow_dir is not None and not workflow_dir.exists():
            add("error", f"工作流目录不存在：{workflow_dir}")
        files = set(self._workflow_files())
        if not files:
            add("error", "工作流目录里没有任何 .json，至少要放一个 ComfyUI 导出的 API 格式工作流")

        for entry in plugin.catalog.items():
            if entry.workflow not in files:
                add("error", f"模型「{entry.key}」指向的工作流 {entry.workflow} 不在目录里")
        for kind, label in (("selfie", "自拍"), ("reference", "参考图"), ("edit", "编辑")):
            section = cfg.get(kind) if isinstance(cfg.get(kind), dict) else {}
            workflow = str((section or {}).get("workflow") or "").strip()
            if workflow and workflow not in files:
                add("error", f"{label}档的工作流 {workflow} 不在目录里")

        if not plugin.catalog.enabled_items():
            add("error", "所有模型都被停用了，生成页会是空的")

        selfie = cfg.get("selfie") if isinstance(cfg.get("selfie"), dict) else {}
        if not str((selfie or {}).get("reference_image") or "").strip():
            add("warn", "自拍档没配人设参考图，出图只是通用角色、不带角色一致性（可留空，但建议配一张）")

        if plugin.pipeline is not None:
            out_dir = plugin.pipeline.output_dir
            try:
                out_dir.mkdir(parents=True, exist_ok=True)
                probe = out_dir / ".write_test"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink()
            except OSError as exc:
                add("error", f"出图目录不可写：{out_dir}（{exc}）")

        orphan = sorted(name for name in files if name not in self._workflow_usage())
        if orphan:
            add("info", "这些工作流没有被任何模型引用（留着也没关系）：" + "、".join(orphan))

        if not items:
            add("ok", "没发现明显问题，可以直接去 Studio 生成")
        return items

    def _workflow_files(self) -> list[str]:
        """递归列出工作流，返回相对路径（如 selfie/miao.json），目录即类型。"""
        workflow_dir = self.plugin.pipeline.workflow_dir if self.plugin.pipeline else self.plugin.root / "workflows"
        if not workflow_dir.exists():
            return []
        return sorted(
            p.relative_to(workflow_dir).as_posix()
            for p in workflow_dir.rglob("*.json")
            if p.is_file()
        )

    def _host_path(self, container_path: str) -> str:
        """把容器内路径映射成宿主路径（需要配置 paths.host_data_dir）。"""
        cfg = self.plugin.config if isinstance(self.plugin.config, dict) else {}
        paths = cfg.get("paths") if isinstance(cfg.get("paths"), dict) else {}
        host = str((paths or {}).get("host_data_dir") or "").strip()
        if not host:
            return ""
        prefix = "/AstrBot/data"
        if container_path.startswith(prefix):
            return host.rstrip("/\\") + container_path[len(prefix):].replace("/", "\\")
        return ""

    def _filter_config(self, patch: dict[str, Any]) -> dict[str, Any]:
        """只放行白名单字段，并按当前值类型做一次转换。"""
        cfg = self.plugin.config if isinstance(self.plugin.config, dict) else {}
        out: dict[str, Any] = {}
        for section, values in patch.items():
            allowed = CONFIG_WHITELIST.get(section)
            if not allowed or not isinstance(values, dict):
                continue
            current = cfg.get(section) if isinstance(cfg.get(section), dict) else {}
            clean: dict[str, Any] = {}
            for key, value in values.items():
                if key not in allowed:
                    continue
                base = current.get(key) if isinstance(current, dict) else None
                if isinstance(base, bool):
                    clean[key] = bool(value)
                elif isinstance(base, int) and not isinstance(base, bool):
                    try:
                        clean[key] = int(float(value))
                    except (TypeError, ValueError):
                        continue
                elif isinstance(base, float):
                    try:
                        clean[key] = float(value)
                    except (TypeError, ValueError):
                        continue
                else:
                    clean[key] = str(value)
            if clean:
                out[section] = clean
        return out

    # ------------------------------------------------------------------ 工具
    def _image_info(self, path: str) -> dict[str, Any]:
        target = Path(path)
        info: dict[str, Any] = {
            "path": str(target),
            "name": target.name,
            "url": f"/api/v1/plugins/extensions/{PLUGIN_NAME}/file?path={target.as_posix()}",
            "size": 0,
            "mtime": 0,
            "data_url": "",
        }
        try:
            stat = target.stat()
            info["size"] = stat.st_size
            info["mtime"] = int(stat.st_mtime)
            if stat.st_size <= 6 * 1024 * 1024:
                mime = mimetypes.guess_type(target.name)[0] or "image/png"
                info["data_url"] = f"data:{mime};base64,{base64.b64encode(target.read_bytes()).decode()}"
        except OSError:
            pass
        return info

"""插件 Web API：给 views/studio 页面提供状态、生成、历史、图片读取。

AstrBot 的插件视图通过 bridge 调用这些接口，路由前缀固定为 /<插件名>。
"""
from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any

from astrbot.api import logger

from .core.types import ImageRequest, normalize_kind

PLUGIN_NAME = "astrbot_plugin_tsukiyo_media"

try:  # AstrBot >= 4.16 提供 astrbot.api.web
    from astrbot.api.web import error_response, file_response, json_response, request

    WEB_API_AVAILABLE = True
except Exception:  # pragma: no cover - 老版本降级
    WEB_API_AVAILABLE = False
    error_response = file_response = json_response = None  # type: ignore[assignment]
    request = None  # type: ignore[assignment]


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
            ("/history", self.history, ["GET"], "最近生成记录"),
            ("/file", self.file, ["GET"], "读取生成产物"),
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
        req = ImageRequest(
            prompt=prompt,
            kind=normalize_kind(payload.get("kind") or "auto"),
            model_key=str(payload.get("model_key") or ""),
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
        data["images"] = [self._image_info(path) for path in result.paths]
        return json_response(data)

    async def history(self):
        plugin = self.plugin
        limit = request.query.get("limit", 12, type=int)
        items: list[dict[str, Any]] = []
        known: dict[str, dict[str, Any]] = {}
        if plugin.pipeline:
            for result in reversed(plugin.pipeline.history[-limit:]):
                for path in result.paths:
                    known[str(path)] = result.to_receipt()
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

    async def file(self):
        plugin = self.plugin
        raw = request.query.get("path", "", type=str) or ""
        if not raw:
            return error_response("缺少 path", status_code=400)
        root = plugin.pipeline.output_dir.resolve() if plugin.pipeline else None
        if root is None:
            return error_response("输出目录未初始化", status_code=503)
        try:
            target = Path(raw).expanduser().resolve()
        except OSError:
            return error_response("非法路径", status_code=400)
        if target != root and root not in target.parents:
            return error_response("只允许读取输出目录内的文件", status_code=403)
        if not target.is_file():
            return error_response("文件不存在", status_code=404)
        content_type = mimetypes.guess_type(target.name)[0] or "image/png"
        return file_response(target, filename=target.name, content_type=content_type)

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

"""月夜绘影（tsukiyo_media）· AstrBot 入口。

设计边界（刻意保持窄）：
- 只负责“怎么生成”：后端连接（ComfyUI / 在线 API）、工作流绑定、提示词拼装、产物落盘。
- 不负责“要不要生成”：人格、好感度、日程、主动消息一律不碰。
- 不 import 任何陪伴类插件；别的插件想用，只通过 api.TsukiyoMediaAPI。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import httpx

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image
from astrbot.api.star import Context, Star, StarTools, register

from . import __version__
from .api import TsukiyoMediaAPI
from .backends.comfyui.client import ComfyUIClient
from .core.catalog import ModelCatalog
from .core.errors import TsukiyoMediaError
from .core.pipeline import ImagePipeline, KindProfile, PipelineSettings
from .page_api import PageAPI
from .core.types import (
    KIND_EDIT,
    KIND_REFERENCE,
    KIND_SELFIE,
    KIND_TEXT2IMG,
    GenerationResult,
    ImageRequest,
    normalize_kind,
)

PLUGIN_NAME = "astrbot_plugin_tsukiyo_media"
DEFAULT_NEGATIVE = (
    "worst quality, low quality, normal quality, bad anatomy, extra fingers, "
    "watermark, text, signature, logo"
)
_GROUP_BLOCK_HINTS = ("nude", "naked", "topless", "裸", "脱光", "全裸")


@register(
    "tsukiyo_media",
    "Mio (tsukiyo-zero)",
    "低耦合生成插件：本地 ComfyUI / 在线 API，文生图·自拍·参考图·编辑，预留视频",
    "0.0.0",
)
class TsukiyoMediaPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config or {}
        self.data_dir = Path(StarTools.get_data_dir(PLUGIN_NAME))
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.root = Path(__file__).resolve().parent
        self._version = __version__
        self.reference_dir = self.data_dir / "references"
        self.reference_dir.mkdir(parents=True, exist_ok=True)

        self.catalog: ModelCatalog | None = None
        self.client: ComfyUIClient | None = None
        self.pipeline: ImagePipeline | None = None
        self.api: TsukiyoMediaAPI | None = None
        self._init_runtime()

        # 插件可视化视图的后端 API：只在启动时注册一次（/img reload 不重复注册）
        self._log_registered_commands()

        self.page_api = PageAPI(self)
        try:
            self.page_api.register(context)
        except Exception as exc:  # pragma: no cover - 老版本或权限问题不影响主功能
            logger.warning("[TsukiyoMedia] 插件页面注册失败：%s", exc)

    def _log_registered_commands(self) -> None:
        """启动自检：确认本插件的命令/别名真的注册上了（过滤器是 AND 关系，叠多个会失效）。"""
        try:
            from astrbot.core.star.star_handler import star_handlers_registry

            commands: list[str] = []
            for handler in star_handlers_registry:
                if not str(getattr(handler, "handler_full_name", "")).endswith("img_command"):
                    continue
                for item in getattr(handler, "event_filters", []) or ():
                    name = getattr(item, "command_name", "")
                    if not name:
                        continue
                    alias = sorted(getattr(item, "alias", set()) or ())
                    commands.append(name + ("(" + ", ".join(alias) + ")" if alias else ""))
            logger.info("[TsukiyoMedia] 命令已注册: %s", " / ".join(commands) or "(无)")
        except Exception as exc:  # pragma: no cover - 只影响日志
            logger.debug("[TsukiyoMedia] 命令自检跳过: %s", exc)

    # ------------------------------------------------------------------ 装配
    def _init_runtime(self) -> None:
        cfg = self.config if isinstance(self.config, dict) else {}
        comfy = cfg.get("comfyui") or {}
        paths = cfg.get("paths") or {}
        generation = cfg.get("generation") or {}

        workflow_dir = self._resolve_path(paths.get("workflow_dir") or "workflows")
        catalog_path = self._resolve_path(paths.get("catalog") or "models.json")
        output_dir = Path(paths.get("output_dir") or "").expanduser() if paths.get("output_dir") else self.data_dir / "output"
        if not output_dir.is_absolute():
            output_dir = (self.root / output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        self.catalog = ModelCatalog(catalog_path)
        self.client = ComfyUIClient(
            str(comfy.get("base_url") or "http://127.0.0.1:8188"),
            connect_timeout=float(comfy.get("connect_timeout_seconds") or 10),
            job_timeout=float(comfy.get("job_timeout_seconds") or 180),
            poll_interval=float(comfy.get("poll_interval_seconds") or 1.0),
        )

        settings = PipelineSettings(
            negative_prompt=str(generation.get("negative_prompt") or DEFAULT_NEGATIVE),
            prompt_mode=str(generation.get("prompt_mode") or "append"),
            strip_cjk=bool(generation.get("strip_non_english", False)),
            max_concurrent=int(generation.get("max_concurrent") or 1),
            filename_prefix=str(generation.get("filename_prefix") or "tsukiyo"),
            job_timeout=float(comfy.get("job_timeout_seconds") or 180),
            profiles=self._build_profiles(cfg),
        )
        self.pipeline = ImagePipeline(
            client=self.client,
            catalog=self.catalog,
            settings=settings,
            workflow_dir=workflow_dir,
            output_dir=output_dir,
            history_path=self.data_dir / "history.json",
        )
        self.api = TsukiyoMediaAPI(self.pipeline, self.catalog)
        logger.info(
            "[TsukiyoMedia] 就绪：comfy=%s models=%s workflows=%s",
            comfy.get("base_url") or "http://127.0.0.1:8188",
            len(self.catalog.keys()),
            workflow_dir,
        )

    def _build_profiles(self, cfg: dict[str, Any]) -> dict[str, KindProfile]:
        text2img = cfg.get("text2img") or {}
        selfie = cfg.get("selfie") or {}
        reference = cfg.get("reference") or {}
        edit = cfg.get("edit") or {}
        selfie_image = str(selfie.get("reference_image") or "").strip()
        if selfie_image:
            candidate = Path(selfie_image).expanduser()
            selfie_image = str(candidate if candidate.is_absolute() else (self.root / candidate).resolve())
        return {
            KIND_TEXT2IMG: KindProfile(fixed_prompt=str(text2img.get("fixed_prompt") or "")),
            KIND_SELFIE: KindProfile(
                workflow=str(selfie.get("workflow") or "selfie/default.json"),
                model_key=str(selfie.get("model") or ""),
                fixed_prompt=str(selfie.get("fixed_prompt") or ""),
                identity_prompt=str(selfie.get("identity_prompt") or ""),
                identity_image=selfie_image,
                ipadapter_weight=self._opt_float(selfie.get("ipadapter_weight")),
                width=int(selfie.get("width") or 0),
                height=int(selfie.get("height") or 0),
            ),
            KIND_REFERENCE: KindProfile(
                workflow=str(reference.get("workflow") or "reference/default.json"),
                fixed_prompt=str(reference.get("fixed_prompt") or ""),
                ipadapter_weight=self._opt_float(reference.get("ipadapter_weight")),
                width=int(reference.get("width") or 0),
                height=int(reference.get("height") or 0),
            ),
            KIND_EDIT: KindProfile(
                workflow=str(edit.get("workflow") or "edit/default.json"),
                fixed_prompt=str(edit.get("fixed_prompt") or ""),
                denoise=self._opt_float(edit.get("denoise")),
                width=int(edit.get("width") or 0),
                height=int(edit.get("height") or 0),
            ),
        }

    def _resolve_path(self, value: str) -> Path:
        candidate = Path(str(value)).expanduser()
        return candidate if candidate.is_absolute() else (self.root / candidate).resolve()

    @staticmethod
    def _opt_float(value: Any) -> float | None:
        try:
            return None if value in (None, "") else float(value)
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------ 命令
    @filter.command("img", alias={"画图", "draw"})
    async def img_command(self, event: AstrMessageEvent):
        """本地 ComfyUI 生图：/img [selfie|edit|ref] [model=key] [size=832x1216] [seed=1] 描述"""
        raw = str(getattr(event, "message_str", "") or "")
        # /draw 是旧插件的命令，这里做兼容：/draw <模型key> <描述>
        invoked_draw = bool(re.match(r"^\s*/?draw\b", raw, flags=re.I))
        body = re.sub(r"^\s*/?(?:img|画图|draw)\b", "", raw, flags=re.I).strip()
        head = body.split()[0].lower() if body.split() else ""

        if head in {"", "help", "帮助", "说明", "?", "？"}:
            yield event.plain_result(self._help_text())
            return
        if head in {"models", "模型", "列表", "list"}:
            yield event.plain_result(self._models_text())
            return
        if head in {"status", "状态"}:
            yield event.plain_result(await self._status_text())
            return
        if head in {"last", "上一张"}:
            yield event.plain_result(self._last_text())
            return
        if head in {"reload", "重载"}:
            if not event.is_admin():
                yield event.plain_result("只有管理员能重载配置。")
                return
            try:
                self._init_runtime()
                yield event.plain_result("已重载：模型目录 / 工作流 / ComfyUI 连接配置。")
            except TsukiyoMediaError as exc:
                yield event.plain_result(f"重载失败：{exc}")
            return

        kind_hint = ""
        if head in {"selfie", "自拍"}:
            kind_hint = KIND_SELFIE
            body = body[len(body.split()[0]):].strip()
        elif head in {"edit", "改图", "编辑"}:
            kind_hint = KIND_EDIT
            body = body[len(body.split()[0]):].strip()
        elif head in {"ref", "reference", "参考", "图生图"}:
            kind_hint = KIND_REFERENCE
            body = body[len(body.split()[0]):].strip()

        prompt, opts = self._parse_options(body)
        if invoked_draw and not opts.get("model"):
            # 旧插件的写法：/draw miao 海边 —— 首词若是模型 key/别名，当成选模
            tokens = prompt.split()
            if len(tokens) >= 2 and self.catalog is not None:
                try:
                    opts["model"] = self.catalog.get(tokens[0]).key
                    prompt = prompt[len(tokens[0]):].strip()
                except Exception:  # noqa: BLE001 - 不是模型名就当普通描述
                    pass
        if not prompt:
            yield event.plain_result("请描述画面内容，例如：/img selfie 在海边散步，黄昏逆光")
            return

        blocked = self._blocked_reason(event, prompt)
        if blocked:
            yield event.plain_result(blocked)
            return

        references = await self._collect_references(event)
        if kind_hint in (KIND_EDIT, KIND_REFERENCE) and not references:
            yield event.plain_result("这个用法需要带一张图（或引用一张图）。")
            return

        request = ImageRequest(
            prompt=prompt,
            kind=kind_hint or normalize_kind(opts.get("kind", "")),
            model_key=opts.get("model", ""),
            references=references,
            width=_dim(opts.get("size"), 0),
            height=_dim(opts.get("size"), 1),
            seed=_int_or(opts.get("seed"), -1),
            source="command",
        )
        yield event.plain_result("🖌 正在画，稍等一下…")
        result = await self._generate(request)
        async for chunk in self._deliver(event, result, opts.get("caption", "")):
            yield chunk

    # ------------------------------------------------------------------ LLM 工具
    @filter.llm_tool(name="tsukiyo_image_generate")
    async def tsukiyo_image_generate(
        self,
        event: AstrMessageEvent,
        prompt: str,
        kind: str = "auto",
        model_key: str = "",
        reference_image_path: str = "",
        caption: str = "",
        send: bool = True,
    ) -> str:
        """用本地 ComfyUI 生成图片（文生图 / 自拍 / 编辑 / 参考图重绘）。

        Args:
            prompt(string): 英文逗号分隔的 danbooru 风格 tag；不要写句子、不要写 "Positive prompt:" 之类标签。中文会被 CLIP 忽略。
            kind(string): auto/selfie/edit/reference。角色本人出镜用 selfie；对用户给的图做修改（改成/换成/去掉）用 edit；照用户给的图画新画面用 reference；不含角色的普通画面用 text2img；不确定就填 auto。
            model_key(string): 英文模型 key（可用值见插件模型列表）；文生图留空则按描述自动选，自拍/参考图/编辑留空则用该档配置的默认模型。仅换底模与作者词，不改变链路结构。
            reference_image_path(string): 可选，本地图片绝对路径；通常留空，插件会自动取本轮消息或引用里的图。
            caption(string): 随图发送的一句话；留空则只发图。
            send(boolean): 是否直接把图发到当前会话，默认 true。
        """
        if self._blocked_reason(event, prompt):
            return json.dumps(
                {"ok": False, "error": self._blocked_reason(event, prompt)}, ensure_ascii=False
            )
        references = await self._collect_references(event)
        if reference_image_path:
            references.insert(0, reference_image_path)
        request = ImageRequest(
            prompt=str(prompt or ""),
            kind=normalize_kind(kind),
            model_key=str(model_key or ""),
            references=references,
            caption=str(caption or ""),
            source="tool",
        )
        result = await self._generate(request)
        delivered = False
        if result.ok and send:
            async for _chunk in self._deliver(event, result, caption, quiet=True):
                pass
            delivered = True
        result.sent = delivered
        return json.dumps(result.to_receipt(), ensure_ascii=False)

    # ------------------------------------------------------------------ 生成
    async def _generate(self, request: ImageRequest) -> GenerationResult:
        if self.pipeline is None:
            raise TsukiyoMediaError("插件尚未初始化完成")
        try:
            result = await self.pipeline.generate(request)
        except TsukiyoMediaError as exc:
            result = GenerationResult(ok=False, error=str(exc))
        except Exception as exc:  # pragma: no cover
            result = GenerationResult(ok=False, error=f"{type(exc).__name__}: {exc}")
        if not result.ok:
            logger.warning("[TsukiyoMedia] 出图失败：%s", result.error)
        else:
            logger.info(
                "[TsukiyoMedia] 出图成功 kind=%s model=%s ms=%s files=%s",
                result.kind,
                result.model_key,
                result.elapsed_ms,
                len(result.paths),
            )
        return result

    async def _deliver(
        self,
        event: AstrMessageEvent,
        result: GenerationResult,
        caption: str = "",
        *,
        quiet: bool = False,
    ):
        if not result.ok:
            if not quiet:
                yield event.plain_result(f"没画出来：{result.error[:200]}")
            return
        text = str(caption or "").strip()
        if text:
            yield event.plain_result(text)
        for path in result.paths:
            yield event.image_result(path)

    async def _status_text(self) -> str:
        if self.client is None:
            return "插件未初始化。"
        try:
            stats = await self.client.system_stats()
            queue = await self.client.queue_state()
        except TsukiyoMediaError as exc:
            return f"ComfyUI 连不上：{exc}"
        device = (stats.get("devices") or [{}])[0]
        vram_total = float(device.get("vram_total") or 0) / (1024**3)
        vram_free = float(device.get("vram_free") or 0) / (1024**3)
        running = len(queue.get("queue_running") or ())
        pending = len(queue.get("queue_pending") or ())
        return (
            f"ComfyUI {stats.get('system', {}).get('comfyui_version', '?')}\n"
            f"显存 {vram_free:.1f}/{vram_total:.1f} GB\n"
            f"队列 运行 {running} / 等待 {pending}\n"
            f"模型 {len(self.catalog.keys() if self.catalog else [])} 个，默认 {self.catalog.default_key if self.catalog else '-'}"
        )

    def _last_text(self) -> str:
        last = self.api.last_result if self.api else None
        if last is None:
            return "还没有出过图。"
        payload = last.to_receipt()
        payload["output"] = last.paths[-1] if last.paths else ""
        return json.dumps(payload, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------ 工具方法
    def _help_text(self) -> str:
        return (
            "本地 ComfyUI 生图（/img、/画图、/draw 三种写法等价）\n"
            "/img models — 列出模型\n"
            "/img status — ComfyUI 状态\n"
            "/img last — 上一张的参数\n"
            "/img <描述> — 自动判断文生图/自拍\n"
            "/img selfie <描述> — 自拍（用固定人设参考图）\n"
            "/img edit <描述> — 改图（需要带图）\n"
            "/img ref <描述> — 参考图画新图（需要带图）\n"
            "可选参数：model=<key> size=832x1216 seed=123 kind=selfie\n"
            "例：/img model=miao 海边散步，黄昏逆光，全身\n"
            "旧写法也支持：/draw miao 海边散步"
        )

    def _models_text(self) -> str:
        if not self.catalog:
            return "模型目录未加载。"
        return self.catalog.gallery()

    def _blocked_reason(self, event: AstrMessageEvent, prompt: str) -> str:
        delivery = self.config.get("delivery") or {}
        is_private = bool(getattr(event, "is_private_chat", lambda: True)())
        if is_private and not bool(delivery.get("allow_private", True)):
            return "私聊生图已关闭。"
        if not is_private and not bool(delivery.get("allow_group", True)):
            return "群聊生图已关闭。"
        if not is_private and bool(delivery.get("group_block_nsfw", False)):
            lowered = str(prompt or "").casefold()
            if any(hint.casefold() in lowered for hint in _GROUP_BLOCK_HINTS):
                return "群里不画这类图。"
        return ""

    @staticmethod
    def _parse_options(body: str) -> tuple[str, dict[str, str]]:
        opts: dict[str, str] = {}
        kept: list[str] = []
        for token in body.split():
            if "=" in token:
                key, _, value = token.partition("=")
                if key.lower() in {"model", "kind", "size", "seed", "caption"}:
                    opts[key.lower()] = value
                    continue
            kept.append(token)
        return " ".join(kept).strip(), opts

    async def _collect_references(self, event: AstrMessageEvent) -> list[str]:
        message = getattr(getattr(event, "message_obj", None), "message", None) or []
        paths: list[str] = []
        for component in message:
            if not isinstance(component, Image):
                continue
            path = await self._materialize(component)
            if path:
                paths.append(path)
        return paths

    async def _materialize(self, component: Image) -> str:
        for attr in ("path", "file"):
            value = getattr(component, attr, None)
            if isinstance(value, str) and value and Path(value).exists():
                return value
        url = getattr(component, "url", None) or getattr(component, "file", None)
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            target = self.reference_dir / f"incoming_{int(time.time() * 1000)}.png"
            try:
                async with httpx.AsyncClient(timeout=30.0) as http:
                    resp = await http.get(url)
                    resp.raise_for_status()
                target.write_bytes(resp.content)
                return str(target)
            except Exception as exc:  # pragma: no cover
                logger.warning("[TsukiyoMedia] 下载参考图失败：%s", exc)
        return ""

    async def terminate(self) -> None:
        if self.client is not None:
            await self.client.close()

    # ------------------------------------------------------------------ 配置热更新
    async def apply_patch(self, patch: dict[str, Any]) -> None:
        """深合并配置 → 落盘 → 重建运行时（不重启 AstrBot）。

        设置页保存走这里；失败时抛异常，让前端看到原因。
        """
        if not isinstance(patch, dict) or not patch:
            return
        old_client = self.client
        _deep_update(self.config, patch)

        saver = getattr(self.config, "save_config_async", None)
        if callable(saver):
            await saver()
        else:
            sync_saver = getattr(self.config, "save_config", None)
            if callable(sync_saver):
                sync_saver()

        self._init_runtime()
        if old_client is not None and old_client is not self.client:
            try:
                await old_client.close()
            except Exception:  # pragma: no cover
                pass
        logger.info("[TsukiyoMedia] 配置已更新并重建运行时")


def _deep_update(target: dict, patch: dict) -> None:
    """递归合并：只覆盖 patch 里出现的键，其余保持原值。"""
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = value


def _dim(size: str | None, index: int) -> int:
    text = str(size or "").lower().replace("*", "x")
    if "x" not in text:
        return 0
    parts = [p for p in text.split("x") if p.isdigit()]
    return int(parts[index]) if len(parts) > index else 0


def _int_or(value: Any, default: int) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default

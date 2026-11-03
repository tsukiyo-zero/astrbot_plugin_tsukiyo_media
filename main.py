"""月夜绘影（tsukiyo_media）· AstrBot 入口。

设计边界（刻意保持窄）：
- 只负责“怎么生成”：后端连接（ComfyUI / 在线 API）、工作流绑定、提示词拼装、产物落盘。
- 不负责“要不要生成”：人格、好感度、日程、主动消息一律不碰。
- 不 import 任何陪伴类插件；别的插件想用，只通过 api.TsukiyoMediaAPI。
"""
from __future__ import annotations

import json
from dataclasses import replace
import re
import time
from pathlib import Path
from typing import Any, Optional

import httpx

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image, Plain
from astrbot.api.star import Context, Star, StarTools, register
from astrbot.core.message.message_event_result import MessageChain

from . import __version__
from .api import TsukiyoMediaAPI
from .backends.comfyui.client import ComfyUIClient
from .core.catalog import ModelCatalog
from .core.errors import TsukiyoMediaError
from .core.pipeline import ImagePipeline, KindProfile, PipelineSettings
from .core.translate import PromptTranslator, has_cjk, maybe_translate
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
        #: 每个会话上一条生成请求，用于“重画 / 换个模型”
        self._last_jobs: dict[str, ImageRequest] = {}
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

        # 中文描述 → 英文 tag（CLIP 读不懂中文，不转等于没描述）
        self.translate_enabled = bool(generation.get("translate_cjk", True))
        self.translate_timeout = float(generation.get("translate_timeout_seconds") or 20)
        self.translator = PromptTranslator(
            get_provider=self._current_provider,
            log=lambda msg: logger.info("[TsukiyoMedia] %s", msg),
        )
        logger.info(
            "[TsukiyoMedia] 就绪：comfy=%s models=%s workflows=%s 中文转 tag=%s",
            comfy.get("base_url") or "http://127.0.0.1:8188",
            len(self.catalog.keys()),
            workflow_dir,
            "开" if self.translate_enabled else "关",
        )

    def _current_provider(self) -> Any:
        """拿 AstrBot 当前对话用的 LLM Provider（用于中文转 tag）。"""
        try:
            return self.context.get_using_provider()
        except Exception:  # pragma: no cover - 环境相关
            return None

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
                workflow=str(selfie.get("workflow") or "selfie/miao.json"),
                fixed_prompt=str(selfie.get("fixed_prompt") or ""),
                negative_prompt=str(selfie.get("fixed_negative") or ""),
                identity_prompt=str(selfie.get("identity_prompt") or ""),
                identity_image=selfie_image,
                ipadapter_weight=self._opt_float(selfie.get("ipadapter_weight")),
                width=int(selfie.get("width") or 0),
                height=int(selfie.get("height") or 0),
            ),
            KIND_REFERENCE: KindProfile(
                workflow=str(reference.get("workflow") or "reference/obsession.json"),
                fixed_prompt=str(reference.get("fixed_prompt") or ""),
                negative_prompt=str(reference.get("fixed_negative") or ""),
                ipadapter_weight=self._opt_float(reference.get("ipadapter_weight")),
                width=int(reference.get("width") or 0),
                height=int(reference.get("height") or 0),
            ),
            KIND_EDIT: KindProfile(
                workflow=str(edit.get("workflow") or "edit/illustrious.json"),
                fixed_prompt=str(edit.get("fixed_prompt") or ""),
                negative_prompt=str(edit.get("fixed_negative") or ""),
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
        """本地 ComfyUI 生图：/img [model=key] [size=832x1216] [seed=1] 描述"""
        raw = str(getattr(event, "message_str", "") or "")
        # /draw 是旧插件的命令，这里做兼容：/draw <模型key> <描述>
        invoked_draw = bool(re.match(r"^\s*/?draw\b", raw, flags=re.I))
        body = re.sub(r"^\s*/?(?:img|画图|draw)\b", "", raw, flags=re.I).strip()
        head = body.split()[0].lower() if body.split() else ""

        if head in {"", "help", "帮助", "说明", "?", "？", "models", "模型", "列表", "list"}:
            yield event.plain_result(self._help_text())
            return

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
            yield event.plain_result("请描述画面内容，例如：/img 在海边散步，黄昏逆光")
            return

        blocked = self._blocked_reason(event, prompt)
        if blocked:
            yield event.plain_result(blocked)
            return

        references = await self._collect_references(event)

        request = ImageRequest(
            prompt=prompt,
            kind=normalize_kind(opts.get("kind", "")),
            model_key=opts.get("model", ""),
            references=references,
            width=_dim(opts.get("size"), 0),
            height=_dim(opts.get("size"), 1),
            seed=_int_or(opts.get("seed"), -1),
            source="command",
            # hint = 用户原话：按名选模（/img 用cat …）和链路纠正都靠它
            hint=raw,
        )
        # 不再发固定的“正在画”占位文案：命令路径直接出图，想让她说话就走自然语言（LLM 工具）
        result = await self._generate(request)
        if result.ok:
            self._remember_job(event, request)
        async for chunk in self._deliver(event, result, opts.get("caption", "")):
            yield chunk
        if result.ok and self.catalog is not None:
            yield event.plain_result(self._menu_text())

    def _menu_text(self) -> str:
        """出图后的文字菜单（QQ 官方机器人不支持按钮，只能给可回复的词）。"""
        names = [entry.label for entry in self.catalog.items()][:6]
        return "想换风格就回：换" + " / 换".join(names) + "；想再抽一张就回：重画"

    # ------------------------------------------------------------------ 重画
    def _remember_job(self, event: AstrMessageEvent, request: ImageRequest) -> None:
        umo = str(getattr(event, "unified_msg_origin", "") or "")
        if umo:
            self._last_jobs[umo] = request
            if len(self._last_jobs) > 200:  # 简易上限，避免无限增长
                self._last_jobs.pop(next(iter(self._last_jobs)))

    def _model_from_text(self, text: str) -> str:
        """从“换柔光 / 用像素”这类短句里找出模型 key；找不到返回空。"""
        if self.catalog is None:
            return ""
        body = re.sub(r"^(换成|换|用|改成)", "", text).strip()
        if not body:
            return ""
        try:
            return self.catalog.get(body).key
        except Exception:  # noqa: BLE001 - 不是模型名就当没说
            return ""

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def regenerate_handler(self, event: AstrMessageEvent) -> None:
        """「重画」「换柔光」这类短句：拿上一条请求重跑一次。"""
        text = str(getattr(event, "message_str", "") or "").strip()
        if not text or len(text) > 8 or text.startswith(("/", "／")):
            return
        umo = str(getattr(event, "unified_msg_origin", "") or "")
        job = self._last_jobs.get(umo)
        if job is None:
            return

        if text in {"重画", "再来一张", "再画一张", "再抽一张"}:
            model_key = job.model_key
        else:
            model_key = self._model_from_text(text)
            if not model_key:
                return

        request = replace(job, seed=-1, model_key=model_key, hint=text)
        try:
            result = await self._generate(request)
            await self._send_result(event, result, "")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[TsukiyoMedia] 重画失败：%s", exc)
            return
        event.stop_event()


    # ------------------------------------------------------------------ LLM 工具
    @filter.llm_tool(name="tsukiyo_image_generate")
    async def tsukiyo_image_generate(
        self,
        event: AstrMessageEvent,
        prompt: str,
        kind: Optional[str] = None,
        model_key: Optional[str] = None,
        caption: Optional[str] = None,
    ) -> str:
        """生成一张图并发到当前会话。用户说“来张自拍”“发张照片”“画一张…”“把这张改成…”时必须调用这个工具，不要只用文字回复。

        Args:
            prompt(string): 这张图的内容，英文逗号分隔的 danbooru 风格 tag（如 sitting, window, evening, white hoodie）。只写场景、动作、服装、光线、表情；**不要写她本人的外貌**（发色、瞳色、耳朵、尾巴、发饰——插件会自动追加，写错反而破坏一致性）。不要写句子、不要写 "Positive prompt:" 之类标签；中文会被忽略。
            kind(string, optional): selfie = 你本人出镜（用户想看你的样子、要自拍）；text2img = 画别的画面；edit = 修改用户发来的图（改成/换成/去掉）；reference = 照用户发来的图重画；不确定就省略。
            model_key(string, optional): 模型 key，通常省略。
            caption(string, optional): 随图发送的一句话；省略则只发图。
        """
        if self._blocked_reason(event, prompt):
            return json.dumps(
                {"ok": False, "error": self._blocked_reason(event, prompt)}, ensure_ascii=False
            )
        references = await self._collect_references(event)
        request = ImageRequest(
            prompt=str(prompt or ""),
            kind=normalize_kind(kind or "auto"),
            model_key=str(model_key or ""),
            references=references,
            caption=str(caption or ""),
            source="tool",
            hint=str(getattr(event, "message_str", "") or ""),
        )
        result = await self._generate(request)
        if result.ok:
            self._remember_job(event, request)
        result.sent = await self._send_result(event, result, str(caption or ""))
        return json.dumps(result.to_receipt(), ensure_ascii=False)

    # ------------------------------------------------------------------ 生成
    async def _generate(self, request: ImageRequest) -> GenerationResult:
        if self.pipeline is None:
            raise TsukiyoMediaError("插件尚未初始化完成")
        request = await self._translate_request(request)
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

    async def _translate_request(self, request: ImageRequest) -> ImageRequest:
        """提示词含中文时先转成英文 tag；转不了就保持原样（不阻塞出图）。"""
        prompt = str(getattr(request, "prompt", "") or "")
        if not has_cjk(prompt):
            return request
        try:
            tags, ok = await maybe_translate(
                getattr(self, "translator", None),
                prompt,
                enabled=bool(getattr(self, "translate_enabled", True)),
                timeout=float(getattr(self, "translate_timeout", 20.0)),
            )
        except Exception as exc:  # pragma: no cover - 翻译失败不能影响出图
            logger.warning("[TsukiyoMedia] 中文转 tag 出错：%s", exc)
            return request
        if not ok or not tags or tags == prompt:
            logger.info("[TsukiyoMedia] 中文转 tag 未生效，按原文出图")
            return request
        logger.info("[TsukiyoMedia] 中文转 tag：%s -> %s", prompt[:40], tags[:80])
        try:
            return replace(request, prompt=tags)
        except Exception:  # pragma: no cover
            request.prompt = tags
            return request

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

    async def _send_result(
        self, event: AstrMessageEvent, result: GenerationResult, caption: str = ""
    ) -> bool:
        """主动发送（工具调用 / 兜底路径用）。

        命令处理函数可以 yield 结果交给框架发送；工具调用里 yield 出来的东西
        没人消费，必须自己调用 event.send()。
        """
        chain: list = []
        if not result.ok:
            chain.append(Plain(f"没画出来：{result.error[:200]}"))
        else:
            text = str(caption or "").strip()
            if text:
                chain.append(Plain(text))
            for path in result.paths:
                chain.append(Image.fromFileSystem(path))
        if not chain:
            return False
        await event.send(MessageChain(chain))
        return bool(result.ok)

    # ------------------------------------------------------------------ 工具方法
    def _help_text(self) -> str:
        """帮助 = 模型图鉴：怎么选模型、怎么用，都在这张表里。"""
        return self._models_text()

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


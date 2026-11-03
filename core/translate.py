"""中文画面描述 → Danbooru 风格英文 tag（借助 AstrBot 的 LLM Provider）。

为什么要这层：SDXL/Illustrious 的 CLIP 读不懂中文，`/draw 教室里粉发少女` 这类输入
会原样进 CLIP，等于没描述——出图内容基本靠运气。这里在进 pipeline 前把中文转成 tag。
"""
from __future__ import annotations

import re
from typing import Any, Awaitable, Callable

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_ASCII_TAG_RE = re.compile(r"[A-Za-z0-9_\-:'() ]+")

SYSTEM_PROMPT = (
    "你是 Stable Diffusion / Danbooru 提示词翻译器。把用户的中文画面描述转成英文 tag，"
    "要求：1) 只输出用英文逗号分隔的 tag 本身，不要任何解释、不要换行、不要引号；"
    "2) 保持画面要素（人物数量、动作、服装、场景、光照、镜头）完整；"
    "3) 人物用 1girl / 1boy 这类 tag 开头；"
    "4) 不要添加用户没说的服装或角色特征。"
)


def has_cjk(text: str) -> bool:
    return bool(CJK_RE.search(str(text or "")))


def clean_tags(text: str, *, max_len: int = 400) -> str:
    """把 LLM 输出洗成干净的 tag 串；含中文或空则返回空串（调用方回退原文）。"""
    raw = str(text or "").strip()
    if not raw:
        return ""
    raw = raw.split("\n")[0]
    raw = raw.strip().strip('"').strip("'").strip("`")
    if "：" in raw or ":" in raw:
        # 模型偶尔会写“翻译：xxx”，取冒号后面那段
        head, _, tail = raw.partition(":" if ":" in raw else "：")
        if has_cjk(head) and tail.strip():
            raw = tail
    raw = raw.replace("，", ",").replace("、", ",")
    if has_cjk(raw):
        return ""
    pieces = [p.strip() for p in raw.split(",")]
    kept = [p for p in pieces if p and _ASCII_TAG_RE.fullmatch(p)]
    out = ", ".join(kept)
    return out[:max_len]


class PromptTranslator:
    """带缓存的中文→tag 翻译器；provider 拿不到就静默回退。"""

    def __init__(
        self,
        get_provider: Callable[[], Any] | None = None,
        log: Callable[[str], None] | None = None,
        max_cache: int = 256,
    ) -> None:
        self._get_provider = get_provider
        self._log = log or (lambda _m: None)
        self._cache: dict[str, str] = {}
        self._max_cache = max(8, int(max_cache))

    def cached(self, text: str) -> str:
        return self._cache.get(str(text or "").strip(), "")

    async def to_tags(self, text: str, *, timeout: float = 20.0) -> str:
        """返回英文 tag；失败或不可用返回空串。"""
        src = str(text or "").strip()
        if not src or not has_cjk(src):
            return src if not has_cjk(src) else ""
        hit = self._cache.get(src)
        if hit:
            return hit
        provider = self._call_provider()
        if provider is None:
            self._log("没有可用的 LLM Provider，中文描述无法转 tag")
            return ""

        import asyncio

        async def _call() -> str:
            resp = await provider.text_chat(
                prompt=src,
                system_prompt=SYSTEM_PROMPT,
                contexts=[],
            )
            return getattr(resp, "completion_text", "") or ""

        try:
            raw = await asyncio.wait_for(_call(), timeout=timeout)
        except Exception as exc:  # 超时 / 网络 / 模型报错都回退
            self._log(f"中文转 tag 失败：{type(exc).__name__}: {exc}")
            return ""
        tags = clean_tags(raw)
        if not tags:
            self._log(f"翻译结果不可用，回退原文：{raw[:80]}")
            return ""
        if len(self._cache) >= self._max_cache:
            self._cache.pop(next(iter(self._cache)))
        self._cache[src] = tags
        return tags

    def _call_provider(self) -> Any:
        if self._get_provider is None:
            return None
        try:
            provider = self._get_provider()
        except Exception as exc:  # pragma: no cover - 环境相关
            self._log(f"取 Provider 失败：{exc}")
            return None
        return provider


async def maybe_translate(
    translator: PromptTranslator | None,
    prompt: str,
    *,
    enabled: bool = True,
    timeout: float = 20.0,
) -> tuple[str, bool]:
    """需要时翻译；返回 (最终提示词, 是否翻译成功)。"""
    if not enabled or translator is None or not has_cjk(prompt):
        return prompt, False
    tags = await translator.to_tags(prompt, timeout=timeout)
    if not tags:
        return prompt, False
    return tags, True

"""模型目录：模型 key → 工作流 + 作者参数。

目录是一份 JSON（默认 models.json），支持热重载，不改代码就能加模型。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ConfigError, RoutingError


@dataclass(frozen=True)
class ModelEntry:
    key: str
    label: str
    workflow: str
    author_params: dict[str, Any] = field(default_factory=dict)
    aliases: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    allow_override: bool = False

    def matches(self, text: str) -> bool:
        needle = str(text or "").strip().casefold()
        if not needle:
            return False
        candidates = {self.key.casefold(), self.label.casefold(), *(a.casefold() for a in self.aliases)}
        return needle in candidates


class ModelCatalog:
    """加载并查询模型目录。文件 mtime 变化时自动重载。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._models: dict[str, ModelEntry] = {}
        self._default = ""
        self._mtime: float = -1.0
        self.load()

    # ---------- 加载 ----------
    def load(self) -> None:
        if not self.path.exists():
            raise ConfigError(f"模型目录不存在：{self.path}")
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"模型目录不是合法 JSON：{exc}") from exc

        models: dict[str, ModelEntry] = {}
        for key, item in (raw.get("models") or {}).items():
            if not isinstance(item, dict):
                raise ConfigError(f"模型 {key} 的定义不是对象")
            workflow = str(item.get("workflow") or "").strip()
            if not workflow:
                raise ConfigError(f"模型 {key} 缺少 workflow")
            models[key] = ModelEntry(
                key=key,
                label=str(item.get("label") or key),
                workflow=workflow,
                author_params=dict(item.get("author_params") or {}),
                aliases=tuple(str(a) for a in (item.get("aliases") or ())),
                tags=tuple(str(t) for t in (item.get("tags") or ())),
                allow_override=bool(item.get("allow_override", False)),
            )
        if not models:
            raise ConfigError("模型目录为空")

        default = str(raw.get("default") or "").strip()
        if default and default not in models:
            raise ConfigError(f"默认模型 {default} 不在目录里")

        self._models = models
        self._default = default or next(iter(models))
        self._mtime = self.path.stat().st_mtime

    def maybe_reload(self) -> bool:
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return False
        if mtime != self._mtime:
            self.load()
            return True
        return False

    # ---------- 查询 ----------
    @property
    def default_key(self) -> str:
        return self._default

    def keys(self) -> list[str]:
        return list(self._models)

    def items(self) -> list[ModelEntry]:
        return list(self._models.values())

    def get(self, key_or_alias: str) -> ModelEntry:
        text = str(key_or_alias or "").strip()
        if not text:
            return self._models[self._default]
        if text in self._models:
            return self._models[text]
        for entry in self._models.values():
            if entry.matches(text):
                return entry
        raise RoutingError(f"未知绘图模型：{text}（可用：{', '.join(self.keys())}）")

    def find(self, text: str) -> ModelEntry | None:
        try:
            return self.get(text)
        except RoutingError:
            return None

    def describe(self) -> str:
        lines = []
        for entry in self._models.values():
            alias = f" / {', '.join(entry.aliases)}" if entry.aliases else ""
            tag = f"［{', '.join(entry.tags)}］" if entry.tags else ""
            star = "*" if entry.key == self._default else " "
            lines.append(f"{star} {entry.key}{alias} — {entry.label}{tag}")
        return "\n".join(lines)

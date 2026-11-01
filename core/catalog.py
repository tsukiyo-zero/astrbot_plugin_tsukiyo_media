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
    enabled: bool = True
    group: str = ""
    desc: str = ""

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
                enabled=bool(item.get("enabled", True)),
                group=str(item.get("group") or ""),
                desc=str(item.get("desc") or ""),
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

    def enabled_items(self) -> list[ModelEntry]:
        return [entry for entry in self._models.values() if entry.enabled]

    def enabled_keys(self) -> list[str]:
        return [entry.key for entry in self._models.values() if entry.enabled]

    def get(self, key_or_alias: str, *, allow_disabled: bool = False) -> ModelEntry:
        text = str(key_or_alias or "").strip()
        if not text:
            entry = self._models[self._default]
            return entry if (entry.enabled or allow_disabled) else self._first_enabled()
        if text in self._models:
            entry = self._models[text]
        else:
            entry = next((item for item in self._models.values() if item.matches(text)), None)
            if entry is None:
                raise RoutingError(f"未知绘图模型：{text}（可用：{', '.join(self.enabled_keys())}）")
        if not entry.enabled and not allow_disabled:
            raise RoutingError(f"模型已停用：{entry.key}（去设置页启用）")
        return entry

    def _first_enabled(self) -> ModelEntry:
        for entry in self._models.values():
            if entry.enabled:
                return entry
        raise RoutingError("所有模型都被停用了，请到设置页启用至少一个")

    def find(self, text: str) -> ModelEntry | None:
        try:
            return self.get(text)
        except RoutingError:
            return None

    def gallery(self) -> str:
        """聊天里展示的"模型图鉴"：按分组排版，一眼能选。"""
        groups: dict[str, list[ModelEntry]] = {}
        for entry in self._models.values():
            group = entry.group or (
                "real" if any(tag in ("写实", "人像", "摄影") for tag in entry.tags) else "anime"
            )
            groups.setdefault(group, []).append(entry)

        titles = {"anime": "🎀 动漫系", "real": "📷 写实系", "other": "📦 其他"}
        order = ["anime", "real", "other"]

        lines = ["✨ 月夜绘影 | 模型图鉴 ✨", ""]
        default = self._models.get(self._default)
        if default is not None:
            style = self._style_of(default)
            style_tags = [tag for tag in default.tags if tag != style]
            applies = "、".join(style_tags[:2]) or "通用"
            lines.append(f"⭐ [默认] {default.key}")
            lines.append(f"├ 风格：{style} | 适用：{applies}")
            lines.append("")

        for group in order + [g for g in groups if g not in order]:
            entries = groups.get(group) or []
            if not entries:
                continue
            lines.append(titles.get(group, group))
            for index, entry in enumerate(entries):
                branch = "└" if index == len(entries) - 1 else "├"
                label = self._style_of(entry)
                note = entry.desc or "、".join(entry.tags)
                off = "（已停用）" if not entry.enabled else ""
                lines.append(f"{branch} {label} ({entry.key}) ─ {note}{off}")
            lines.append("")

        lines.append("💬 怎么用？")
        lines.append("直接发：/draw " + self._example_alias() + " 海边散步")
        lines.append("指定参数：/img model=" + self._example_key() + " 一只猫")
        alias_samples = [a for entry in self._models.values() for a in entry.aliases if a and not a.isascii()]
        if alias_samples:
            lines.append("（模型名支持中文别名，如 " + "、".join(dict.fromkeys(alias_samples[:3])) + "）")
        return "\n".join(lines)

    @staticmethod
    def _style_of(entry: ModelEntry) -> str:
        """label 里通常写成 "obsession 华丽"，展示时只留中文风格名。"""
        label = entry.label.strip()
        if label.casefold().startswith(entry.key.casefold()):
            label = label[len(entry.key):].strip(" -·_")
        return label or entry.key

    def _example_alias(self) -> str:
        """示例优先用"柔光"这类好记的中文别名，其次非默认模型的中文别名。"""
        preferred = self._models.get("miao")
        if preferred is not None:
            for alias in preferred.aliases:
                if alias and not alias.isascii():
                    return alias
        for entry in self._models.values():
            if entry.key == self._default:
                continue
            for alias in entry.aliases:
                if alias and not alias.isascii():
                    return alias
        return self._default or "miao"

    def _example_key(self) -> str:
        """示例 key 用非默认模型，避免看起来"只能用默认的"。"""
        for entry in self._models.values():
            if entry.key != self._default:
                return entry.key
        return self._default or "miao"

    def describe(self) -> str:
        """给聊天看的模型列表：一列一个模型，只保留 key / 名称 / 标签。"""
        rows = []
        for entry in self._models.values():
            star = "★" if entry.key == self._default else " "
            tags = "、".join(entry.tags)
            off = "（已停用）" if not entry.enabled else ""
            rows.append((star, entry.key, self._style_of(entry), tags + off))
        if not rows:
            return "没有可用模型。"

        key_width = max(len(row[1]) for row in rows)
        label_width = max(len(row[2]) for row in rows)
        lines = ["默认模型带 ★", ""]
        for star, key, label, tail in rows:
            lines.append(f"{star} {key.ljust(key_width)}  {label.ljust(label_width)}  {tail}".rstrip())
        lines.append("")
        lines.append("用法：/img model=<key> 描述   ·   /draw <key> 描述")
        lines.append("别名也认：/img model=柔光 海边散步")
        return "\n".join(lines)

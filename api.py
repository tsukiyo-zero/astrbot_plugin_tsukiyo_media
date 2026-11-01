"""对外稳定 API：别的插件/上层只依赖这一个门面，不碰内部实现。"""
from __future__ import annotations

from typing import Any

from .core.catalog import ModelCatalog
from .core.pipeline import ImagePipeline
from .core.types import GenerationResult, ImageRequest


class TsukiyoMediaAPI:
    """最小对外接口：给一张请求，返回结果；外加模型查询。"""

    def __init__(self, pipeline: ImagePipeline, catalog: ModelCatalog) -> None:
        self._pipeline = pipeline
        self._catalog = catalog

    async def generate(self, request: ImageRequest) -> GenerationResult:
        return await self._pipeline.generate(request)

    def list_models(self) -> list[dict[str, Any]]:
        return [
            {
                "key": entry.key,
                "label": entry.label,
                "aliases": list(entry.aliases),
                "tags": list(entry.tags),
                "workflow": entry.workflow,
                "enabled": entry.enabled,
                "is_default": entry.key == self._catalog.default_key,
            }
            for entry in self._catalog.items()
        ]

    @property
    def default_model(self) -> str:
        return self._catalog.default_key

    @property
    def last_result(self) -> GenerationResult | None:
        return self._pipeline.history[-1] if self._pipeline.history else None

    def reload_models(self) -> None:
        self._catalog.load()

"""历史记录测试：确保"可重跑"所需的原始请求被写进去。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO.parent) not in sys.path:
    sys.path.insert(0, str(REPO.parent))

from astrbot_plugin_tsukiyo_media.core.catalog import ModelCatalog  # noqa: E402

try:  # pipeline 依赖 httpx；本机没装时跳过这些用例（CI 里会真正跑）
    from astrbot_plugin_tsukiyo_media.core.pipeline import (  # noqa: E402
        HISTORY_LIMIT,
        ImagePipeline,
        PipelineSettings,
    )

    HTTPX_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover
    HISTORY_LIMIT = 60
    ImagePipeline = object  # type: ignore[assignment,misc]
    PipelineSettings = object  # type: ignore[assignment,misc]
    HTTPX_AVAILABLE = False
from astrbot_plugin_tsukiyo_media.core.types import (  # noqa: E402
    KIND_SELFIE,
    GenerationResult,
    ImageRequest,
)


class DummyClient:
    """_save_history 不碰网络，这里只需要一个占位对象。"""

    async def close(self) -> None:  # pragma: no cover
        return None


def make_pipeline(tmpdir: str) -> ImagePipeline:
    return ImagePipeline(
        client=DummyClient(),  # type: ignore[arg-type]
        catalog=ModelCatalog(REPO / "models.json"),
        settings=PipelineSettings(),
        workflow_dir=REPO / "workflows",
        output_dir=Path(tmpdir) / "output",
        history_path=Path(tmpdir) / "history.json",
    )


def make_result(tmpdir: str) -> GenerationResult:
    return GenerationResult(
        ok=True,
        kind=KIND_SELFIE,
        model_key="selfie",
        workflow="selfie-ref.json",
        paths=[str(Path(tmpdir) / "output" / "a.png")],
        elapsed_ms=1234,
        seed=42,
        positive="masterpiece, test",
        negative="bad hands",
    )


@unittest.skipUnless(HTTPX_AVAILABLE, "需要 httpx（在容器/CI 里运行）")
class TestHistoryRecord(unittest.TestCase):
    def test_record_keeps_original_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = make_pipeline(tmp)
            request = ImageRequest(
                prompt="sitting on bed",
                kind=KIND_SELFIE,
                width=832,
                height=1216,
                seed=42,
                extra_negative="blurry",
                references=["/tmp/ref.png"],
            )
            pipeline._save_history(make_result(tmp), request)

            data = json.loads((Path(tmp) / "history.json").read_text(encoding="utf-8"))
            self.assertEqual(len(data), 1)
            record = data[0]
            self.assertEqual(record["request"]["prompt"], "sitting on bed")
            self.assertEqual(record["request"]["width"], 832)
            self.assertEqual(record["request"]["height"], 1216)
            self.assertEqual(record["request"]["extra_negative"], "blurry")
            self.assertEqual(record["request"]["references"], ["/tmp/ref.png"])
            # 最终提示词也要留着，方便对照 /history
            self.assertEqual(record["positive"], "masterpiece, test")
            self.assertEqual(record["seed"], 42)

    def test_record_survives_missing_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = make_pipeline(tmp)
            pipeline._save_history(make_result(tmp))
            data = json.loads((Path(tmp) / "history.json").read_text(encoding="utf-8"))
            self.assertEqual(len(data), 1)
            self.assertNotIn("request", data[0])

    def test_history_is_capped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = make_pipeline(tmp)
            result = make_result(tmp)
            for index in range(HISTORY_LIMIT + 5):
                pipeline._save_history(result)
            data = json.loads((Path(tmp) / "history.json").read_text(encoding="utf-8"))
            self.assertEqual(len(data), HISTORY_LIMIT)

    def test_history_reload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first = make_pipeline(tmp)
            first._save_history(make_result(tmp))
            second = make_pipeline(tmp)
            self.assertEqual(len(second.records), 1)
            self.assertEqual(second.records[0]["kind"], KIND_SELFIE)


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

from astrbot_plugin_tsukiyo_media.core.catalog import ModelCatalog
from astrbot_plugin_tsukiyo_media.core.pipeline import ImagePipeline, KindProfile, PipelineSettings
from astrbot_plugin_tsukiyo_media.core.types import KIND_SELFIE, ImageRequest

ROOT = Path(__file__).resolve().parents[1]


class BuildPlanTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.pipeline = ImagePipeline(
            client=None,
            catalog=ModelCatalog(ROOT / "models.json"),
            settings=PipelineSettings(
                profiles={
                    KIND_SELFIE: KindProfile(
                        workflow="selfie-ref.json", width=832, height=1216
                    )
                }
            ),
            workflow_dir=ROOT / "workflows",
            output_dir=Path(self.tmp.name),
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_selfie_without_model_keeps_profile(self) -> None:
        kind, entry, profile = self.pipeline.build_plan(
            ImageRequest(prompt="x", kind=KIND_SELFIE)
        )
        self.assertEqual(kind, KIND_SELFIE)
        self.assertIsNone(entry)
        self.assertEqual(profile.workflow, "selfie-ref.json")
        self.assertEqual((profile.width, profile.height), (832, 1216))

    def test_selfie_with_model_takes_its_size(self) -> None:
        kind, entry, profile = self.pipeline.build_plan(
            ImageRequest(prompt="x", kind=KIND_SELFIE, model_key="pixel")
        )
        self.assertEqual(kind, KIND_SELFIE)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.key, "pixel")
        # 工作流结构不变，参数跟模型走
        self.assertEqual(profile.workflow, "selfie-ref.json")
        self.assertEqual((profile.width, profile.height), (768, 1280))

    def test_checkpoint_of_reads_model_workflow(self) -> None:
        self.assertEqual(
            self.pipeline.checkpoint_of("draw-pixel.json"),
            "miaomiaoPixel_vPred11.safetensors",
        )
        self.assertEqual(
            self.pipeline.checkpoint_of("selfie-ref.json"),
            "oneObsession_v24.safetensors",
        )
        self.assertEqual(self.pipeline.checkpoint_of("no-such.json"), "")


if __name__ == "__main__":
    unittest.main()

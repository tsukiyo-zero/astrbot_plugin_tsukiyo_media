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

    def test_selfie_uses_profile_default_model(self) -> None:
        """QQ/命令/工具没传 model_key 时，用该档配置的默认模型。"""
        self.pipeline.settings.profiles[KIND_SELFIE].model_key = "pixel"
        kind, entry, profile = self.pipeline.build_plan(
            ImageRequest(prompt="x", kind=KIND_SELFIE)
        )
        self.assertIsNotNone(entry)
        self.assertEqual(entry.key, "pixel")
        self.assertEqual((profile.width, profile.height), (768, 1280))

    def test_request_model_wins_over_profile_default(self) -> None:
        self.pipeline.settings.profiles[KIND_SELFIE].model_key = "pixel"
        _, entry, _ = self.pipeline.build_plan(
            ImageRequest(prompt="x", kind=KIND_SELFIE, model_key="miao")
        )
        self.assertEqual(entry.key, "miao")

    def test_missing_profile_default_model_falls_back(self) -> None:
        """默认模型被删了也不能把出图卡死。"""
        self.pipeline.settings.profiles[KIND_SELFIE].model_key = "no-such-model"
        _, entry, profile = self.pipeline.build_plan(
            ImageRequest(prompt="x", kind=KIND_SELFIE)
        )
        self.assertIsNone(entry)
        self.assertEqual(profile.workflow, "selfie-ref.json")

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

    def test_author_prompts_follow_model(self) -> None:
        pos, neg = self.pipeline.author_prompts("draw-miao.json")
        self.assertIn("pale_skin", pos)
        self.assertIn("bad feet", neg)
        # 专用工作流的作者词与所选模型不同，正好用来区分
        selfie_pos, _ = self.pipeline.author_prompts("selfie-ref.json")
        self.assertNotEqual(pos, selfie_pos)
        self.assertEqual(self.pipeline.author_prompts("no-such.json"), ("", ""))


if __name__ == "__main__":
    unittest.main()

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
                profiles={KIND_SELFIE: KindProfile(workflow="selfie/default.json")}
            ),
            workflow_dir=ROOT / "workflows",
            output_dir=Path(self.tmp.name),
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_selfie_without_model_uses_default_file(self) -> None:
        kind, entry, profile = self.pipeline.build_plan(
            ImageRequest(prompt="x", kind=KIND_SELFIE)
        )
        self.assertEqual(kind, KIND_SELFIE)
        self.assertIsNone(entry)
        self.assertEqual(profile.workflow, "selfie/default.json")

    def test_selfie_with_model_uses_its_own_file(self) -> None:
        """选模型 = 选文件：selfie/miao.json。"""
        _, entry, profile = self.pipeline.build_plan(
            ImageRequest(prompt="x", kind=KIND_SELFIE, model_key="miao")
        )
        self.assertIsNone(entry)
        self.assertEqual(profile.workflow, "selfie/miao.json")

    def test_selfie_model_without_file_falls_back_to_default(self) -> None:
        """没有专属文件（如 pixel）就用 selfie/default.json，不报错。"""
        _, _, profile = self.pipeline.build_plan(
            ImageRequest(prompt="x", kind=KIND_SELFIE, model_key="pixel")
        )
        self.assertEqual(profile.workflow, "selfie/default.json")

    def test_profile_default_model_is_used(self) -> None:
        self.pipeline.settings.profiles[KIND_SELFIE].model_key = "novaflat"
        _, _, profile = self.pipeline.build_plan(
            ImageRequest(prompt="x", kind=KIND_SELFIE)
        )
        self.assertEqual(profile.workflow, "selfie/novaflat.json")

    def test_request_model_wins_over_profile_default(self) -> None:
        self.pipeline.settings.profiles[KIND_SELFIE].model_key = "novaflat"
        _, _, profile = self.pipeline.build_plan(
            ImageRequest(prompt="x", kind=KIND_SELFIE, model_key="miao")
        )
        self.assertEqual(profile.workflow, "selfie/miao.json")

    def test_unknown_model_falls_back(self) -> None:
        _, _, profile = self.pipeline.build_plan(
            ImageRequest(prompt="x", kind=KIND_SELFIE, model_key="no-such-model")
        )
        self.assertEqual(profile.workflow, "selfie/default.json")

    def test_model_key_cannot_escape_directory(self) -> None:
        _, _, profile = self.pipeline.build_plan(
            ImageRequest(prompt="x", kind=KIND_SELFIE, model_key="../text2img/draw-miao")
        )
        self.assertEqual(profile.workflow, "selfie/default.json")

    def test_checkpoint_of_reads_model_workflow(self) -> None:
        self.assertEqual(
            self.pipeline.checkpoint_of("text2img/draw-pixel.json"),
            "miaomiaoPixel_vPred11.safetensors",
        )
        self.assertEqual(
            self.pipeline.checkpoint_of("selfie/miao.json"),
            "miaomiaoRealskin_epsV14.safetensors",
        )
        self.assertEqual(self.pipeline.checkpoint_of("no-such.json"), "")

    def test_author_prompts_follow_model(self) -> None:
        pos, neg = self.pipeline.author_prompts("text2img/draw-miao.json")
        self.assertIn("pale_skin", pos)
        self.assertIn("bad feet", neg)
        selfie_pos, _ = self.pipeline.author_prompts("selfie/default.json")
        self.assertNotEqual(pos, selfie_pos)
        self.assertEqual(self.pipeline.author_prompts("no-such.json"), ("", ""))

    def test_selfie_variants_are_complete_workflows(self) -> None:
        """每个变体都自带底模与作者词，不依赖运行时覆盖。"""
        miao = self.pipeline.load_workflow("selfie/miao.json")
        self.assertEqual(
            self.pipeline.checkpoint_of("selfie/miao.json"),
            "miaomiaoRealskin_epsV14.safetensors",
        )
        pos, _ = self.pipeline.author_prompts("selfie/miao.json")
        self.assertIn("pale_skin", pos)
        self.assertIn("ipa", miao)


if __name__ == "__main__":
    unittest.main()

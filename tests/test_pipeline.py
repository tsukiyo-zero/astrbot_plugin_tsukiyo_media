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
                profiles={KIND_SELFIE: KindProfile(workflow="selfie/miao.json")}
            ),
            workflow_dir=ROOT / "workflows",
            output_dir=Path(self.tmp.name),
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_selfie_without_model_uses_configured_workflow(self) -> None:
        """没指定模型：用三档配置里选的那个文件，它就是默认。"""
        kind, entry, profile = self.pipeline.build_plan(
            ImageRequest(prompt="x", kind=KIND_SELFIE)
        )
        self.assertEqual(kind, KIND_SELFIE)
        self.assertIsNone(entry)
        self.assertEqual(profile.workflow, "selfie/miao.json")

    def test_selfie_with_model_uses_its_own_file(self) -> None:
        _, _, profile = self.pipeline.build_plan(
            ImageRequest(prompt="x", kind=KIND_SELFIE, model_key="novaflat")
        )
        self.assertEqual(profile.workflow, "selfie/novaflat.json")

    def test_model_without_file_falls_back_to_configured(self) -> None:
        """没有专属文件（如 pixel）就用配置里那个，不报错。"""
        _, _, profile = self.pipeline.build_plan(
            ImageRequest(prompt="x", kind=KIND_SELFIE, model_key="pixel")
        )
        self.assertEqual(profile.workflow, "selfie/miao.json")

    def test_unknown_model_falls_back(self) -> None:
        _, _, profile = self.pipeline.build_plan(
            ImageRequest(prompt="x", kind=KIND_SELFIE, model_key="no-such-model")
        )
        self.assertEqual(profile.workflow, "selfie/miao.json")

    def test_model_key_cannot_escape_directory(self) -> None:
        _, _, profile = self.pipeline.build_plan(
            ImageRequest(prompt="x", kind=KIND_SELFIE, model_key="../text2img/draw-miao")
        )
        self.assertEqual(profile.workflow, "selfie/miao.json")

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
        selfie_pos, _ = self.pipeline.author_prompts("selfie/obsession.json")
        self.assertNotEqual(pos, selfie_pos)
        self.assertEqual(self.pipeline.author_prompts("no-such.json"), ("", ""))

    def test_selfie_variants_are_complete_workflows(self) -> None:
        """每个变体自带底模、作者词与 IP-Adapter，不依赖运行时覆盖。"""
        workflow = self.pipeline.load_workflow("selfie/novaflat.json")
        self.assertIn("ipa", workflow)
        self.assertEqual(
            self.pipeline.checkpoint_of("selfie/novaflat.json"),
            "novaFlatXL_v90.safetensors",
        )


if __name__ == "__main__":
    unittest.main()

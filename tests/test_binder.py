"""工作流绑定测试：不联网、不需要 GPU。"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO.parent) not in sys.path:
    sys.path.insert(0, str(REPO.parent))

from astrbot_plugin_tsukiyo_media.backends.comfyui.binder import (  # noqa: E402
    BindValues,
    apply_values,
    resolve_roles,
)
from astrbot_plugin_tsukiyo_media.core.errors import BindError  # noqa: E402

WORKFLOW_DIR = REPO / "workflows"
SELFIE = "selfie/default.json"
REFERENCE = "reference/default.json"
IMG2IMG = "edit/default.json"
DRAW = "text2img/draw-miao.json"


def load(name: str) -> dict:
    return json.loads((WORKFLOW_DIR / name).read_text(encoding="utf-8"))


class TestResolveRoles(unittest.TestCase):
    def test_every_shipped_workflow_resolves(self) -> None:
        for path in sorted(WORKFLOW_DIR.glob("*.json")):
            with self.subTest(workflow=path.name):
                roles = resolve_roles(load(path.name))
                self.assertTrue(roles.sampler)
                self.assertTrue(roles.positive)
                self.assertTrue(roles.negative)
                self.assertTrue(roles.save)

    def test_selfie_has_ipadapter_and_identity_ref(self) -> None:
        roles = resolve_roles(load(SELFIE))
        self.assertTrue(roles.ipadapter)
        self.assertTrue(roles.identity_ref)
        self.assertTrue(roles.empty_latent)
        self.assertEqual(roles.vae_encode, "")

    def test_img2img_has_source_image(self) -> None:
        roles = resolve_roles(load(IMG2IMG))
        self.assertTrue(roles.vae_encode)
        self.assertTrue(roles.source_image)
        self.assertTrue(roles.image_scale)
        self.assertEqual(roles.identity_ref, "")

    def test_missing_sampler_raises(self) -> None:
        broken = {"1": {"class_type": "CLIPTextEncode", "inputs": {"text": "x"}}}
        with self.assertRaises(BindError):
            resolve_roles(broken)

    def test_ambiguous_sampler_raises(self) -> None:
        workflow = load(DRAW)
        workflow["extra"] = {"class_type": "KSampler", "inputs": {}}
        with self.assertRaises(BindError):
            resolve_roles(workflow)


class TestApplyValues(unittest.TestCase):
    def test_append_keeps_author_words(self) -> None:
        workflow = load(SELFIE)
        roles = resolve_roles(workflow)
        author_text = workflow[roles.positive]["inputs"]["text"]

        prompt = apply_values(
            workflow,
            roles,
            BindValues(positive="beach, sunset", negative="blurry", seed=123),
        )
        final = prompt[roles.positive]["inputs"]["text"]
        self.assertTrue(final.startswith(author_text))
        self.assertTrue(final.endswith("beach, sunset"))
        self.assertIn("blurry", prompt[roles.negative]["inputs"]["text"])

    def test_replace_mode_drops_author_words(self) -> None:
        workflow = load(SELFIE)
        roles = resolve_roles(workflow)
        prompt = apply_values(
            workflow,
            roles,
            BindValues(positive="only this", prompt_mode="replace"),
        )
        self.assertEqual(prompt[roles.positive]["inputs"]["text"], "only this")

    def test_seed_size_ipadapter_and_images(self) -> None:
        workflow = load(SELFIE)
        roles = resolve_roles(workflow)
        prompt = apply_values(
            workflow,
            roles,
            BindValues(
                positive="p",
                width=768,
                height=1280,
                seed=42,
                ipadapter_weight=0.4,
                identity_image="uploaded_ref.png",
                filename_prefix="test",
            ),
        )
        self.assertEqual(prompt[roles.sampler]["inputs"]["seed"], 42)
        self.assertEqual(prompt[roles.empty_latent]["inputs"]["width"], 768)
        self.assertEqual(prompt[roles.empty_latent]["inputs"]["height"], 1280)
        self.assertEqual(prompt[roles.ipadapter]["inputs"]["weight"], 0.4)
        self.assertEqual(prompt[roles.identity_ref]["inputs"]["image"], "uploaded_ref.png")
        self.assertEqual(prompt[roles.save]["inputs"]["filename_prefix"], "test")

    def test_random_seed_when_negative(self) -> None:
        workflow = load(DRAW)
        roles = resolve_roles(workflow)
        prompt = apply_values(workflow, roles, BindValues(positive="p", seed=-1))
        seed = prompt[roles.sampler]["inputs"]["seed"]
        self.assertGreaterEqual(seed, 0)
        self.assertLess(seed, 2**32)

    def test_denoise_only_touches_existing_field(self) -> None:
        workflow = load(IMG2IMG)
        roles = resolve_roles(workflow)
        prompt = apply_values(workflow, roles, BindValues(positive="p", denoise=0.6))
        self.assertEqual(prompt[roles.sampler]["inputs"]["denoise"], 0.6)

    def test_author_prompt_replaces_workflow_text(self) -> None:
        """换模型时用该模型的作者词整段替换，再追加本次词。"""
        workflow = load(SELFIE)
        roles = resolve_roles(workflow)
        prompt = apply_values(
            workflow,
            roles,
            BindValues(
                positive="cowboy shot, standing",
                author_positive="masterpiece, ultra detailed, pale_skin",
            ),
        )
        text = prompt[roles.positive]["inputs"]["text"]
        self.assertTrue(text.startswith("masterpiece, ultra detailed, pale_skin"))
        self.assertIn("cowboy shot", text)
        self.assertNotIn("very awa", text)

    def test_author_prompt_untouched_without_override(self) -> None:
        workflow = load(SELFIE)
        roles = resolve_roles(workflow)
        original = workflow[roles.positive]["inputs"]["text"]
        prompt = apply_values(workflow, roles, BindValues(positive="cowboy shot"))
        self.assertTrue(prompt[roles.positive]["inputs"]["text"].startswith(original))

    def test_checkpoint_override_on_special_workflow(self) -> None:
        """自拍/参考图这类专用工作流也要能按所选模型换底模。"""
        workflow = load(SELFIE)
        roles = resolve_roles(workflow)
        self.assertTrue(roles.checkpoint)
        prompt = apply_values(
            workflow,
            roles,
            BindValues(positive="p", ckpt_name="miaomiaoRealskin_epsV14.safetensors"),
        )
        self.assertEqual(
            prompt[roles.checkpoint]["inputs"]["ckpt_name"],
            "miaomiaoRealskin_epsV14.safetensors",
        )

    def test_checkpoint_untouched_without_override(self) -> None:
        workflow = load(SELFIE)
        roles = resolve_roles(workflow)
        original = workflow[roles.checkpoint]["inputs"]["ckpt_name"]
        prompt = apply_values(workflow, roles, BindValues(positive="p"))
        self.assertEqual(prompt[roles.checkpoint]["inputs"]["ckpt_name"], original)

    def test_sampler_override_whitelist(self) -> None:
        workflow = load(DRAW)
        roles = resolve_roles(workflow)
        prompt = apply_values(
            workflow,
            roles,
            BindValues(positive="p", sampler_override={"steps": 20, "nonsense": 1}),
        )
        inputs = prompt[roles.sampler]["inputs"]
        self.assertEqual(inputs["steps"], 20)
        self.assertNotIn("nonsense", inputs)

    def test_source_copy_isolation(self) -> None:
        """apply_values 不能改到原工作流对象。"""
        workflow = load(SELFIE)
        roles = resolve_roles(workflow)
        before = workflow[roles.positive]["inputs"]["text"]
        apply_values(workflow, roles, BindValues(positive="changed"))
        self.assertEqual(workflow[roles.positive]["inputs"]["text"], before)


if __name__ == "__main__":
    unittest.main()

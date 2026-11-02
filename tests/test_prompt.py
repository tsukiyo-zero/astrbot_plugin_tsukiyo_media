"""提示词清洗与拼装测试。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO.parent) not in sys.path:
    sys.path.insert(0, str(REPO.parent))

from astrbot_plugin_tsukiyo_media.core.prompt import (  # noqa: E402
    build_prompt,
    join_parts,
    sanitize,
    strip_cjk_clauses,
)
from astrbot_plugin_tsukiyo_media.core.types import KIND_SELFIE, KIND_TEXT2IMG  # noqa: E402


class TestSanitize(unittest.TestCase):
    def test_negative_weight_syntax_removed(self) -> None:
        cleaned = sanitize("1girl, -1.5::a selfie or portrait::, beach")
        self.assertNotIn("::", cleaned)
        self.assertIn("1girl", cleaned)
        self.assertIn("beach", cleaned)

    def test_rule_section_removed(self) -> None:
        raw = "beach, sunset, Image edit contract: use the source image as the sole canvas, keep identity"
        cleaned = sanitize(raw)
        self.assertIn("beach", cleaned)
        self.assertNotIn("sole canvas", cleaned)

    def test_heading_labels_removed(self) -> None:
        cleaned = sanitize("Positive prompt: 1girl, blue hair, Negative prompt: bad hands")
        self.assertNotIn("Positive prompt:", cleaned)
        self.assertIn("1girl", cleaned)

    def test_blank_input(self) -> None:
        self.assertEqual(sanitize(""), "")
        self.assertEqual(sanitize("   ,,,  "), "")

    def test_drop_cjk(self) -> None:
        self.assertEqual(strip_cjk_clauses("blue hair, 蓝色头发, beach"), "blue hair, beach")


class TestJoinParts(unittest.TestCase):
    def test_dedup_and_blank(self) -> None:
        self.assertEqual(join_parts(["a", " ", "a", "b"]), "a, b")


class TestBuildPrompt(unittest.TestCase):
    def test_selfie_puts_identity_first(self) -> None:
        bundle = build_prompt(
            user_prompt="sitting on bed",
            kind=KIND_SELFIE,
            identity_prompt="blue hair, whale tail",
            fixed_prompt="cowboy shot",
            global_negative="bad hands",
        )
        self.assertTrue(bundle.positive.startswith("blue hair, whale tail"))
        self.assertIn("cowboy shot", bundle.positive)
        self.assertTrue(bundle.positive.endswith("sitting on bed"))
        self.assertEqual(bundle.negative, "bad hands")
        self.assertEqual([name for name, _ in bundle.parts], ["identity", "fixed", "user"])

    def test_text2img_has_no_identity(self) -> None:
        bundle = build_prompt(
            user_prompt="a cat",
            kind=KIND_TEXT2IMG,
            identity_prompt="should be ignored",
            fixed_prompt="",
        )
        self.assertNotIn("should be ignored", bundle.positive)
        self.assertEqual(bundle.positive, "a cat")

    def test_extra_negative_kept(self) -> None:
        bundle = build_prompt(
            user_prompt="x",
            kind=KIND_TEXT2IMG,
            global_negative="bad hands",
            extra_negative="blurry",
        )
        self.assertIn("bad hands", bundle.negative)
        self.assertIn("blurry", bundle.negative)


    def test_fixed_negative_kept(self) -> None:
        """三档里的「固定负面词」要追加在全局负面词之后、本次额外词之前。"""
        bundle = build_prompt(
            user_prompt="x",
            kind=KIND_SELFIE,
            fixed_negative="extra limbs, bad feet",
            global_negative="bad hands",
            extra_negative="blurry",
        )
        self.assertEqual(bundle.negative, "bad hands, extra limbs, bad feet, blurry")

    def test_fixed_negative_empty_is_noop(self) -> None:
        bundle = build_prompt(
            user_prompt="x",
            kind=KIND_SELFIE,
            fixed_negative="  ",
            global_negative="bad hands",
        )
        self.assertEqual(bundle.negative, "bad hands")


if __name__ == "__main__":
    unittest.main()

"""路由与选模测试：纯规则，不联网。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO.parent) not in sys.path:
    sys.path.insert(0, str(REPO.parent))

from astrbot_plugin_tsukiyo_media.core.catalog import ModelCatalog  # noqa: E402
from astrbot_plugin_tsukiyo_media.core.errors import RoutingError  # noqa: E402
from astrbot_plugin_tsukiyo_media.core.router import correct_kind, route_kind, select_model  # noqa: E402
from astrbot_plugin_tsukiyo_media.core.types import (  # noqa: E402
    KIND_EDIT,
    KIND_REFERENCE,
    KIND_SELFIE,
    KIND_TEXT2IMG,
    ImageRequest,
)

CATALOG = ModelCatalog(REPO / "models.json")


class TestRouteKind(unittest.TestCase):
    def test_selfie_keywords(self) -> None:
        for text in ("来张自拍", "拍一张给我看看", "看看你现在的样子", "selfie please"):
            with self.subTest(text=text):
                self.assertEqual(route_kind(ImageRequest(prompt=text)), KIND_SELFIE)

    def test_plain_text_goes_text2img(self) -> None:
        self.assertEqual(route_kind(ImageRequest(prompt="一只在屋顶睡觉的橘猫")), KIND_TEXT2IMG)

    def test_reference_defaults_when_image_present(self) -> None:
        request = ImageRequest(prompt="海边散步", references=["a.png"])
        self.assertEqual(route_kind(request), KIND_REFERENCE)

    def test_edit_keywords_win_with_image(self) -> None:
        for text in ("把衣服换成蓝色", "去掉背景", "remove the hat", "改成夜景"):
            with self.subTest(text=text):
                request = ImageRequest(prompt=text, references=["a.png"])
                self.assertEqual(route_kind(request), KIND_EDIT)

    def test_explicit_kind_wins(self) -> None:
        request = ImageRequest(prompt="随便", kind="selfie", references=["a.png"])
        self.assertEqual(route_kind(request), KIND_SELFIE)

    def test_unknown_kind_falls_back_to_auto(self) -> None:
        self.assertEqual(route_kind(ImageRequest(prompt="一只猫", kind="???")), KIND_TEXT2IMG)


class TestSelectModel(unittest.TestCase):
    def test_explicit_key(self) -> None:
        entry, reason = select_model(CATALOG, "anything", "miao")
        self.assertEqual(entry.key, "miao")
        self.assertEqual(reason, "explicit")

    def test_alias_and_chinese_label(self) -> None:
        self.assertEqual(select_model(CATALOG, "", "柔光")[0].key, "miao")
        self.assertEqual(select_model(CATALOG, "", "像素")[0].key, "pixel")

    def test_style_hint_from_prompt(self) -> None:
        self.assertEqual(select_model(CATALOG, "来个像素风的房间")[0].key, "pixel")
        self.assertEqual(select_model(CATALOG, "写实照片，人像特写")[0].key, "xxmix")

    def test_model_name_in_hint(self) -> None:
        """用户原话里点名模型/别名时优先用它。"""
        entry, reason = select_model(CATALOG, "a cat on a roof", hint="用柔光画一只猫")
        self.assertEqual(entry.key, "miao")
        self.assertTrue(reason.startswith("name:"))

    def test_model_name_in_prompt(self) -> None:
        entry, reason = select_model(CATALOG, "pixel art style room, 8bit")
        self.assertEqual(entry.key, "pixel")
        self.assertIn(reason, {"name:pixel", "style:像素|pixel|8bit|8-bit"})

    def test_ascii_alias_needs_word_boundary(self) -> None:
        """`cat` 不能命中 `concatenate` 这种词。"""
        entry, _ = select_model(CATALOG, "a concatenate experiment")
        self.assertNotEqual(entry.key, "cat")

    def test_ascii_key_not_matched_from_translated_tags(self) -> None:
        """`cat girl` 是普通 tag，不能把模型选成 cat。"""
        entry, _ = select_model(CATALOG, "pixel art, 8bit, cat girl, cat ears")
        self.assertNotEqual(entry.key, "cat")
        self.assertEqual(entry.key, "pixel")

    def test_ascii_key_with_lead_word(self) -> None:
        entry, reason = select_model(CATALOG, "a room", hint="用cat画一个房间")
        self.assertEqual(entry.key, "cat")
        self.assertTrue(reason.startswith("name:"))

    def test_chinese_alias_from_hint(self) -> None:
        entry, _ = select_model(CATALOG, "a cat on a roof", hint="画个像素猫娘")
        self.assertEqual(entry.key, "pixel")

    def test_default_when_no_hint(self) -> None:
        entry, reason = select_model(CATALOG, "一个女孩在看书")
        self.assertEqual(entry.key, CATALOG.default_key)
        self.assertEqual(reason, "default")

    def test_unknown_key_raises(self) -> None:
        with self.assertRaises(RoutingError):
            CATALOG.get("不存在的模型")

    def test_catalog_sanity(self) -> None:
        self.assertTrue(CATALOG.items())
        self.assertIn(CATALOG.default_key, CATALOG.keys())


class TestCorrectKind(unittest.TestCase):
    def test_edit_with_reference_wording_becomes_reference(self) -> None:
        """模型显式选了 edit，但描述是“参考这张画新场景”时纠正为 reference。"""
        request = ImageRequest(
            prompt="参考这张图，给我画一张在海边散步的图片",
            kind="edit",
            references=["a.png"],
        )
        self.assertEqual(correct_kind(KIND_EDIT, request), KIND_REFERENCE)

    def test_hint_from_user_message_triggers_correction(self) -> None:
        """模型把“参考这张”从 prompt 里省了，但用户原话里有 → 仍能纠正。"""
        request = ImageRequest(
            prompt="walking on beach, seaside, sunset, white hoodie",
            kind="edit",
            references=["a.png"],
            hint="参考这张图，画她在海边散步",
        )
        self.assertEqual(correct_kind(KIND_EDIT, request), KIND_REFERENCE)

    def test_real_edit_stays_edit(self) -> None:
        request = ImageRequest(prompt="把这张图改成夜景", kind="edit", references=["a.png"])
        self.assertEqual(correct_kind(KIND_EDIT, request), KIND_EDIT)

    def test_edit_without_reference_stays_edit(self) -> None:
        request = ImageRequest(prompt="参考这张图", kind="edit")
        self.assertEqual(correct_kind(KIND_EDIT, request), KIND_EDIT)

    def test_other_kinds_untouched(self) -> None:
        request = ImageRequest(prompt="参考这张图", kind="selfie", references=["a.png"])
        self.assertEqual(correct_kind(KIND_SELFIE, request), KIND_SELFIE)


if __name__ == "__main__":
    unittest.main()


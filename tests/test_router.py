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
from astrbot_plugin_tsukiyo_media.core.router import route_kind, select_model  # noqa: E402
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


if __name__ == "__main__":
    unittest.main()

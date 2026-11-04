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
        self.assertEqual(select_model(CATALOG, "厚涂块面风格的人像")[0].key, "748cm")

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
        """短 key 不能命中更长的英文单词（原 cat/concatenate 用例）。"""
        entry, _ = select_model(CATALOG, "a concatenate experiment")
        self.assertNotEqual(entry.key, "748cm")

    def test_ascii_key_not_matched_from_translated_tags(self) -> None:
        """`748` 出现在普通 tag 里不能抢走模型选择。"""
        entry, _ = select_model(CATALOG, "pixel art, 8bit, cat girl, cat ears")
        self.assertNotEqual(entry.key, "748cm")
        self.assertEqual(entry.key, "pixel")

    def test_ascii_key_with_lead_word(self) -> None:
        entry, reason = select_model(CATALOG, "a room", hint="用748cm画一个房间")
        self.assertEqual(entry.key, "748cm")
        self.assertTrue(reason.startswith("name:"))

    def test_chinese_alias_from_hint(self) -> None:
        entry, _ = select_model(CATALOG, "a cat on a roof", hint="画个像素猫娘")
        self.assertEqual(entry.key, "pixel")

    def test_default_when_no_hint(self) -> None:
        entry, reason = select_model(CATALOG, "一个女孩在看书")
        self.assertEqual(entry.key, CATALOG.default_key)
        self.assertEqual(reason, "default")

    def test_llm_tags_do_not_pick_model(self) -> None:
        """LLM 翻译出来的 tag 里常有 soft light / realistic，不能拿它选模。

        真实案例：用户说“给我画一只猫娘…”，LLM 自己加了 `soft light`，
        结果默认模型 obsession 被悄悄换成了 miao。
        """
        prompt = ("1girl, cat girl, blue cat ears, blue eyes, whiskers, bikini, "
                  "kneeling, seiza, floor, simple background, soft light")
        hint = "给我画一只猫娘，蓝眼睛，蓝耳朵，有胡须，穿着比基尼，跪坐在地上"
        entry, reason = select_model(CATALOG, prompt, "", hint)
        self.assertEqual(entry.key, CATALOG.default_key)
        self.assertEqual(reason, "default")

    def test_photoreal_tag_in_prompt_does_not_override_default(self) -> None:
        entry, _ = select_model(
            CATALOG, "photorealistic, realistic, soft light, 1girl", "", "画个猫娘"
        )
        self.assertEqual(entry.key, CATALOG.default_key)

    def test_style_word_from_user_words_still_wins(self) -> None:
        """用户在**原话**里说了风格词，仍然要生效（哪怕 prompt 里是别的风格）。"""
        entry, reason = select_model(CATALOG, "a room, realistic, photorealistic", "", "用像素画")
        self.assertEqual(entry.key, "pixel")
        self.assertTrue(reason.startswith(("style:", "name:")))

    def test_no_hint_falls_back_to_prompt_style(self) -> None:
        """页面 / API 直调没有原话，退回用 prompt 自身的风格词。"""
        entry, _ = select_model(CATALOG, "来个像素风的房间")
        self.assertEqual(entry.key, "pixel")

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


class TestSceneChangeRouting(unittest.TestCase):
    """场景/背景类改造走 reference；局部改造（衣服/头发/颜色）留在 edit。"""

    def test_background_change_beats_edit_wording(self) -> None:
        """真实案例：句子里同时有“参考这张”和“换成”，但改的是背景。"""
        request = ImageRequest(
            prompt="purple short hair, beach, sea, sand, ocean, sunset light, waves, outdoors",
            kind="edit",
            references=["a.png"],
            hint="参考这张图，把背景换成海边",
        )
        self.assertEqual(correct_kind(KIND_EDIT, request), KIND_REFERENCE)

    def test_background_change_without_reference_anchor(self) -> None:
        request = ImageRequest(prompt="背景换成海边", kind="edit", references=["a.png"])
        self.assertEqual(correct_kind(KIND_EDIT, request), KIND_REFERENCE)

    def test_pose_change_goes_reference(self) -> None:
        request = ImageRequest(prompt="换个姿势坐着", kind="edit", references=["a.png"])
        self.assertEqual(correct_kind(KIND_EDIT, request), KIND_REFERENCE)

    def test_reference_anchor_without_edit_word(self) -> None:
        request = ImageRequest(prompt="beach, walking", kind="edit", references=["a.png"],
                               hint="参考这张，画她在海边")
        self.assertEqual(correct_kind(KIND_EDIT, request), KIND_REFERENCE)

    def test_local_edits_stay_edit(self) -> None:
        for hint in ("把衣服改成白色", "把头发变成黑色", "去掉帽子", "加个眼镜"):
            with self.subTest(hint=hint):
                request = ImageRequest(prompt="1girl, indoor", kind="edit",
                                       references=["a.png"], hint=hint)
                self.assertEqual(correct_kind(KIND_EDIT, request), KIND_EDIT)

    def test_anchor_plus_local_edit_stays_edit(self) -> None:
        """“参考这张，把衣服改成白色”既要保留构图又要改局部 → edit。"""
        request = ImageRequest(prompt="white shirt", kind="edit", references=["a.png"],
                               hint="参考这张图，把衣服改成白色")
        self.assertEqual(correct_kind(KIND_EDIT, request), KIND_EDIT)

    def test_auto_kind_prefers_reference_for_scene_words(self) -> None:
        request = ImageRequest(prompt="把背景换成森林", references=["a.png"])
        self.assertEqual(route_kind(request), KIND_REFERENCE)

    def test_auto_kind_keeps_edit_for_local_words(self) -> None:
        request = ImageRequest(prompt="把衣服换成蓝色", references=["a.png"])
        self.assertEqual(route_kind(request), KIND_EDIT)


if __name__ == "__main__":
    unittest.main()


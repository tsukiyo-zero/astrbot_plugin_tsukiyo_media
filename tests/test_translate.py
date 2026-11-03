"""中文转 tag 的单测（用假 Provider，不联网）。"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO.parent) not in sys.path:
    sys.path.insert(0, str(REPO.parent))

from astrbot_plugin_tsukiyo_media.core.translate import (  # noqa: E402
    PromptTranslator,
    clean_tags,
    has_cjk,
    maybe_translate,
)


class FakeProvider:
    def __init__(self, text: str, delay: float = 0.0) -> None:
        self.text = text
        self.delay = delay
        self.calls = 0

    async def text_chat(self, **kwargs):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)

        class R:
            completion_text = self.text

        return R()


class TestHasCjk(unittest.TestCase):
    def test_detect(self) -> None:
        self.assertTrue(has_cjk("教室里粉发少女"))
        self.assertFalse(has_cjk("1girl, classroom, sunset"))


class TestCleanTags(unittest.TestCase):
    def test_strips_explanation_and_quotes(self) -> None:
        self.assertEqual(clean_tags('"1girl, classroom, sunset"'), "1girl, classroom, sunset")

    def test_keeps_first_line_only(self) -> None:
        self.assertEqual(clean_tags("1girl, beach\n说明：这是一张画"), "1girl, beach")

    def test_chinese_output_is_rejected(self) -> None:
        self.assertEqual(clean_tags("1girl, 教室"), "")

    def test_fullwidth_comma(self) -> None:
        self.assertEqual(clean_tags("1girl，beach"), "1girl, beach")

    def test_empty(self) -> None:
        self.assertEqual(clean_tags(""), "")


class TestTranslator(unittest.TestCase):
    def test_translates_and_caches(self) -> None:
        provider = FakeProvider("1girl, classroom, sunset, pink hair")
        tr = PromptTranslator(get_provider=lambda: provider)
        first = asyncio.run(tr.to_tags("教室里粉发少女，夕阳"))
        self.assertIn("classroom", first)
        second = asyncio.run(tr.to_tags("教室里粉发少女，夕阳"))
        self.assertEqual(first, second)
        self.assertEqual(provider.calls, 1, "第二次应该命中缓存")

    def test_english_passthrough(self) -> None:
        tr = PromptTranslator(get_provider=lambda: FakeProvider("x"))
        self.assertEqual(asyncio.run(tr.to_tags("1girl, beach")), "1girl, beach")

    def test_provider_missing_returns_empty(self) -> None:
        tr = PromptTranslator(get_provider=lambda: None)
        self.assertEqual(asyncio.run(tr.to_tags("教室里")), "")

    def test_strips_chinese_prefix_keeps_tags(self) -> None:
        """模型偶尔写“好的，这是 tag：1girl”，要能剥掉中文前缀取到 tag。"""
        tr = PromptTranslator(get_provider=lambda: FakeProvider("好的，这是 tag：1girl, classroom"))
        self.assertEqual(asyncio.run(tr.to_tags("粉色头发")), "1girl, classroom")

    def test_fully_chinese_output_falls_back(self) -> None:
        tr = PromptTranslator(get_provider=lambda: FakeProvider("一个粉色头发的女孩"))
        self.assertEqual(asyncio.run(tr.to_tags("粉色头发")), "")

    def test_timeout_returns_empty(self) -> None:
        tr = PromptTranslator(get_provider=lambda: FakeProvider("1girl", delay=1.0))
        self.assertEqual(asyncio.run(tr.to_tags("粉色头发", timeout=0.05)), "")

    def test_exception_returns_empty(self) -> None:
        class Boom:
            async def text_chat(self, **kwargs):
                raise RuntimeError("boom")

        tr = PromptTranslator(get_provider=lambda: Boom())
        self.assertEqual(asyncio.run(tr.to_tags("粉色头发")), "")


class TestMaybeTranslate(unittest.TestCase):
    def test_disabled_keeps_original(self) -> None:
        tr = PromptTranslator(get_provider=lambda: FakeProvider("1girl"))
        out, ok = asyncio.run(maybe_translate(tr, "教室", enabled=False))
        self.assertEqual(out, "教室")
        self.assertFalse(ok)

    def test_success_replaces(self) -> None:
        tr = PromptTranslator(get_provider=lambda: FakeProvider("1girl, classroom"))
        out, ok = asyncio.run(maybe_translate(tr, "教室", enabled=True))
        self.assertEqual(out, "1girl, classroom")
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()

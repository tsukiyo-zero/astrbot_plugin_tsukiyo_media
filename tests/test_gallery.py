"""模型图鉴排版测试：分组、默认标记、别名示例、停用标记。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO.parent) not in sys.path:
    sys.path.insert(0, str(REPO.parent))

from astrbot_plugin_tsukiyo_media.core.catalog import ModelCatalog  # noqa: E402


class TestGallery(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = ModelCatalog(REPO / "models.json")
        self.text = self.catalog.gallery()

    def test_has_header_and_default(self) -> None:
        self.assertIn("模型图鉴", self.text)
        self.assertIn("⭐ [默认] " + self.catalog.default_key, self.text)
        self.assertIn("风格：", self.text)

    def test_groups_and_entries(self) -> None:
        self.assertIn("🎀 动漫系", self.text)
        self.assertIn("📷 写实系", self.text)
        for entry in self.catalog.items():
            self.assertIn("(" + entry.key + ")", self.text)

    def test_usage_hints(self) -> None:
        self.assertIn("/draw ", self.text)
        self.assertIn("/img model=", self.text)

    def test_tree_branches(self) -> None:
        self.assertIn("├ ", self.text)
        self.assertIn("└ ", self.text)

    def test_disabled_marked(self) -> None:
        raw = json.loads((REPO / "models.json").read_text(encoding="utf-8-sig"))
        first_key = next(iter(raw["models"]))
        raw["models"][first_key]["enabled"] = False
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "models.json"
            path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
            text = ModelCatalog(path).gallery()
        self.assertIn("（已停用）", text)


if __name__ == "__main__":
    unittest.main()

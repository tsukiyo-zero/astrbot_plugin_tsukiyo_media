"""出图后处理单测。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
if str(REPO.parent) not in sys.path:
    sys.path.insert(0, str(REPO.parent))

from PIL import Image  # noqa: E402

from astrbot_plugin_tsukiyo_media.core.postprocess import enhance_image  # noqa: E402


def make_gray_image(path: Path, size=(64, 64)) -> None:
    """低对比灰度图，方便观察增强效果。"""
    arr = np.full((size[1], size[0], 3), 128, dtype="uint8")
    arr[:, size[0] // 2:] = 140
    Image.fromarray(arr).save(path)


def block_contrast(path: Path) -> float:
    g = np.asarray(Image.open(path).convert("L")).astype("float32")
    return float(g.std())


class TestPostprocess(unittest.TestCase):
    def test_contrast_increases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.png"
            make_gray_image(p)
            before = block_contrast(p)
            changed = enhance_image(str(p), contrast=1.6, saturation=1.0, sharpen_percent=0)
            after = block_contrast(p)
            self.assertTrue(changed)
            self.assertGreater(after, before)

    def test_noop_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.png"
            make_gray_image(p)
            self.assertFalse(
                enhance_image(str(p), contrast=1.0, saturation=1.0, sharpen_percent=0)
            )

    def test_sharpen_only_changes_pixels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.png"
            make_gray_image(p)
            before = p.read_bytes()
            enhance_image(str(p), contrast=1.0, saturation=1.0, sharpen_percent=150)
            self.assertNotEqual(before, p.read_bytes())

    def test_keeps_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.png"
            make_gray_image(p, size=(48, 72))
            enhance_image(str(p), contrast=1.3, saturation=0.9, sharpen_percent=100)
            with Image.open(p) as im:
                self.assertEqual(im.size, (48, 72))

    def test_broken_file_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "bad.png"
            p.write_bytes(b"not an image")
            self.assertFalse(enhance_image(str(p), contrast=1.4, saturation=0.9))


if __name__ == "__main__":
    unittest.main()

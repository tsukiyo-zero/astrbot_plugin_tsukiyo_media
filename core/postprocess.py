"""出图后处理：对比/饱和/锐化（PIL，无需额外依赖）。

为什么需要：目标风格（厚涂 CG）的局部对比度比我们底模直出高一倍以上，
提升 CFG/加体积光词都补不上，后处理能把差距缩短约 70%。
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter


def enhance_image(
    path: str | Path,
    *,
    contrast: float = 1.4,
    saturation: float = 0.9,
    sharpen_percent: int = 120,
    sharpen_radius: float = 2.0,
    sharpen_threshold: int = 3,
) -> bool:
    """就地增强一张图；参数全为默认值时不做事。返回是否改动过。"""
    if (
        abs(contrast - 1.0) < 1e-3
        and abs(saturation - 1.0) < 1e-3
        and sharpen_percent <= 0
    ):
        return False
    target = Path(path)
    try:
        with Image.open(target) as raw:
            im = raw.convert("RGB")
    except Exception:
        return False

    if abs(contrast - 1.0) >= 1e-3:
        im = ImageEnhance.Contrast(im).enhance(float(contrast))
    if abs(saturation - 1.0) >= 1e-3:
        im = ImageEnhance.Color(im).enhance(float(saturation))
    if sharpen_percent > 0:
        im = im.filter(
            ImageFilter.UnsharpMask(
                radius=float(sharpen_radius),
                percent=int(sharpen_percent),
                threshold=int(sharpen_threshold),
            )
        )
    suffix = target.suffix.lower()
    if suffix in (".jpg", ".jpeg"):
        im.save(target, quality=95, subsampling=0)
    else:
        im.save(target)
    return True

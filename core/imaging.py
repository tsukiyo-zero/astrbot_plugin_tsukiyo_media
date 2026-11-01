"""图片处理：参考图压缩。PIL 缺失时安全降级为原样返回。"""
from __future__ import annotations

import io

try:  # PIL 在 AstrBot 镜像里默认存在，但插件不应强依赖
    from PIL import Image

    PIL_AVAILABLE = True
except Exception:  # pragma: no cover
    Image = None  # type: ignore[assignment]
    PIL_AVAILABLE = False

#: 超过这个字节数就压缩
SIZE_THRESHOLD = 2 * 1024 * 1024
#: 最长边上限
MAX_SIDE = 1536
#: JPEG 质量
QUALITY = 88


def compress_image_bytes(data: bytes, *, max_side: int = MAX_SIDE, quality: int = QUALITY) -> tuple[bytes, str]:
    """把过大的参考图压到 max_side 以内，返回 (数据, 后缀)。

    只在「PIL 可用 + 确实需要压」时动手，任何异常都返回原数据，绝不因为压缩失败阻断出图。
    """
    if not PIL_AVAILABLE or not data:
        return data, ""
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception:  # noqa: BLE001
        return data, ""

    width, height = image.size
    too_big_pixels = max(width, height) > max_side
    too_big_bytes = len(data) > SIZE_THRESHOLD
    if not too_big_pixels and not too_big_bytes:
        return data, ""

    if too_big_pixels:
        ratio = max_side / float(max(width, height))
        image = image.resize((max(1, int(width * ratio)), max(1, int(height * ratio))), Image.LANCZOS)

    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality, optimize=True)
    result = buffer.getvalue()
    if not result or len(result) >= len(data):
        return data, ""
    return result, ".jpg"

"""Small, single-frame visual evidence files for APP execution reports."""
import logging
import os
from typing import Optional

from PIL import Image

logger = logging.getLogger(__name__)

# A final-state image is evidence, not a screen recording.  Constraining both
# dimensions and the palette keeps batch reports inexpensive to retain.
MAX_EVIDENCE_SIZE = (540, 960)
GIF_COLORS = 128


def compress_screenshot_to_gif(screenshot_path: str) -> Optional[str]:
    """Create an optimized GIF preview without removing the source screenshot."""
    if not screenshot_path or not os.path.isfile(screenshot_path):
        return None

    gif_path = os.path.splitext(screenshot_path)[0] + '.gif'
    try:
        with Image.open(screenshot_path) as source:
            image = source.convert('RGB')
            image.thumbnail(MAX_EVIDENCE_SIZE, Image.Resampling.LANCZOS)
            try:
                palette_image = image.quantize(colors=GIF_COLORS, method=Image.Quantize.MEDIANCUT)
            except AttributeError:
                palette_image = image.convert('P', palette=Image.ADAPTIVE, colors=GIF_COLORS)
            palette_image.save(gif_path, format='GIF', optimize=True)
        return gif_path
    except Exception:
        if os.path.exists(gif_path):
            try:
                os.remove(gif_path)
            except OSError:
                logger.warning('清理损坏的 APP 截图预览失败: %s', gif_path)
        logger.exception('压缩 APP 最终截图为 GIF 失败: %s', screenshot_path)
        return screenshot_path

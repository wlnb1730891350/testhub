"""Compact GIF helpers shared by browser and Windows UI execution reports."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageSequence


MAX_GIF_FRAME_SIZE = (960, 720)
MAX_GIF_FRAMES = 24
GIF_COLORS = 128
_RESAMPLING = getattr(getattr(Image, 'Resampling', Image), 'LANCZOS')


def _sample_indexes(total: int) -> list[int]:
    if total <= MAX_GIF_FRAMES:
        return list(range(total))
    return sorted({round(index * (total - 1) / (MAX_GIF_FRAMES - 1)) for index in range(MAX_GIF_FRAMES)})


def _prepare_frames(frames: list[Image.Image]) -> list[Image.Image]:
    resized: list[Image.Image] = []
    for frame in frames:
        image = frame.convert('RGB')
        image.thumbnail(MAX_GIF_FRAME_SIZE, _RESAMPLING)
        resized.append(image)

    if not resized:
        return []

    canvas_size = (
        max(frame.width for frame in resized),
        max(frame.height for frame in resized),
    )
    prepared: list[Image.Image] = []
    for frame in resized:
        canvas = Image.new('RGB', canvas_size, (18, 20, 24))
        canvas.paste(frame, (0, 0))
        prepared.append(canvas.quantize(colors=GIF_COLORS, method=Image.Quantize.MEDIANCUT))
    return prepared


def save_compact_gif(frames: Iterable[Image.Image], output_path: str | Path, duration: int = 900) -> bool:
    """Save a replay GIF with bounded resolution, palette and frame count."""
    source_frames = list(frames)
    indexes = _sample_indexes(len(source_frames))
    selected_frames = [source_frames[index] for index in indexes]
    prepared_frames = _prepare_frames(selected_frames)
    if not prepared_frames:
        return False

    total_duration = max(20, int(duration)) * len(source_frames)
    frame_duration = max(20, round(total_duration / len(prepared_frames)))
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    prepared_frames[0].save(
        output,
        format='GIF',
        save_all=True,
        append_images=prepared_frames[1:],
        duration=frame_duration,
        loop=0,
        disposal=2,
        optimize=True,
    )
    return True


def compress_gif_in_place(path: str | Path) -> bool:
    """Replace an existing GIF only when the compact version is smaller."""
    original = Path(path)
    if not original.is_file():
        return False

    try:
        with Image.open(original) as source:
            frames = [frame.copy() for frame in ImageSequence.Iterator(source)]
            durations = [int(frame.info.get('duration', 100)) for frame in ImageSequence.Iterator(source)]
        if not frames:
            return False

        temporary = original.with_name(f'{original.stem}.compact.gif')
        average_duration = max(20, round(sum(durations or [100]) / len(frames)))
        if not save_compact_gif(frames, temporary, duration=average_duration):
            return False
        if temporary.stat().st_size < original.stat().st_size:
            os.replace(temporary, original)
            return True
        temporary.unlink(missing_ok=True)
    except Exception:
        return False
    return False

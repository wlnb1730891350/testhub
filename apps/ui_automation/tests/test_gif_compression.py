from PIL import Image, ImageSequence

from apps.ui_automation.gif_utils import MAX_GIF_FRAMES, MAX_GIF_FRAME_SIZE, save_compact_gif


def test_save_compact_gif_bounds_replay_dimensions_palette_and_frames(tmp_path):
    frames = [
        Image.new('RGB', (1920, 1080), (index * 7 % 255, 80, 160))
        for index in range(30)
    ]
    output = tmp_path / 'replay.gif'

    assert save_compact_gif(frames, output, duration=100)

    with Image.open(output) as gif:
        stored_frames = [frame.copy() for frame in ImageSequence.Iterator(gif)]
    assert len(stored_frames) == MAX_GIF_FRAMES
    assert stored_frames[0].width <= MAX_GIF_FRAME_SIZE[0]
    assert stored_frames[0].height <= MAX_GIF_FRAME_SIZE[1]
    assert stored_frames[0].mode == 'P'

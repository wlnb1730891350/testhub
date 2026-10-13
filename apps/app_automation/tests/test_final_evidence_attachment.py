# -*- coding: utf-8 -*-
import os
import tempfile

from PIL import Image

from apps.app_automation.tests.test_app_flow import _attach_final_evidence


def test_final_evidence_attaches_lossless_png_and_preview_gif():
    with tempfile.TemporaryDirectory() as directory:
        screenshot_path = os.path.join(directory, 'final_state.png')
        Image.new('RGB', (1080, 1920), '#2f4f4f').save(screenshot_path)

        preview_path = _attach_final_evidence(screenshot_path)

        assert os.path.getsize(screenshot_path) > 0
        assert preview_path.endswith('.gif')
        assert os.path.getsize(preview_path) > 0

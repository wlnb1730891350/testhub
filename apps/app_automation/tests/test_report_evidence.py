# -*- coding: utf-8 -*-
import os
import tempfile

from django.test import SimpleTestCase
from PIL import Image

from apps.app_automation.utils.report_evidence import compress_screenshot_to_gif


class ReportEvidenceTests(SimpleTestCase):
    def test_final_screenshot_is_preserved_when_creating_a_single_frame_gif(self):
        with tempfile.TemporaryDirectory() as directory:
            screenshot_path = os.path.join(directory, 'final_state.png')
            Image.new('RGB', (1080, 1920), '#2f4f4f').save(screenshot_path)

            gif_path = compress_screenshot_to_gif(screenshot_path)

            self.assertTrue(gif_path.endswith('.gif'))
            self.assertTrue(os.path.isfile(gif_path))
            self.assertTrue(os.path.isfile(screenshot_path))
            with Image.open(gif_path) as evidence:
                self.assertEqual(evidence.format, 'GIF')
                self.assertLessEqual(evidence.width, 540)
                self.assertLessEqual(evidence.height, 960)
                self.assertEqual(getattr(evidence, 'n_frames', 1), 1)

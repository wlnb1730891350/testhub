# -*- coding: utf-8 -*-
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.app_automation.runners.uiautomator2_flow_runner import Uiautomator2FlowRunner
from apps.app_automation.services.execution_engine import flow_requires_airtest


class FakeSelector:
    def __init__(self):
        self.clicked = 0
        self.values = []

    def exists(self, timeout=0):
        return True

    def click(self):
        self.clicked += 1

    def long_click(self, duration=1):
        self.clicked += 1


class FakeDevice:
    def __init__(self):
        self.selectors = []
        self.keys = []

    def __call__(self, **kwargs):
        selector = FakeSelector()
        selector.kwargs = kwargs
        self.selectors.append(selector)
        return selector

    def xpath(self, value):
        return self(xpath=value)

    def send_keys(self, value, clear=True):
        self.keys.append((value, clear))

    def press(self, key):
        self.keys.append(('press', key))

    def wait_idle(self, timeout=0):
        self.keys.append(('wait_idle', timeout))


class Uiautomator2FlowRunnerTests(SimpleTestCase):
    @patch('uiautomator2.connect')
    def test_click_input_and_text_assert_use_native_selectors(self, connect):
        device = FakeDevice()
        connect.return_value = device
        runner = Uiautomator2FlowRunner('emulator-5554')

        result = runner.run([
            {'type': 'click', 'config': {'selector_type': 'resource_id', 'selector': 'com.demo:id/login'}},
            {'type': 'input', 'config': {'selector_type': 'text', 'selector': '账号', 'value': 'tester', 'send_enter': True}},
            {'type': 'assert', 'config': {'assert_type': 'text', 'expected': '登录成功'}},
        ], runtime={'stop_on_error': True})

        self.assertEqual(result['passed'], 3)
        self.assertEqual(device.selectors[0].kwargs, {'resourceId': 'com.demo:id/login'})
        self.assertIn(('tester', True), device.keys)
        self.assertIn(('press', 'enter'), device.keys)
        self.assertEqual(device.selectors[-1].kwargs, {'textContains': '登录成功'})

    def test_image_flow_stays_on_airtest_compatibility_path(self):
        self.assertTrue(flow_requires_airtest([
            {'type': 'click', 'config': {'selector_type': 'image', 'selector': 'login.png'}},
        ]))
        self.assertFalse(flow_requires_airtest([
            {'type': 'click', 'config': {'selector_type': 'resource_id', 'selector': 'com.demo:id/login'}},
        ]))

    @patch('uiautomator2.connect')
    def test_optional_click_does_not_fail_when_popup_is_absent(self, connect):
        device = FakeDevice()
        connect.return_value = device
        runner = Uiautomator2FlowRunner('emulator-5554')

        absent = FakeSelector()
        absent.exists = lambda timeout=0: False
        with patch.object(runner, '_find', return_value=absent):
            result = runner.run([
                {'type': 'click_if_present', 'config': {'selector_type': 'resource_id', 'selector': 'com.demo:id/cancel'}},
            ], runtime={'stop_on_error': True})

        self.assertEqual(result['passed'], 1)
        self.assertEqual(absent.clicked, 0)

    @patch('apps.app_automation.runners.uiautomator2_flow_runner.time.sleep')
    @patch('uiautomator2.connect')
    def test_final_evidence_waits_for_the_ui_to_settle(self, connect, sleep):
        device = FakeDevice()
        connect.return_value = device
        runner = Uiautomator2FlowRunner('emulator-5554')

        with patch.object(runner, '_capture_screenshot', return_value='final.png'), patch(
            'apps.app_automation.runners.uiautomator2_flow_runner.compress_screenshot_to_gif',
            return_value='final.gif',
        ):
            evidence = runner.capture_final_evidence()

        self.assertEqual(evidence, 'final.gif')
        self.assertIn(('wait_idle', 3), device.keys)
        sleep.assert_called_once_with(1.5)

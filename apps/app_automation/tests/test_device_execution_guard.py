from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.app_automation.managers.device_manager import DeviceManager


class DeviceExecutionGuardTests(SimpleTestCase):
    def test_recovery_closes_lock_screen_and_notification_overlays_before_run(self):
        manager = DeviceManager(adb_path='adb')
        success = SimpleNamespace(returncode=0, stdout='', stderr='')

        with patch.object(manager, '_run_adb', return_value=(success, '')) as run_adb:
            recovered = manager._recover_execution_surface('device-1')

        self.assertEqual(recovered, ['唤醒屏幕', '尝试解锁', '关闭系统遮罩', '回到桌面'])
        self.assertEqual(
            [call.args[0][-3:] for call in run_adb.call_args_list],
            [
                ['input', 'keyevent', '224'],
                ['input', 'swipe', '608', '2110', '608', '520', '200'][-3:],
                ['input', 'keyevent', '4'],
                ['input', 'keyevent', '3'],
            ],
        )

    def test_preflight_reports_manual_unlock_when_recovery_cannot_clear_secure_lock(self):
        manager = DeviceManager(adb_path='adb')
        adb = SimpleNamespace(returncode=0, stdout='Android Debug Bridge version', stderr='')
        device = SimpleNamespace(returncode=0, stdout='device\n', stderr='')
        locked_window = SimpleNamespace(returncode=0, stdout='isKeyguardShowing=true\n', stderr='')

        with patch.object(manager, '_run_adb', side_effect=[
            (adb, ''), (device, ''),
            (SimpleNamespace(returncode=0, stdout='', stderr=''), ''),
            (SimpleNamespace(returncode=0, stdout='', stderr=''), ''),
            (SimpleNamespace(returncode=0, stdout='', stderr=''), ''),
            (SimpleNamespace(returncode=0, stdout='', stderr=''), ''),
            (locked_window, ''),
        ]):
            result = manager.preflight('device-1')

        self.assertFalse(result['ready'])
        self.assertEqual(result['checks'][-1]['key'], 'execution_surface')
        self.assertIn('仍处于锁屏状态', result['checks'][-1]['message'])

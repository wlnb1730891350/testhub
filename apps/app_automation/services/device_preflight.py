"""执行前设备与用例预检服务。"""
import logging

from ..managers.device_manager import DeviceManager

logger = logging.getLogger(__name__)


def get_adb_path():
    """读取当前配置的 ADB 路径，配置缺失时回退到系统 PATH。"""
    try:
        from ..models import AppTestConfig
        config = AppTestConfig.objects.first()
        return config.adb_path if config and config.adb_path else 'adb'
    except Exception as exc:
        logger.warning('读取 ADB 配置失败，使用默认路径: %s', exc)
        return 'adb'


def get_flow_steps(test_case):
    """兼容历史用例的 list / {steps: []} 两种 UI Flow 格式。"""
    ui_flow = test_case.ui_flow
    if isinstance(ui_flow, list):
        return ui_flow
    if isinstance(ui_flow, dict):
        steps = ui_flow.get('steps', [])
        return steps if isinstance(steps, list) else []
    return []


def validate_test_case(test_case):
    steps = get_flow_steps(test_case)
    if not steps:
        return False, '用例未配置可执行的 UI Flow 步骤'
    return True, ''


def resolve_package_name(test_case, override=''):
    if override:
        return override.strip()
    return test_case.app_package.package_name if test_case.app_package else ''


def preflight_device(device, package_name='', recover_environment=False):
    """执行实时 ADB 检查，并将成功读取到的设备信息回写到设备记录。"""
    result = DeviceManager(adb_path=get_adb_path()).preflight(
        device.device_id,
        package_name,
        recover_environment=recover_environment,
    )
    info = result.get('device') or {}
    if result.get('checks', []) and any(item.get('key') == 'device' and item.get('passed') for item in result['checks']):
        device.status = 'locked' if device.status == 'locked' else 'online'
        device.name = info.get('name') or device.name
        device.android_version = info.get('android_version') or device.android_version
        specs = dict(device.device_specs or {})
        if info.get('screen_size'):
            specs['screen_size'] = info['screen_size']
        device.device_specs = specs
        device.save(update_fields=['status', 'name', 'android_version', 'device_specs', 'updated_at'])
    elif device.status != 'locked':
        device.status = 'offline'
        device.save(update_fields=['status', 'updated_at'])
    return result

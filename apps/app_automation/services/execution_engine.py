"""执行引擎选择与运行器工厂。"""
import logging

logger = logging.getLogger(__name__)


IMAGE_ONLY_ACTIONS = {'image_exists_click', 'image_exists_click_chain'}
VISUAL_ASSERTIONS = {'image', 'number', 'range'}


def _iter_steps(steps):
    """递归遍历嵌套控制流与自定义组件中的步骤。"""
    if not isinstance(steps, list):
        return
    nested_fields = ('steps', 'then_steps', 'else_steps', 'try_steps', 'catch_steps', 'finally_steps')
    for step in steps:
        if not isinstance(step, dict):
            continue
        yield step
        for field in nested_fields:
            yield from _iter_steps(step.get(field))


def flow_requires_airtest(steps):
    """图片模板或 OCR 步骤继续使用 Airtest，其他流程可走 UIAutomator2。"""
    for step in _iter_steps(steps):
        if str(step.get('type', '')).lower() in IMAGE_ONLY_ACTIONS:
            return True
        config = step.get('config') if isinstance(step.get('config'), dict) else step
        if config.get('assert_type') in VISUAL_ASSERTIONS:
            return True
        for key, value in config.items():
            if key.endswith('selector_type') and value == 'image':
                return True
    return False


def get_configured_engine():
    try:
        from ..models import AppTestConfig
        config = AppTestConfig.objects.first()
        return config.execution_engine if config else 'auto'
    except Exception as exc:
        logger.warning('读取 APP 执行引擎配置失败: %s', exc)
        return 'auto'


def resolve_execution_engine(test_case):
    configured_engine = get_configured_engine()
    if configured_engine in {'uiautomator2', 'airtest'}:
        return configured_engine
    if isinstance(test_case.ui_flow, list):
        ui_flow = test_case.ui_flow
    elif isinstance(test_case.ui_flow, dict):
        ui_flow = test_case.ui_flow.get('steps', [])
    else:
        ui_flow = []
    return 'airtest' if flow_requires_airtest(ui_flow) else 'uiautomator2'


def create_flow_runner(engine, device_id, username=None):
    if engine == 'uiautomator2':
        from ..runners.uiautomator2_flow_runner import Uiautomator2FlowRunner
        return Uiautomator2FlowRunner(device_id=device_id, username=username)
    if engine == 'airtest':
        from ..runners.ui_flow_runner import UiFlowRunner
        return UiFlowRunner(username=username)
    raise ValueError(f'不支持的 APP 执行引擎: {engine}')

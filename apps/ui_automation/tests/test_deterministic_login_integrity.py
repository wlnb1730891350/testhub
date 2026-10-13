import asyncio
from unittest.mock import patch

from apps.ui_automation.ai_base import BaseBrowserAgent


class FakeLocator:
    def __init__(self, selector):
        self.selector = selector
        self.first = self

    async def click(self, timeout=5000, force=True):
        return None


class FakePage:
    def __init__(self):
        self.url = 'https://test6-web.nn.com'

    async def goto(self, *args, **kwargs):
        return None

    async def wait_for_load_state(self, *args, **kwargs):
        return None

    async def wait_for_timeout(self, *args, **kwargs):
        return None

    async def screenshot(self, *args, **kwargs):
        return b'fakepng'

    def locator(self, selector):
        return FakeLocator(selector)

    async def evaluate(self, script, arg=None):
        script = str(script)
        if 'closeSelectors' in script:
            return 'no popup'
        if 'hasLoginInput' in script:
            return {'opened': True, 'via': 'already'}
        if 'phoneInput.focus(); phoneInput.value = phone;' in script:
            return {'ok': True, 'phonePlaceholder': '手机号', 'codePlaceholder': '验证码', 'scopedToDialog': True}
        if 'input[type=checkbox]' in script:
            return {'ok': True, 'via': 'checkbox'}
        if 'login button not found' in script:
            return {'ok': True, 'clicked': '登录'}
        raise AssertionError(f'unexpected evaluate script: {script[:120]}')


class FakeContext:
    async def new_page(self):
        return FakePage()

    async def close(self):
        return None


class FakeBrowser:
    async def new_context(self, **kwargs):
        return FakeContext()

    async def close(self):
        return None


class FakeChromium:
    async def launch(self, **kwargs):
        return FakeBrowser()


class FakePlaywrightManager:
    def __init__(self):
        self.chromium = FakeChromium()

    async def start(self):
        return self

    async def stop(self):
        return None


async def _fake_find_dialog(page):
    return {'selector': '.login-dialog'}


async def _run_case(assertion_passed: bool):
    async def fake_evaluate_login_success(page):
        return {
            'passed': assertion_passed,
            'reason': '' if assertion_passed else 'still on login form',
            'evidence': {'marker': 'ok' if assertion_passed else 'fail'},
        }

    events = []
    planned_tasks = [
        {'id': 1, 'description': '访问 https://test6-web.nn.com/', 'status': 'pending'},
        {'id': 2, 'description': '点击登录入口打开登录弹窗', 'status': 'pending'},
        {'id': 3, 'description': '输入手机号 17680942927', 'status': 'pending'},
        {'id': 4, 'description': '输入验证码 8888', 'status': 'pending'},
        {'id': 5, 'description': '勾选同意协议', 'status': 'pending'},
        {'id': 6, 'description': '点击登录按钮', 'status': 'pending'},
        {'id': 7, 'description': '提交登录操作', 'status': 'pending'},
        {'id': 8, 'description': '完成登录', 'status': 'pending'},
    ]

    async def callback(payload):
        events.append(payload)
        if payload.get('task_id'):
            for task in planned_tasks:
                if task['id'] == payload['task_id']:
                    task['status'] = payload['status']

    agent = object.__new__(BaseBrowserAgent)
    agent.enable_gif = False

    with (
        patch('playwright.async_api.async_playwright', lambda: FakePlaywrightManager()),
        patch('apps.ui_automation.ai_base._find_best_login_dialog', _fake_find_dialog),
        patch('apps.ui_automation.ai_base.evaluate_login_success', fake_evaluate_login_success),
    ):
        try:
            result = await agent._run_nn_login_deterministic(
                '访问 https://test6-web.nn.com/，输入手机号 17680942927，输入验证码 8888，完成登录',
                planned_tasks=planned_tasks,
                callback=callback,
            )
            if not assertion_passed:
                raise AssertionError('expected RuntimeError on failed assertion path')
            return result, events
        except RuntimeError as exc:
            if assertion_passed:
                raise
            if '登录断言失败' not in str(exc):
                raise
            return False, events


def _last_status(events, task_id):
    matches = [e.get('status') for e in events if e.get('task_id') == task_id]
    return matches[-1] if matches else None


def test_deterministic_login_submit_not_completed_before_success():
    result, events = asyncio.run(_run_case(True))
    assert result is True
    assert _last_status(events, 6) == 'completed'
    assert _last_status(events, 7) is None
    assert _last_status(events, 8) == 'completed'


def test_deterministic_login_final_task_failed_when_assertion_fails():
    result, events = asyncio.run(_run_case(False))
    assert result is False
    assert _last_status(events, 6) == 'completed'
    assert _last_status(events, 7) is None
    assert _last_status(events, 8) == 'failed'

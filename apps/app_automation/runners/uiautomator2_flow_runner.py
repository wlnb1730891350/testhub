# -*- coding: utf-8 -*-
"""基于 openatx/uiautomator2 的 Android 原生 UI Flow 执行器。"""
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

from django.conf import settings

logger = logging.getLogger(__name__)


TEEN_MODE_DIALOG_MARKERS = (
    '体验青少年模式',
    '年龄限制',
    '控制时长',
    '健康守护',
    '呵护儿童',
)


class Uiautomator2FlowRunner:
    """使用 Android 原生控件树定位，替代坐标与图片模板的主执行路径。"""

    def __init__(self, device_id: str, username: Optional[str] = None):
        try:
            import uiautomator2 as u2
        except ImportError as exc:
            raise RuntimeError('未安装 uiautomator2，请执行依赖安装后重试') from exc
        self.device = u2.connect(device_id)
        self.device_id = device_id
        self.screenshots_dir = os.path.join(
            settings.MEDIA_ROOT, 'app-automation', 'screenshots', username or 'unknown'
        )
        os.makedirs(self.screenshots_dir, exist_ok=True)
        self.context = {'global': {}, 'local': {}, 'outputs': {}}
        self.runtime = {'retry_interval': 0.5}

    def start_app(self, package_name: str):
        # 每条用例从冷启动的已登录首页开始，避免上一条用例遗留页面状态。
        self._prepare_device_for_run()
        self.device.app_start(package_name, stop=True, use_monkey=True)
        # 青少年模式提示会遮住首页。它属于应用的已知一次性提示，不应让
        # 任何业务用例误判为首页加载失败。
        self._dismiss_known_blocking_dialogs(timeout=1.5)

    def stop_app(self, package_name: str):
        self.device.app_stop(package_name)

    def finish_run(self) -> None:
        """Restore the test device's normal screen-off policy after execution."""
        self._run_device_shell('svc power stayon false')

    def run(self, ui_flow: List[Dict[str, Any]], variables=None, runtime=None, progress_callback=None):
        if not isinstance(ui_flow, list):
            raise ValueError('ui_flow 必须是列表')
        self._init_context(variables, runtime)
        passed, failed = 0, 0
        for index, raw_step in enumerate(ui_flow, 1):
            step_name = raw_step.get('name', raw_step.get('type', 'unknown')) if isinstance(raw_step, dict) else 'unknown'
            if progress_callback:
                progress_callback(index, len(ui_flow), step_name, 'running')
            try:
                self._execute_step(raw_step)
                passed += 1
                if progress_callback:
                    progress_callback(index, len(ui_flow), step_name, 'passed')
            except Exception:
                failed += 1
                if progress_callback:
                    progress_callback(index, len(ui_flow), step_name, 'failed')
                if self.runtime.get('stop_on_error'):
                    raise
        return {'total': len(ui_flow), 'passed': passed, 'failed': failed, 'outputs': self.context['outputs']}

    def _init_context(self, variables, runtime):
        self.context = {'global': {}, 'local': {}, 'outputs': {}}
        if isinstance(variables, list):
            for item in variables:
                if isinstance(item, dict) and item.get('name'):
                    self.context.get(item.get('scope', 'local'), self.context['local'])[item['name']] = item.get('value')
        if isinstance(runtime, dict):
            self.runtime.update(runtime)

    def _render(self, value):
        if not isinstance(value, str):
            if isinstance(value, dict):
                return {key: self._render(item) for key, item in value.items()}
            if isinstance(value, list):
                return [self._render(item) for item in value]
            return value

        def replace(match):
            name = (match.group(1) or match.group(2)).strip()
            for scope in ('local', 'global', 'outputs'):
                if name in self.context[scope]:
                    return str(self.context[scope][name])
            return ''
        return re.sub(r'\{\{\s*([^}]+)\s*\}\}|\$\{\s*([^}]+)\s*\}', replace, value)

    def _normalise_step(self, raw_step):
        if not isinstance(raw_step, dict):
            raise ValueError('步骤必须是对象')
        step = self._render(dict(raw_step))
        if isinstance(step.get('config'), dict):
            for key, value in step['config'].items():
                step.setdefault(key, value)
        return step

    @staticmethod
    def _parse_coordinates(value):
        if isinstance(value, str):
            value = [item.strip() for item in value.split(',')]
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            return int(value[0]), int(value[1])
        raise ValueError(f'坐标格式错误: {value}')

    def _selector_kwargs(self, selector_type, selector):
        if isinstance(selector, dict):
            return selector
        if isinstance(selector, str) and selector.strip().startswith('{'):
            try:
                parsed = json.loads(selector)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
        selector_type = (selector_type or 'text').strip()
        mapping = {
            'text': 'text', 'text_contains': 'textContains', 'resource_id': 'resourceId',
            'resourceId': 'resourceId', 'description': 'description', 'class_name': 'className',
            'className': 'className', 'text_regex': 'textMatches',
        }
        if selector_type == 'native':
            if not isinstance(selector, str) or '=' not in selector:
                raise ValueError('native 定位格式为 key=value，例如 resourceId=com.demo:id/login')
            key, value = selector.split('=', 1)
            return self._selector_kwargs(key.strip(), value.strip())
        if selector_type == 'xpath':
            return {'xpath': selector}
        if selector_type == 'pos':
            return {'pos': self._parse_coordinates(selector)}
        if selector_type in {'image', 'region'}:
            raise ValueError(f'{selector_type} 定位需要 Airtest 引擎，请在设置中选择 Airtest 或使用原生定位')
        key = mapping.get(selector_type)
        if not key or not selector:
            raise ValueError(f'无效的原生定位: {selector_type}={selector}')
        return {key: selector}

    def _find(self, step):
        kwargs = self._selector_kwargs(step.get('selector_type'), step.get('selector'))
        if 'pos' in kwargs:
            return kwargs['pos']
        if 'xpath' in kwargs:
            return self.device.xpath(kwargs['xpath'])
        return self.device(**kwargs)

    def _exists(self, target, timeout=0):
        if isinstance(target, tuple):
            return True
        return bool(target.exists(timeout=float(timeout or 0)))

    def _require_target(self, step, timeout=None):
        target = self._find(step)
        effective_timeout = step.get('timeout', 5) if timeout is None else timeout
        if not self._exists(target, effective_timeout):
            raise AssertionError(f"未找到元素: {step.get('selector_type', 'text')}={step.get('selector', '')}")
        return target

    def _tap(self, target):
        if isinstance(target, tuple):
            self.device.click(*target)
        else:
            target.click()

    def _execute_step(self, raw_step):
        step = self._normalise_step(raw_step)
        action = str(step.get('type', '')).lower()
        self._dismiss_known_blocking_dialogs()
        retry_times = int(step.get('retry_times', 0) or 0)
        last_error = None
        for attempt in range(retry_times + 1):
            try:
                return self._dispatch(step, action)
            except Exception as exc:
                last_error = exc
                if attempt < retry_times:
                    time.sleep(float(step.get('retry_interval', self.runtime['retry_interval'])))
        raise last_error

    def _prepare_device_for_run(self) -> None:
        """Wake a test device and clear its lock-screen/notification overlay."""
        try:
            self._run_device_shell('svc power stayon true')
            self._run_device_shell('input keyevent 224')
            time.sleep(0.2)
            self.device.screen_on()
            width, height = self.device.window_size()
            self._run_device_shell(
                f'input swipe {width // 2} {int(height * 0.84)} '
                f'{width // 2} {int(height * 0.24)} 200'
            )
            self.device.press('back')
            self.device.press('home')
            time.sleep(0.35)
        except Exception as exc:
            logger.warning('准备 APP 自动化设备状态失败: %s', exc)

        if self._exists(self.device(textContains='上滑解锁')):
            raise RuntimeError('测试设备仍处于锁屏状态，请先解除密码或生物识别锁屏后再执行')

    def _run_device_shell(self, command: str) -> None:
        try:
            self.device.shell(command)
        except Exception as exc:
            logger.debug('执行设备命令失败: %s, %s', command, exc)

    def _dismiss_known_blocking_dialogs(self, timeout=0) -> bool:
        """Dismiss the verified teen-mode modal without touching unrelated dialogs."""
        deadline = time.monotonic() + max(float(timeout or 0), 0)
        while True:
            acknowledge = self.device(text='我知道了')
            has_marker = any(
                self._exists(self.device(textContains=marker))
                for marker in TEEN_MODE_DIALOG_MARKERS
            )
            if has_marker and self._exists(acknowledge):
                self._tap(acknowledge)
                logger.info('已关闭青少年模式提示弹窗')
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.1)

    def _dispatch(self, step, action):
        if action in {'click', 'touch'}:
            self._tap(self._require_target(step))
        elif action == 'click_if_present':
            target = self._find(step)
            if self._exists(target, step.get('timeout', 0.5)):
                self._tap(target)
        elif action == 'double_click':
            target = self._require_target(step)
            self._tap(target)
            time.sleep(0.12)
            self._tap(target)
        elif action == 'long_press':
            target = self._require_target(step)
            if isinstance(target, tuple):
                self.device.long_click(*target, duration=float(step.get('duration', 1)))
            else:
                target.long_click(duration=float(step.get('duration', 1)))
        elif action == 'input':
            target = self._require_target(step)
            self._tap(target)
            self.device.send_keys(str(step.get('value', '')), clear=bool(step.get('clear', True)))
            if step.get('send_enter'):
                self.device.press('enter')
        elif action in {'sleep', 'wait'}:
            if step.get('selector'):
                self._require_target(step, timeout=step.get('timeout', step.get('duration', 3)))
            else:
                time.sleep(float(step.get('duration', step.get('timeout', 1))))
        elif action == 'swipe':
            start = self._parse_coordinates(step.get('start'))
            end = self._parse_coordinates(step.get('end'))
            self.device.swipe(*start, *end, duration=float(step.get('duration', 0.5)))
        elif action == 'drag':
            start = self._parse_coordinates(step.get('start_selector') or step.get('start'))
            end = self._parse_coordinates(step.get('end_selector') or step.get('end'))
            self.device.swipe(*start, *end, duration=float(step.get('duration', 0.8)))
        elif action == 'swipe_to':
            self._swipe_to(step)
        elif action == 'screenshot':
            self._capture_screenshot(step.get('name', 'screenshot'))
        elif action == 'assert':
            self._assert(step)
        elif action == 'set_variable':
            self.context.get(step.get('scope', 'local'), self.context['local'])[step.get('name')] = step.get('value')
        elif action == 'unset_variable':
            self.context.get(step.get('scope', 'local'), self.context['local']).pop(step.get('name'), None)
        elif action == 'sequence':
            for child in step.get('steps', []):
                self._execute_step(child)
        elif action == 'if':
            left, right = self._render(step.get('left', '')), self._render(step.get('right', ''))
            children = step.get('then_steps', []) if str(left) == str(right) else step.get('else_steps', [])
            for child in children:
                self._execute_step(child)
        else:
            raise ValueError(f'UIAutomator2 暂不支持步骤类型: {action or "空"}')

    def _swipe_to(self, step):
        target = self._find({'selector_type': step.get('target_selector_type'), 'selector': step.get('target_selector')})
        width, height = self.device.window_size()
        direction = step.get('direction', 'up')
        movements = {
            'up': ((width // 2, int(height * .72)), (width // 2, int(height * .30))),
            'down': ((width // 2, int(height * .30)), (width // 2, int(height * .72))),
            'left': ((int(width * .72), height // 2), (int(width * .30), height // 2)),
            'right': ((int(width * .30), height // 2), (int(width * .72), height // 2)),
        }
        start, end = movements.get(direction, movements['up'])
        for _ in range(int(step.get('max_swipes', 5))):
            if self._exists(target):
                return
            self.device.swipe(*start, *end, duration=0.35)
            time.sleep(float(step.get('interval', 0.4)))
        raise AssertionError('滑动后仍未找到目标元素')

    def _assert(self, step):
        assert_type = step.get('assert_type', 'exists')
        timeout = float(step.get('timeout', 0))
        if assert_type == 'text':
            expected = str(step.get('expected', step.get('selector', '')))
            target = self.device(text=expected) if step.get('match_mode') == 'exact' else self.device(textContains=expected)
            if not self._exists(target, timeout):
                raise AssertionError(f'未找到期望文本: {expected}')
            return
        if assert_type == 'regex':
            pattern = str(step.get('expected', ''))
            if not self._exists(self.device(textMatches=pattern), timeout):
                raise AssertionError(f'未找到匹配文本: {pattern}')
            return
        if assert_type == 'exists':
            actual = self._exists(self._find(step), timeout)
            if bool(step.get('expected_exists', True)) != actual:
                raise AssertionError(f'元素存在性断言失败，实际存在={actual}')
            return
        raise ValueError(f'UIAutomator2 暂不支持断言类型: {assert_type}')

    def _capture_screenshot(self, name):
        safe_name = re.sub(r'[^0-9a-zA-Z_-]+', '_', str(name)) or 'screenshot'
        path = os.path.join(self.screenshots_dir, f'{safe_name}_{int(time.time() * 1000)}.png')
        self.device.screenshot(path)
        return path

    def capture_final_evidence(self):
        """Capture the settled final screen as the source report evidence."""
        self._dismiss_known_blocking_dialogs()
        try:
            self.device.wait_idle(timeout=3)
        except (AttributeError, TypeError):
            # Older uiautomator2 clients do not provide wait_idle.
            pass
        # A completed selector assertion can precede the final layout draw.
        # Keep one small settling window instead of recording every transition.
        time.sleep(1.5)
        return self._capture_screenshot('final_state')

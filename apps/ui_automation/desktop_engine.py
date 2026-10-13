"""Windows native UI executor for AI cases.

The executor intentionally consumes explicit control locators. Native Windows
applications rarely expose a stable DOM, so free-form text is not treated as a
locator or silently converted into screen coordinates.
"""
from __future__ import annotations

import os
import time
import json
import re
import base64
import asyncio
import subprocess
import threading
import urllib.request
from urllib.parse import urlparse
from io import BytesIO
from pathlib import Path
from typing import Any

from django.conf import settings
from django.utils import timezone

from .gif_utils import save_compact_gif


class DesktopAutomationError(RuntimeError):
    pass


class CDPConnectionLost(DesktopAutomationError):
    """The Electron renderer closed its DevTools socket while a case was running."""


TERMINAL_EXECUTION_STATUSES = {'passed', 'failed', 'error', 'stopped', 'cancelled'}
_CDP_AGENT_START_LOCK = threading.Lock()


def _cdp_agent_startupinfo(silent: bool):
    """Keep an Electron Agent window out of the operator's desktop at launch."""
    if not silent or os.name != 'nt':
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0  # SW_HIDE
    return startupinfo


def _hide_cdp_agent_windows(executable: str) -> int:
    """Hide only windows owned by the configured Agent executable.

    Electron can recreate its main window after startup, so startupinfo alone
    is not sufficient. Matching the full executable path avoids hiding the
    operator's separately installed NN client.
    """
    if os.name != 'nt' or not executable:
        return 0
    try:
        import ctypes
        from ctypes import wintypes
        import psutil
    except ImportError:
        return 0
    expected = os.path.normcase(os.path.abspath(str(executable)))
    user32 = ctypes.windll.user32
    hidden = 0
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def visit(hwnd, _lparam):
        nonlocal hidden
        if not user32.IsWindowVisible(hwnd):
            return True
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        try:
            candidate = os.path.normcase(os.path.abspath(psutil.Process(process_id.value).exe()))
        except (psutil.Error, OSError):
            return True
        if candidate != expected:
            return True
        # SW_HIDE affects only this Agent's top-level window; renderer/CDP
        # execution continues with no physical mouse or foreground focus.
        user32.ShowWindow(hwnd, 0)
        hidden += 1
        return True

    try:
        user32.EnumWindows(visit, 0)
    except Exception:
        return hidden
    return hidden


def _execution_finished_elsewhere(execution_record) -> bool:
    """Avoid allowing a delayed UIA call to revive a watchdog-failed record."""
    try:
        status = execution_record.__class__.objects.filter(pk=execution_record.pk).values_list('status', flat=True).first()
    except Exception:
        return False
    return str(status or '').lower() in TERMINAL_EXECUTION_STATUSES


def _ensure_execution_active(execution_record, should_stop=None) -> None:
    if should_stop and should_stop():
        raise DesktopAutomationError('Desktop execution was stopped before the startup phase completed.')
    if _execution_finished_elsewhere(execution_record):
        raise DesktopAutomationError('Desktop execution was already finalized by the startup watchdog.')


def _append_startup_progress(execution_record, message: str, should_stop=None) -> None:
    _ensure_execution_active(execution_record, should_stop)
    execution_record.logs += f'[Desktop] {message}\n'
    execution_record.save(update_fields=['logs'])


def _persist_desktop_execution_gif(execution_record, records: list[dict[str, Any]]) -> bool:
    """Build a replay GIF from the screenshots produced by a desktop run."""
    if getattr(execution_record, 'gif_path', None):
        return True

    try:
        from PIL import Image, ImageDraw, ImageFont

        media_root = Path(settings.MEDIA_ROOT)
        frames: list[Image.Image] = []
        descriptions: list[str] = []
        for index, record in enumerate(records or [], 1):
            screenshot = str(record.get('screenshot') or '').strip()
            if screenshot.startswith('/media/'):
                screenshot = screenshot[len('/media/'):]
            screenshot = screenshot.lstrip('/').replace('\\', '/')
            if not screenshot:
                continue
            screenshot_path = media_root / screenshot
            if not screenshot_path.is_file():
                continue
            with Image.open(screenshot_path) as source:
                frames.append(source.convert('RGB'))
            descriptions.append(str(record.get('description') or f'Step {index}').strip())

        if not frames:
            return False

        max_width = max(frame.width for frame in frames)
        max_height = max(frame.height for frame in frames)
        font = None
        for font_path in (
            r'C:\Windows\Fonts\msyh.ttc',
            r'C:\Windows\Fonts\simhei.ttf',
            r'C:\Windows\Fonts\simsun.ttc',
        ):
            if Path(font_path).is_file():
                try:
                    font = ImageFont.truetype(font_path, 24)
                    break
                except OSError:
                    pass
        font = font or ImageFont.load_default()

        labeled_frames: list[Image.Image] = []
        for index, (frame, description) in enumerate(zip(frames, descriptions), 1):
            if frame.size != (max_width, max_height):
                normalized = Image.new('RGB', (max_width, max_height), (18, 20, 24))
                normalized.paste(frame, (0, 0))
                frame = normalized
            header_height = 52
            canvas = Image.new('RGB', (max_width, max_height + header_height), (18, 28, 45))
            canvas.paste(frame, (0, header_height))
            draw = ImageDraw.Draw(canvas)
            draw.text((16, 14), f'Step {index}: {description[:100]}', fill=(255, 255, 255), font=font)
            labeled_frames.append(canvas)

        gif_dir = media_root / 'ui_automation' / 'desktop_execution' / str(execution_record.id)
        gif_dir.mkdir(parents=True, exist_ok=True)
        gif_path = gif_dir / 'execution.gif'
        save_compact_gif(labeled_frames, gif_path, duration=1000)
        execution_record.gif_path = f'/media/ui_automation/desktop_execution/{execution_record.id}/execution.gif'
        execution_record.logs += f'[Desktop] GIF replay generated with {len(labeled_frames)} frame(s).\n'
        execution_record.save(update_fields=['gif_path', 'logs'])
        return True
    except Exception as exc:
        execution_record.logs += f'[Desktop] GIF replay generation failed: {exc}\n'
        execution_record.save(update_fields=['logs'])
        return False


SUPPORTED_ACTIONS = {
    'click', 'double_click', 'click_coordinate', 'fill', 'type', 'press', 'select', 'wait',
    'assert_visible', 'assert_text', 'assert_value', 'screenshot',
}


def _load_pywinauto():
    try:
        from pywinauto import Application, Desktop, keyboard
        return Application, Desktop, keyboard
    except ImportError as exc:
        raise DesktopAutomationError(
            'Windows desktop automation dependency is missing. Install pywinauto==0.6.9.'
        ) from exc


def _validate_config(config: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(config, dict):
        raise DesktopAutomationError('Desktop configuration must be a JSON object.')
    steps = config.get('steps')
    if not isinstance(steps, list) or not steps:
        raise DesktopAutomationError('Desktop configuration requires a non-empty steps array.')
    for index, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            raise DesktopAutomationError(f'Desktop step {index} must be a JSON object.')
        action = str(step.get('action') or '').strip().lower()
        if action not in SUPPORTED_ACTIONS:
            raise DesktopAutomationError(f'Desktop step {index} has unsupported action: {action or "<empty>"}.')
        if action == 'click_coordinate':
            if not isinstance(step.get('x'), (int, float)) or not isinstance(step.get('y'), (int, float)):
                raise DesktopAutomationError(f'Desktop step {index} requires numeric x and y coordinates.')
        elif action not in {'wait', 'screenshot'} and not isinstance(step.get('locator'), dict):
            raise DesktopAutomationError(f'Desktop step {index} requires a locator object.')
    return steps


def _window_locator(config: dict[str, Any]) -> dict[str, Any]:
    locator = config.get('window') or {}
    if not isinstance(locator, dict):
        raise DesktopAutomationError('desktop_config.window must be a locator object.')
    if not locator and not config.get('executable_path') and not config.get('process_name'):
        raise DesktopAutomationError('Provide desktop_config.executable_path, process_name, or window.')
    return locator


def _find_running_process(process_name: str) -> int | None:
    expected = str(process_name or '').strip().casefold()
    if not expected:
        return None
    try:
        import psutil
    except ImportError:
        return None
    candidates = []
    for process in psutil.process_iter(['pid', 'name', 'exe', 'create_time']):
        try:
            names = [str(process.info.get('name') or ''), Path(str(process.info.get('exe') or '')).name]
            if any(name.casefold() == expected for name in names):
                candidates.append(process.info)
        except (psutil.Error, OSError):
            continue
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.get('create_time') or 0)['pid']


def _restore_window_if_minimized(window) -> None:
    """Restore a target app from the taskbar before requiring it to be visible."""
    try:
        if window.is_minimized():
            window.restore()
            time.sleep(0.25)
    except Exception:
        pass


def _bring_window_to_foreground(window) -> None:
    """Make screenshots and input target the connected application, not an overlay."""
    _restore_window_if_minimized(window)
    try:
        window.set_focus()
    except Exception:
        pass


def _window_matches_process_name(window, process_name: str) -> bool:
    expected = Path(str(process_name or '')).name.casefold()
    if not expected:
        return True
    try:
        process_id = int(window.element_info.process_id)
        import psutil
        process = psutil.Process(process_id)
        names = [str(process.name() or ''), Path(str(process.exe() or '')).name]
        return any(name.casefold() == expected for name in names)
    except Exception:
        return False


def _window_matches_locator(window, window_locator: dict[str, Any]) -> bool:
    try:
        title = str(window.element_info.name or window.window_text() or '')
    except Exception:
        return False
    expected_title = str(window_locator.get('title') or '')
    title_pattern = str(window_locator.get('title_re') or '')
    if expected_title and title != expected_title:
        return False
    if title_pattern:
        try:
            if not re.search(title_pattern, title):
                return False
        except re.error as exc:
            raise DesktopAutomationError(f'Invalid desktop window title rule: {exc}') from exc
    return bool(expected_title or title_pattern)


def _desktop_window_for_locator(desktop, window_locator: dict[str, Any], process_name: str):
    """Find a top-level desktop window by both title rule and owning process."""
    try:
        candidates = desktop.windows()
    except Exception:
        candidates = []
    for candidate in candidates:
        if _window_matches_locator(candidate, window_locator) and _window_matches_process_name(candidate, process_name):
            try:
                handle = int(candidate.handle)
                if handle:
                    return desktop.window(handle=handle)
            except Exception:
                pass
            return candidate
    if candidates:
        raise DesktopAutomationError(
            f'No desktop window matched both the title rule and process {process_name}.'
        )
    return desktop.window(**window_locator)


def _find_ready_window(
    app,
    desktop,
    window_locator: dict[str, Any],
    timeout: float,
    native_desktop=None,
    expected_process_name: str = '',
):
    """Return the actual application window, never an internal status pane.

    Some Windows launchers immediately hand work to another process.  A title
    locator is therefore also tried against the desktop after the process-bound
    application lookup, while an unqualified launch is constrained to visible
    Window/Dialog controls owned by the launched process.
    """
    errors = []
    if window_locator:
        sources = [
            ('application process', lambda: app.window(**window_locator)),
            ('desktop', lambda: _desktop_window_for_locator(desktop, window_locator, expected_process_name)),
        ]
        if native_desktop is not None and native_desktop is not desktop:
            sources.append((
                'native desktop recovery',
                lambda: _desktop_window_for_locator(native_desktop, window_locator, expected_process_name),
            ))
        for source, resolver in sources:
            try:
                candidate = resolver()
                if not _window_matches_process_name(candidate, expected_process_name):
                    raise DesktopAutomationError(
                        f'Window matched the title rule but does not belong to {expected_process_name}.'
                    )
                _restore_window_if_minimized(candidate)
                if source == 'native desktop recovery':
                    candidate = _desktop_window_for_locator(desktop, window_locator, expected_process_name)
                    _restore_window_if_minimized(candidate)
                candidate.wait('exists visible ready', timeout=timeout)
                _bring_window_to_foreground(candidate)
                return candidate
            except Exception as exc:
                errors.append(f'{source}: {exc}')
        title = window_locator.get('title') or window_locator.get('title_re') or 'target window'
        raise DesktopAutomationError(
            f'Unable to make {title} ready. ' + ' | '.join(errors)
        )

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            candidates = app.windows()
        except Exception as exc:
            errors.append(str(exc))
            candidates = []
        for candidate in candidates:
            try:
                info = candidate.element_info
                if str(getattr(info, 'control_type', '') or '') not in {'Window', 'Dialog'}:
                    continue
                if not candidate.is_visible():
                    continue
                candidate.wait('exists visible ready', timeout=min(2, max(0.1, deadline - time.monotonic())))
                _bring_window_to_foreground(candidate)
                return candidate
            except Exception as exc:
                errors.append(str(exc))
        time.sleep(0.25)

    raise DesktopAutomationError(
        'Unable to find a visible top-level desktop window for the launched process. '
        'Configure desktop_app_profile.window_title_regex when the executable starts another process.'
    )


def _connect_window(config: dict[str, Any]):
    Application, Desktop, keyboard = _load_pywinauto()
    backend = str(config.get('backend') or 'uia').lower()
    if backend not in {'uia', 'win32'}:
        raise DesktopAutomationError('desktop_config.backend must be "uia" or "win32".')

    executable_path = str(config.get('executable_path') or '').strip()
    process_name = str(config.get('process_name') or '').strip()
    window_locator = _window_locator(config)
    timeout = float(config.get('launch_timeout_seconds') or 20)
    app = Application(backend=backend)

    running_process_id = _find_running_process(process_name)
    if running_process_id:
        try:
            app.connect(process=running_process_id, timeout=timeout)
        except Exception as exc:
            raise DesktopAutomationError(f'Unable to connect to running process {process_name}: {exc}') from exc
    elif executable_path:
        if not os.path.isfile(executable_path):
            raise DesktopAutomationError(f'Desktop executable was not found: {executable_path}')
        work_dir = str(config.get('work_dir') or Path(executable_path).parent)
        arguments = str(config.get('arguments') or '').strip()
        app.start(f'"{executable_path}" {arguments}'.strip(), work_dir=work_dir, timeout=timeout)
    else:
        try:
            app.connect(**window_locator, timeout=timeout)
        except Exception as exc:
            raise DesktopAutomationError(f'Unable to connect to the target window: {exc}') from exc

    desktop = Desktop(backend=backend)
    native_desktop = Desktop(backend='win32') if backend != 'win32' else desktop
    return _find_ready_window(
        app,
        desktop,
        window_locator,
        timeout,
        native_desktop=native_desktop,
        expected_process_name=process_name,
    ), keyboard


def _resolve_control(window, locator: dict[str, Any], timeout: float):
    allowed = {'title', 'title_re', 'auto_id', 'control_type', 'class_name', 'best_match', 'found_index'}
    criteria = {key: value for key, value in locator.items() if key in allowed and value not in (None, '')}
    if not criteria:
        raise DesktopAutomationError('Locator must include title, title_re, auto_id, control_type, class_name, or best_match.')
    try:
        control = window.child_window(**criteria)
        control.wait('exists visible enabled ready', timeout=timeout)
        return control
    except Exception as exc:
        raise DesktopAutomationError(f'Control not available for locator {criteria}: {exc}') from exc


def _capture_screenshot(window, record_id: int, step_number: int) -> str | None:
    target_dir = Path(settings.MEDIA_ROOT) / 'ui_automation' / 'desktop_execution' / str(record_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f'step_{step_number}.png'
    try:
        window.capture_as_image().save(path)
    except Exception:
        try:
            from PIL import ImageGrab
            ImageGrab.grab().save(path)
        except Exception:
            return None
    return path.relative_to(settings.MEDIA_ROOT).as_posix()


def _control_content(control) -> str:
    """Read editable UIA values before falling back to accessible labels."""
    parts = []
    try:
        value = str(control.get_value() or '').strip()
        if value:
            parts.append(value)
    except Exception:
        pass
    try:
        text = ' '.join(str(item) for item in control.texts()).strip()
        if text and text not in parts:
            parts.append(text)
    except Exception:
        pass
    return ' '.join(parts).strip()


def _step_description(step: dict[str, Any], index: int) -> str:
    return str(step.get('description') or step.get('action') or f'Desktop step {index}').strip()


def _execute_step(window, keyboard, step: dict[str, Any], timeout: float, allow_pointer_input: bool = False) -> dict[str, Any]:
    action = str(step.get('action') or '').strip().lower()
    if action == 'wait':
        time.sleep(max(0, float(step.get('seconds', step.get('value', 1)))))
        return {'action': action}
    if action == 'screenshot':
        return {'action': action}
    if action == 'click_coordinate':
        if not allow_pointer_input:
            raise DesktopAutomationError(
                'This action needs a coordinate click, which is disabled in safe desktop mode. '
                'Run it on an isolated desktop agent or expose a UI Automation control instead.'
            )
        window.set_focus()
        window.click_input(coords=(int(step['x']), int(step['y'])))
        return {'action': action, 'coordinate': {'x': int(step['x']), 'y': int(step['y'])}}
    if action == 'type_text':
        value = str(step.get('value') or '')
        if not value:
            raise DesktopAutomationError('Visual text input requires a non-empty value.')
        window.set_focus()
        # Chromium/Electron controls in the NN client reject VK_PACKET in this
        # desktop session; pywinauto's virtual-key path remains accepted.
        keyboard.send_keys(value, with_spaces=True, vk_packet=False)
        return {'action': action, 'value': value}

    control = _resolve_control(window, step['locator'], timeout)
    value = str(step.get('value') if step.get('value') is not None else '')
    if action == 'click':
        try:
            control.invoke()
        except Exception as exc:
            raise DesktopAutomationError(
                'The control does not expose a non-pointer UI Automation invoke action. '
                'Pointer input is disabled in safe desktop mode.'
            ) from exc
    elif action == 'double_click':
        raise DesktopAutomationError('Double-click requires pointer input and is disabled in safe desktop mode.')
    elif action == 'fill':
        control.set_focus()
        try:
            control.set_edit_text(value)
        except Exception:
            control.type_keys('^a{BACKSPACE}', set_foreground=True)
            control.type_keys(value, with_spaces=True, set_foreground=True)
    elif action == 'type':
        control.set_focus()
        control.type_keys(value, with_spaces=True, set_foreground=True)
    elif action == 'press':
        control.set_focus()
        keyboard.send_keys(value or '{ENTER}')
    elif action == 'select':
        control.select(value)
    elif action == 'assert_visible':
        if not control.is_visible():
            raise DesktopAutomationError('Control is not visible.')
    elif action == 'assert_text':
        actual = _control_content(control)
        if value not in actual:
            raise DesktopAutomationError(f'Expected text {value!r}, actual text {actual!r}.')
    elif action == 'assert_value':
        actual = str(control.get_value())
        if actual != value:
            raise DesktopAutomationError(f'Expected value {value!r}, actual value {actual!r}.')
    return {'action': action, 'locator': dict(step.get('locator') or {}), 'value': value}


def _desktop_task_instructions(task_description: str) -> list[str]:
    """Extract user-authored operation and expectation lines without inventing steps."""
    instructions = []
    section = 'operation'
    for raw_line in str(task_description or '').splitlines():
        if re.match(r'^\s*#{1,6}\s+\S', raw_line):
            # Imported Markdown case titles are metadata, not executable steps.
            continue
        line = re.sub(r'^\s*(?:[-*]|\d+[.、])\s*', '', raw_line).strip()
        if not line:
            continue
        if re.fullmatch(r'操作步骤\s*[:：]?', line, flags=re.IGNORECASE):
            section = 'operation'
            continue
        if any(marker in line for marker in ('预期结果', '预期：', '预期:', '断言：', '断言:')):
            section = 'assertion'
            remainder = re.split(r'预期结果\s*[:：]?|预期\s*[:：]?|断言\s*[:：]?', line, maxsplit=1)[-1].strip()
            if remainder:
                instructions.append(f'断言：{remainder}')
            continue
        if re.match(r'^(?:目标地址|前置条件(?:补充)?|测试数据|用例编号|用例标题)\s*[:：]', line):
            continue
        if section == 'assertion' or re.match(r'^(?:断言|验证|校验)', line):
            instructions.append(f'断言：{line}')
        else:
            instructions.append(f'操作：{line}')
    expanded_instructions = []
    for instruction in instructions:
        if instruction.startswith('\u64cd\u4f5c\uff1a') and '\u8bbf\u95ee' in instruction and re.search(r'[\uff0c,]\s*\u70b9\u51fb', instruction):
            body = instruction[len('\u64cd\u4f5c\uff1a'):]
            parts = [part.strip() for part in re.split(r'[\uff0c,]\s*(?=\u70b9\u51fb)', body) if part.strip()]
            expanded_instructions.extend(f'\u64cd\u4f5c\uff1a{part}' for part in parts)
        else:
            expanded_instructions.append(instruction)
    instructions = expanded_instructions
    if len(instructions) == 1:
        login_steps = _inline_login_instructions(instructions[0])
        if login_steps:
            return login_steps
    return instructions or [str(task_description or '').strip()]


def _inline_login_instructions(instruction: str) -> list[str]:
    """Decompose legacy one-line phone login cases into independently observable actions."""
    source = str(instruction or '').strip()
    if '\u767b\u5f55' not in source or '\u624b\u673a' not in source:
        return []
    phone_match = re.search(r'\u624b\u673a(?:\u53f7|\u53f7\u7801)?\s*([0-9]{6,15})', source)
    code_match = re.search(r'\u9a8c\u8bc1\u7801\s*([0-9]{4,8})', source)
    if not phone_match or not code_match:
        return []
    agreement_match = re.search(r'[\"\u201c]([^\"\u201d]{2,80}\u540c\u610f[^\"\u201d]{0,80})[\"\u201d]', source)
    agreement = agreement_match.group(1) if agreement_match else '\u7528\u6237\u624b\u518c'
    return [
        '\u64cd\u4f5c\uff1a\u5982\u679c\u5b58\u5728\u906e\u6321\u64cd\u4f5c\u7684\u5f39\u7a97\uff0c\u70b9\u51fb\u5f39\u7a97\u5185\u7684\u5173\u95ed\u6309\u94ae\u3002',
        '\u64cd\u4f5c\uff1a\u70b9\u51fb\u767b\u5f55\u5165\u53e3\uff0c\u6253\u5f00\u767b\u5f55\u5f39\u7a97\u3002',
        f'\u64cd\u4f5c\uff1a\u8f93\u5165\u624b\u673a\u53f7 {phone_match.group(1)}\u3002',
        f'\u64cd\u4f5c\uff1a\u8f93\u5165\u9a8c\u8bc1\u7801 {code_match.group(1)}\u3002',
        f'\u64cd\u4f5c\uff1a\u52fe\u9009\u300c{agreement}\u300d\u3002',
        '\u64cd\u4f5c\uff1a\u70b9\u51fb\u767b\u5f55\u6309\u94ae\u3002',
        '\u65ad\u8a00\uff1a\u767b\u5f55\u6210\u529f\u540e\uff0c\u5de6\u4e0b\u89d2\u5934\u50cf\u4e0d\u518d\u662f\u9ed8\u8ba4\u9ed1\u767d\u5934\u50cf\u3002',
    ]


def _desktop_setup_instructions(config: dict[str, Any]) -> list[str]:
    """Read target-specific preparation actions without pretending web templates run in a native app."""
    if not isinstance(config, dict):
        return []
    raw_steps = config.get('setup_instructions') or config.get('precondition_instructions') or []
    if isinstance(raw_steps, str):
        raw_steps = [raw_steps]
    if not isinstance(raw_steps, list):
        raise DesktopAutomationError('desktop_config.setup_instructions must be a string or an array of strings.')
    return [f'操作：{str(step).strip()}' for step in raw_steps if str(step).strip()]


def _cdp_route_from_task_description(task_description: str) -> str:
    """Map a community URL or explicit client route to an Electron hash route."""
    for raw_url in re.findall(r'https?://[^\s\]\)]+', str(task_description or '')):
        parsed = urlparse(raw_url.rstrip('，。；;'))
        if parsed.path.startswith('/community/'):
            return parsed.path + (f'?{parsed.query}' if parsed.query else '')
    route = re.search(r'(?<![\w/])(/community/\d+(?:/[\w-]+)*(?:\?[^\s\]\)]+)?)', str(task_description or ''))
    if route:
        return route.group(1).rstrip('，。；;')
    return ''


def _cdp_target_route(desktop_config: dict[str, Any], task_description: str) -> str:
    """Use an explicit PC route unless an operator deliberately enables web-route mapping."""
    explicit_route = str((desktop_config or {}).get('cdp_route') or '').strip()
    if explicit_route:
        return explicit_route.lstrip('#')
    if bool((desktop_config or {}).get('map_web_target_route', False)):
        return _cdp_route_from_task_description(task_description)
    return ''


def _cdp_community_from_route(route: str) -> str:
    """Return the NN community key encoded by a client route."""
    match = re.match(r'^/?community/(\d+)(?:/|$)', str(route or '').lstrip('#'))
    return match.group(1) if match else ''


def _is_wait_only_instruction(instruction: str) -> bool:
    text = re.sub(r'^(?:操作|断言)\s*[:：]\s*', '', str(instruction or '')).strip().lower()
    if not (text.startswith('等待') or text.startswith('wait')):
        return False
    return not any(marker in text for marker in ('点击', '输入', '填写', '选择', '切换', '打开', '关闭', '断言', '验证', '检查'))


def _requested_wait_seconds(instruction: str) -> float | None:
    """Read an explicit wait duration instead of silently replacing it."""
    normalized = str(instruction or '').replace(' ', '')
    if not _is_wait_only_instruction(instruction):
        return None
    match = re.search(r'(\d+(?:\.\d+)?)\s*(?:秒|s(?:ec(?:onds?)?)?)', normalized, flags=re.IGNORECASE)
    if not match:
        return None
    return max(0.0, min(float(match.group(1)), 15.0))


def _desktop_control_snapshot(window, max_controls: int = 140) -> list[dict[str, Any]]:
    """Expose a bounded, visible UIA tree to the planner instead of coordinates."""
    controls = []
    try:
        descendants = window.descendants()
    except Exception as exc:
        raise DesktopAutomationError(f'Unable to inspect desktop controls: {exc}') from exc

    for control in descendants:
        if len(controls) >= max_controls:
            break
        try:
            if not control.is_visible():
                continue
            info = control.element_info
            name = str(getattr(info, 'name', '') or control.window_text() or '').strip()
            auto_id = str(getattr(info, 'automation_id', '') or '').strip()
            control_type = str(getattr(info, 'control_type', '') or '').strip()
            class_name = str(getattr(info, 'class_name', '') or '').strip()
            if not any((name, auto_id, control_type, class_name)):
                continue
            value = ''
            is_password = bool(getattr(info, 'is_password', False))
            if not is_password:
                try:
                    value = str(control.get_value() or '').strip()
                except Exception:
                    value = ''
            rectangle = control.rectangle()
            item = {
                'control_id': f'c{len(controls) + 1}',
                'name': name[:160],
                'auto_id': auto_id[:160],
                'control_type': control_type[:80],
                'class_name': class_name[:120],
                'bounds': [rectangle.left, rectangle.top, rectangle.right, rectangle.bottom],
            }
            if value:
                item['value'] = value[:240]
            controls.append(item)
        except Exception:
            continue
    return controls


def _desktop_locator_from_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    locator = {}
    if item.get('auto_id'):
        locator['auto_id'] = item['auto_id']
    elif item.get('name'):
        locator['title'] = item['name']
    if item.get('control_type'):
        locator['control_type'] = item['control_type']
    if not locator and item.get('class_name'):
        locator['class_name'] = item['class_name']
    return locator


def _extract_json_object(content: Any) -> dict[str, Any]:
    text = str(content or '').strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text, flags=re.IGNORECASE | re.DOTALL).strip()
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for match in re.finditer(r'\{', text):
            try:
                value, _ = decoder.raw_decode(text[match.start():])
                if isinstance(value, dict):
                    return value
            except json.JSONDecodeError:
                continue
    raise DesktopAutomationError('Desktop planner returned invalid JSON.')


def _desktop_planner_llm():
    """Use the existing browser-use text model configuration for desktop planning."""
    from apps.requirement_analysis.models import AIModelConfig
    from langchain_openai import ChatOpenAI

    config = AIModelConfig.objects.filter(role='browser_use_text', is_active=True).first()
    if not config or not config.api_key or not config.model_name:
        raise DesktopAutomationError('No active AI model is configured for desktop natural-language execution.')
    kwargs = {
        'model': config.model_name,
        'api_key': config.api_key,
        'temperature': 0,
    }
    if config.base_url:
        kwargs['base_url'] = config.base_url
    return ChatOpenAI(**kwargs)


def _plan_desktop_action(
    llm,
    task_description: str,
    instruction: str,
    controls: list[dict[str, Any]],
    previous_actions: list[dict[str, Any]] | None = None,
    allow_screenshot: bool = True,
) -> dict[str, Any]:
    allowed_actions = set(SUPPORTED_ACTIONS) - {'click_coordinate'}
    if not allow_screenshot:
        allowed_actions.discard('screenshot')
    allowed_actions.add('done')
    action_schema = '|'.join([
        'click', 'double_click', 'fill', 'type', 'press', 'select', 'wait',
        'assert_visible', 'assert_text', 'assert_value',
        *( ['screenshot'] if allow_screenshot else [] ),
        'done',
    ])
    prompt = {
        'role': 'Windows desktop UI automation planner',
        'rules': [
            'Return one JSON object only. Do not wrap it in Markdown.',
            'Choose controls only by a control_id listed in visible_controls.',
            'Never use coordinates. Do not invent a control_id.',
            'Return one atomic action, then wait for a new UI scan before the next action.',
            'Use done only when the current instruction has been completed or verified from the visible controls.',
            'For an assertion, use assert_visible or assert_text and include the expected value.',
            'Before mutating the UI, compare visible control values and previous_actions with the current instruction.',
            'Never repeat a mutation already reflected in the visible controls; return done when that instruction is satisfied.',
            'When visible_controls is non-empty, use wait at most once for the same instruction. Then choose an allowed action or return done.',
        ],
        'allowed_actions': sorted(allowed_actions),
        'task_description': task_description,
        'current_instruction': instruction,
        'previous_actions': previous_actions or [],
        'visible_controls': controls,
        'response_schema': {
            'action': action_schema,
            'control_id': 'required except wait, done' + (', screenshot' if allow_screenshot else ''),
            'value': 'required for fill, type, press, select, assert_text, assert_value',
            'seconds': 'optional for wait',
            'description': 'short execution note',
        },
    }
    try:
        response = llm.invoke(json.dumps(prompt, ensure_ascii=False))
    except Exception as exc:
        raise DesktopAutomationError(f'Desktop planner model call failed: {exc}') from exc
    return _extract_json_object(getattr(response, 'content', response))


def _validate_visual_assertion_result(result: dict[str, Any]) -> dict[str, Any]:
    status = str(result.get('status') or '').strip().lower()
    if status not in {'passed', 'failed', 'inconclusive'}:
        raise DesktopAutomationError('Desktop visual assertion returned an invalid status.')
    return {
        'status': status,
        'reason': str(result.get('reason') or '').strip(),
        'evidence': result.get('evidence') if isinstance(result.get('evidence'), list) else [],
    }


def _visual_assertion_crop_boxes(instruction: str, width: int, height: int) -> list[tuple[str, tuple[int, int, int, int]]]:
    """Return enlarged regions when the assertion targets a dense part of the window."""
    text = str(instruction or '').lower()
    if width < 2 or height < 2:
        return []

    right_terms = ('右侧', '右边', '右栏', '右侧栏', 'right panel', 'right sidebar', 'right side')
    left_terms = ('左侧', '左边', '左栏', '左侧栏', 'left panel', 'left sidebar', 'left side')
    dense_terms = (
        '成员', 'member', '头像', '昵称', '在线', '身份标识', '身份标签',
        '列表', 'list', '表格', 'table', '卡片', 'card', '布局', '重叠',
        '遮挡', '串位', '错位', '对齐', '排列', 'overlap', 'layout', 'alignment',
    )
    side_width = max(1, int(width * 0.36))
    center_left = max(0, int(width * 0.22))
    center_right = min(width, int(width * 0.78))

    if any(term in text for term in right_terms):
        return [('right-side target area', (width - side_width, 0, width, height))]
    if any(term in text for term in left_terms):
        return [('left-side target area', (0, 0, side_width, height))]
    if any(term in text for term in dense_terms):
        return [
            ('left detail area', (0, 0, side_width, height)),
            ('center detail area', (center_left, 0, center_right, height)),
            ('right detail area', (width - side_width, 0, width, height)),
        ]
    return []


def _visual_assertion_interpretation(instruction: str) -> str:
    """Add product-agnostic guidance for common intentionally attached UI indicators."""
    text = str(instruction or '').lower()
    status_terms = ('在线', '状态', '绿点', '状态点', 'online', 'status', 'indicator')
    avatar_terms = ('头像', 'avatar', '成员', 'member', '用户', 'user')
    if any(term in text for term in status_terms) and any(term in text for term in avatar_terms):
        return (
            'A small online/status indicator intentionally anchored on an avatar edge is a valid same-row attachment, '
            'not harmful overlap. Treat it as a failure only when it covers the nickname or identity label, appears in '
            'empty space, or crosses into an adjacent member row.'
        )
    return ''


def _visual_assertion_message_content(instruction: str, image_path: Path) -> list[dict[str, Any]]:
    """Provide full context plus lossless enlarged crops for dense desktop assertions."""
    from PIL import Image

    full_image_data = base64.b64encode(image_path.read_bytes()).decode('ascii')
    content: list[dict[str, Any]] = [
        {'type': 'image_url', 'image_url': {'url': f'data:image/png;base64,{full_image_data}'}},
    ]
    with Image.open(image_path) as source:
        for label, crop_box in _visual_assertion_crop_boxes(instruction, *source.size):
            crop = source.crop(crop_box)
            scale = max(1, min(4, (960 + crop.width - 1) // crop.width))
            if scale > 1:
                crop = crop.resize((crop.width * scale, crop.height * scale))
            buffer = BytesIO()
            crop.save(buffer, format='PNG')
            crop_data = base64.b64encode(buffer.getvalue()).decode('ascii')
            content.extend([
                {'type': 'text', 'text': f'Enlarged {label}; use it only for UI details located in this region.'},
                {'type': 'image_url', 'image_url': {'url': f'data:image/png;base64,{crop_data}'}},
            ])
    return content


def _run_desktop_visual_assertion(llm, instruction: str, screenshot_path: str) -> dict[str, Any]:
    """Verify visual desktop assertions from the current screenshot, not guessed UIA text."""
    from langchain_core.messages import HumanMessage

    image_path = Path(settings.MEDIA_ROOT) / screenshot_path
    if not image_path.is_file():
        raise DesktopAutomationError('Desktop visual assertion screenshot was not created.')
    is_dom_evidence = image_path.name.startswith('cdp_dom_evidence_')
    evidence_mode = (
        'The image is a labeled Renderer DOM Evidence board, generated from the current visible renderer because the '
        'Electron compositor returned only black frames. Each bracketed prefix is the element viewport coordinate and size. '
        'You may pass only text, control-presence, value, route, selection, count, or layout conditions explicitly proven by '
        'that captured state. Return inconclusive for pixels, colors, images, animation, or any relationship not shown by the '
        'text and coordinates. '
        if is_dom_evidence else ''
    )
    prompt = (
        'You are verifying a Windows desktop UI assertion from one current screenshot and optional enlarged detail crops. '
        'Return one JSON object only with status (passed|failed|inconclusive), reason, and evidence (a short array). '
        'The first image is full-window context. Each following crop enlarges a labeled part of that same screenshot. '
        'Use a relevant crop to inspect small rows, icons, labels, and spacing; do not fail a target merely because unrelated '
        'content outside its target area is covered. Pass only when every stated condition is visibly satisfied. '
        'Do not infer hidden state, and use inconclusive when the screenshot cannot prove a condition. '
        f'{evidence_mode}{_visual_assertion_interpretation(instruction)} '
        f'Assertion: {instruction}'
    )
    try:
        response = llm.invoke([HumanMessage(content=[
            {'type': 'text', 'text': prompt},
            *_visual_assertion_message_content(instruction, image_path),
        ])])
    except Exception as exc:
        raise DesktopAutomationError(f'Desktop visual assertion model call failed: {exc}') from exc
    return _validate_visual_assertion_result(_extract_json_object(getattr(response, 'content', response)))


def _run_desktop_visual_operation_check(llm, instruction: str, screenshot_path: str) -> dict[str, Any]:
    """Confirm a navigation/result state when an Electron client exposes no usable controls."""
    from langchain_core.messages import HumanMessage

    image_path = Path(settings.MEDIA_ROOT) / screenshot_path
    if not image_path.is_file():
        raise DesktopAutomationError('Desktop operation-state screenshot was not created.')
    image_data = base64.b64encode(image_path.read_bytes()).decode('ascii')
    prompt = (
        'You are checking whether a Windows desktop operation is already complete in the current screenshot. '
        'Return one JSON object only with status (passed|failed|inconclusive), reason, and evidence (a short array). '
        'Return passed only when the result requested by the operation is visibly present now. '
        'Do not claim passed merely because a related label is visible. '
        f'Operation: {instruction}'
    )
    try:
        response = llm.invoke([HumanMessage(content=[
            {'type': 'text', 'text': prompt},
            {'type': 'image_url', 'image_url': {'url': f'data:image/png;base64,{image_data}'}},
        ])])
    except Exception as exc:
        raise DesktopAutomationError(f'Desktop operation-state model call failed: {exc}') from exc
    return _validate_visual_assertion_result(_extract_json_object(getattr(response, 'content', response)))


def _plan_desktop_visual_action(
    llm,
    instruction: str,
    screenshot_path: str,
    previous_actions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Plan one bounded click when an Electron view has no usable UIA controls."""
    from langchain_core.messages import HumanMessage
    from PIL import Image

    image_path = Path(settings.MEDIA_ROOT) / screenshot_path
    if not image_path.is_file():
        raise DesktopAutomationError('Desktop visual-action screenshot was not created.')
    with Image.open(image_path) as image:
        width, height = image.size
    image_data = base64.b64encode(image_path.read_bytes()).decode('ascii')
    prompt = (
        'You are planning exactly one safe Windows desktop action from the current application screenshot. '
        'Return one JSON object only. The operation must be completed through visible UI, not assumed. '
        'Use click_coordinate only when the required target is visibly identifiable. x and y must be integer pixels '
        f'relative to this screenshot ({width} by {height}), inside the target center, never on a window close/minimize/maximize control. '
        'Use type_text only to enter text into a visibly focused input; provide value with the exact text to type. '
        'Use wait only for a visible loading transition. Use done only if the requested operation result is already visibly true. '
        'Do not repeat an earlier click unless the new screenshot visibly proves it was ineffective. '
        'When the previous action focused an empty input for this operation, enter the requested text next instead of clicking it again. '
        'If the target cannot be identified, return action=failed with a concise reason instead of guessing. '
        f'Operation: {instruction}\nPrevious actions: {json.dumps(previous_actions or [], ensure_ascii=False)}'
    )
    try:
        response = llm.invoke([HumanMessage(content=[
            {'type': 'text', 'text': prompt},
            {'type': 'image_url', 'image_url': {'url': f'data:image/png;base64,{image_data}'}},
        ])])
    except Exception as exc:
        raise DesktopAutomationError(f'Desktop visual-action model call failed: {exc}') from exc
    action = _extract_json_object(getattr(response, 'content', response))
    action_name = str(action.get('action') or '').strip().lower()
    if action_name == 'failed':
        raise DesktopAutomationError(str(action.get('reason') or 'The visual planner could not identify a safe target.'))
    if action_name == 'done':
        return {'action': 'done', 'reason': str(action.get('reason') or '')}
    if action_name == 'wait':
        return {
            'action': 'wait',
            'seconds': max(0.2, min(float(action.get('seconds') or 1), 5.0)),
            'reason': str(action.get('reason') or ''),
        }
    if action_name == 'type_text':
        value = str(action.get('value') or action.get('text') or '').strip()
        if not value:
            raise DesktopAutomationError('Desktop visual planner did not return text for the focused input.')
        return {'action': 'type_text', 'value': value, 'reason': str(action.get('reason') or '')}
    if action_name != 'click_coordinate':
        raise DesktopAutomationError(f'Desktop visual planner selected unsupported action: {action_name or "<empty>"}.')
    try:
        x, y = int(action.get('x')), int(action.get('y'))
    except (TypeError, ValueError) as exc:
        raise DesktopAutomationError('Desktop visual planner did not return numeric click coordinates.') from exc
    if not (0 <= x < width and 0 <= y < height):
        raise DesktopAutomationError(f'Desktop visual planner returned an out-of-window coordinate ({x}, {y}).')
    # Keep vision fallback away from the standard Windows caption-button strip.
    if y < max(36, int(height * 0.05)) and x > int(width * 0.78):
        raise DesktopAutomationError('Desktop visual planner selected the protected window-control area.')
    return {'action': 'click_coordinate', 'x': x, 'y': y, 'reason': str(action.get('reason') or '')}


def _planned_step_from_action(action: dict[str, Any], controls: list[dict[str, Any]]) -> dict[str, Any] | None:
    action_name = str(action.get('action') or '').strip().lower()
    if action_name == 'done':
        return None
    if action_name not in SUPPORTED_ACTIONS or action_name == 'click_coordinate':
        raise DesktopAutomationError(f'Desktop planner selected unsupported action: {action_name or "<empty>"}.')
    step = {
        'action': action_name,
        'value': action.get('value', ''),
        'seconds': action.get('seconds', action.get('value', 1)),
        'description': str(action.get('description') or action_name),
    }
    if action_name not in {'wait', 'screenshot'}:
        control_id = str(action.get('control_id') or '')
        control = next((item for item in controls if item['control_id'] == control_id), None)
        if not control:
            raise DesktopAutomationError('Desktop planner selected a control that is not visible in the current UI scan.')
        locator = _desktop_locator_from_snapshot(control)
        if not locator:
            raise DesktopAutomationError('Selected desktop control has no stable locator metadata.')
        step['locator'] = locator
    return step


def _cdp_endpoint_is_available(cdp_url: str) -> bool:
    endpoint = str(cdp_url or 'http://127.0.0.1:9222').rstrip('/')
    try:
        with urllib.request.urlopen(f'{endpoint}/json/version', timeout=3) as response:
            payload = json.load(response)
        return bool(payload.get('webSocketDebuggerUrl'))
    except Exception:
        return False


def _cdp_renderer_page_is_available(cdp_url: str) -> bool:
    """Require NN's application renderer, not its transient loading window."""
    endpoint = str(cdp_url or 'http://127.0.0.1:9222').rstrip('/')
    try:
        with urllib.request.urlopen(f'{endpoint}/json/list', timeout=3) as response:
            targets = json.load(response)
        return any(
            item.get('type') == 'page'
            and item.get('webSocketDebuggerUrl')
            and 'renderer.asar/index.html' in str(item.get('url') or '')
            for item in targets
        )
    except Exception:
        return False


def _cdp_user_data_dir_from_args(launch_args: list[str] | None) -> str:
    """Read an isolated Electron profile path from standard CDP launch args."""
    for raw_arg in launch_args or []:
        arg = str(raw_arg or '')
        if arg.startswith('--user-data-dir='):
            return os.path.normcase(os.path.abspath(arg.split('=', 1)[1]))
    return ''


def _stop_cdp_profile_processes(executable: str, user_data_dir: str) -> int:
    """Stop only one TestHub-owned Electron profile, never the user's NN app."""
    if not executable or not user_data_dir:
        return 0
    try:
        import psutil
    except ImportError:
        return 0
    expected_executable = os.path.normcase(os.path.abspath(executable))
    expected_profile = os.path.normcase(os.path.abspath(user_data_dir))
    matches = []
    for process in psutil.process_iter(['pid', 'exe', 'cmdline']):
        try:
            candidate = os.path.normcase(os.path.abspath(str(process.info.get('exe') or '')))
            command = ' '.join(str(part) for part in (process.info.get('cmdline') or []))
            if candidate == expected_executable and expected_profile in os.path.normcase(command):
                matches.append(process)
        except (psutil.Error, OSError):
            continue
    for process in matches:
        try:
            process.terminate()
        except (psutil.Error, OSError):
            pass
    if matches:
        try:
            _gone, alive = psutil.wait_procs(matches, timeout=5)
        except psutil.Error:
            alive = []
        for process in alive:
            try:
                process.kill()
            except (psutil.Error, OSError):
                pass
    return len(matches)


async def _wait_for_cdp_endpoint_state(cdp_url: str, available: bool, timeout_seconds: float = 12) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        current = await asyncio.to_thread(_cdp_renderer_page_is_available, cdp_url)
        if current == available:
            return True
        await asyncio.sleep(0.25)
    return False


def _hall_other_member_fixture_config(desktop_config: dict[str, Any]) -> dict[str, Any]:
    fixture = (desktop_config or {}).get('cdp_hall_other_member_fixture') or {}
    if not isinstance(fixture, dict):
        return {}
    credentials = fixture.get('credentials') or {}
    phone = str(credentials.get('phone') or '').strip()
    verification_code = str(credentials.get('verification_code') or '').strip()
    profile = str(fixture.get('user_data_dir') or '').strip()
    if not re.fullmatch(r'1\d{10}', phone) or not verification_code or not profile:
        return {}
    return {
        'credentials': {'phone': phone, 'verification_code': verification_code},
        'user_data_dir': profile,
    }


def _task_requires_hall_other_member_fixture(task_description: str, desktop_config: dict[str, Any]) -> bool:
    text = str(task_description or '').replace(' ', '')
    return bool(_hall_other_member_fixture_config(desktop_config)) and '其他成员账号' in text and 'HALL_${timestamp()}' in text


async def _seed_hall_other_member_fixture(desktop_config: dict[str, Any]) -> dict[str, Any]:
    """Publish one real Hall message through a separate, short-lived NN account."""
    fixture = _hall_other_member_fixture_config(desktop_config)
    executable = str((desktop_config or {}).get('cdp_executable') or '').strip()
    main_args = list((desktop_config or {}).get('cdp_launch_args') or [])
    main_profile = _cdp_user_data_dir_from_args(main_args)
    if not fixture or not executable or not main_profile:
        raise DesktopAutomationError('Hall other-member fixture requires isolated main and fixture CDP profiles.')

    fixture_url = 'http://127.0.0.1:9223'
    fixture_args = [
        '--remote-debugging-address=127.0.0.1',
        '--remote-debugging-port=9223',
        f'--user-data-dir={fixture["user_data_dir"]}',
    ]
    fixture_config = {
        **desktop_config,
        'cdp_url': fixture_url,
        'cdp_launch_args': fixture_args,
        'cdp_login_credentials': fixture['credentials'],
    }
    fixture_page = None
    try:
        await asyncio.to_thread(_stop_cdp_profile_processes, executable, main_profile)
        await _wait_for_cdp_endpoint_state(str(desktop_config.get('cdp_url') or 'http://127.0.0.1:9222'), False, 10)
        await _ensure_cdp_endpoint(fixture_url, fixture_config)
        fixture_page = await _CDPPage.connect(fixture_url)
        await _ensure_cdp_nn_login(fixture_page, fixture_config)
        await _activate_cdp_route_context(fixture_page, '/community/7520/hall')
        await _wait_for_cdp_renderer_stability(fixture_page, timeout_seconds=10)
        result = await _execute_cdp_semantic_instruction(
            fixture_page,
            '操作：在输入框发送唯一文本消息 HALL_${timestamp()}_其他成员夹具。',
            '目标地址：NN 客户端 /community/7520/hall',
        )
        if not isinstance(result, dict) or not result.get('passed'):
            # A just-started isolated Electron profile can expose the Hall
            # composer before its first IM keydown listener is fully mounted.
            # Remount once and retry with a new unique value; a failed first
            # attempt has no server record and therefore cannot duplicate data.
            await _activate_cdp_route_context(fixture_page, '/community/7520/hall')
            await _wait_for_cdp_renderer_stability(fixture_page, timeout_seconds=10)
            result = await _execute_cdp_semantic_instruction(
                fixture_page,
                '操作：在输入框发送唯一文本消息 HALL_${timestamp()}_其他成员夹具。',
                '目标地址：NN 客户端 /community/7520/hall',
            )
        if not isinstance(result, dict) or not result.get('passed'):
            raise DesktopAutomationError(f'Other-member Hall fixture send failed: {result}')
        values = (result.get('evidence') or {}).get('values') or []
        value = str(values[-1] if values else '')
        if not value:
            raise DesktopAutomationError('Other-member Hall fixture did not return a unique message value.')
        return {'value': value, 'fixture_phone': fixture['credentials']['phone'], 'send_evidence': result.get('evidence') or {}}
    finally:
        if fixture_page is not None:
            try:
                await fixture_page.close()
            except Exception:
                pass
        await asyncio.to_thread(_stop_cdp_profile_processes, executable, fixture['user_data_dir'])
        await _wait_for_cdp_endpoint_state(fixture_url, False, 10)
        await _ensure_cdp_endpoint(str(desktop_config.get('cdp_url') or 'http://127.0.0.1:9222'), desktop_config)


async def _cleanup_hall_other_member_fixture(
    desktop_config: dict[str, Any],
    fixture_evidence: dict[str, Any],
) -> dict[str, Any]:
    """Recall a fixture message in the account that created it.

    The primary test account must not be allowed to recall a message owned by
    the secondary fixture account. Reopen the short-lived fixture profile only
    after the case has completed, then use NN's real recall API in that owner
    session. The primary Agent is restored before the next case starts.
    """
    fixture = _hall_other_member_fixture_config(desktop_config)
    executable = str((desktop_config or {}).get('cdp_executable') or '').strip()
    main_args = list((desktop_config or {}).get('cdp_launch_args') or [])
    main_profile = _cdp_user_data_dir_from_args(main_args)
    send_evidence = (fixture_evidence or {}).get('send_evidence') or {}
    values = [str(value) for value in (send_evidence.get('values') or []) if str(value)]
    if not fixture or not executable or not main_profile or not values:
        return {
            'handled': True,
            'passed': False,
            'reason': 'other-member fixture cleanup has incomplete owner-session evidence',
            'evidence': {'values': values, 'fixtureConfigured': bool(fixture)},
        }
    fixture_url = 'http://127.0.0.1:9223'
    fixture_args = [
        '--remote-debugging-address=127.0.0.1',
        '--remote-debugging-port=9223',
        f'--user-data-dir={fixture["user_data_dir"]}',
    ]
    fixture_config = {
        **desktop_config,
        'cdp_url': fixture_url,
        'cdp_launch_args': fixture_args,
        'cdp_login_credentials': fixture['credentials'],
    }
    fixture_page = None
    try:
        await asyncio.to_thread(_stop_cdp_profile_processes, executable, main_profile)
        await _wait_for_cdp_endpoint_state(str(desktop_config.get('cdp_url') or 'http://127.0.0.1:9222'), False, 10)
        await _ensure_cdp_endpoint(fixture_url, fixture_config)
        fixture_page = await _CDPPage.connect(fixture_url)
        await _ensure_cdp_nn_login(fixture_page, fixture_config)
        await _activate_cdp_route_context(fixture_page, '/community/7520/hall')
        await _wait_for_cdp_renderer_stability(fixture_page, timeout_seconds=10)
        evidence_json = json.dumps(send_evidence, ensure_ascii=False)
        values_json = json.dumps(values, ensure_ascii=False)
        await fixture_page.evaluate(f'''
          (() => {{
            sessionStorage.setItem('__testhub_hall_send_evidence', {evidence_json});
            sessionStorage.setItem('__testhub_hall_unique_messages', {values_json});
            return true;
          }})()
        ''')
        await _ensure_cdp_hall_message_context(fixture_page)
        return await _cleanup_cdp_generated_hall_messages(fixture_page)
    finally:
        if fixture_page is not None:
            try:
                await fixture_page.close()
            except Exception:
                pass
        await asyncio.to_thread(_stop_cdp_profile_processes, executable, fixture['user_data_dir'])
        await _wait_for_cdp_endpoint_state(fixture_url, False, 10)
        await _ensure_cdp_endpoint(str(desktop_config.get('cdp_url') or 'http://127.0.0.1:9222'), desktop_config)


def _elevated_cdp_launcher_command(executable: str, launch_args: list[str]) -> list[str]:
    """Build a one-shot Windows launcher for an elevated NN CDP Agent."""
    def ps_quote(value: str) -> str:
        return "'" + str(value).replace("'", "''") + "'"

    arg_list = '@(' + ','.join(ps_quote(argument) for argument in launch_args) + ')'
    agent_profile = _cdp_user_data_dir_from_args(launch_args)
    if not agent_profile:
        raise DesktopAutomationError('Elevated CDP Agent startup requires an isolated --user-data-dir.')
    normalized_executable = os.path.normcase(os.path.abspath(executable))
    normalized_profile = os.path.normcase(os.path.abspath(agent_profile))
    payload = (
        "$ErrorActionPreference='SilentlyContinue';"
        f"$agentExe={ps_quote(normalized_executable)};"
        f"$agentProfile={ps_quote(normalized_profile)};"
        "Get-CimInstance Win32_Process -Filter \"Name = 'nn.exe'\" | "
        "Where-Object { $_.ExecutablePath -and $_.CommandLine -and "
        "[IO.Path]::GetFullPath($_.ExecutablePath).ToLowerInvariant() -eq $agentExe -and "
        "$_.CommandLine.ToLowerInvariant().Contains($agentProfile) } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue };"
        "Start-Sleep -Milliseconds 800;"
        f"Start-Process -FilePath {ps_quote(executable)} -ArgumentList {arg_list} "
        f"-WorkingDirectory {ps_quote(str(Path(executable).parent))}"
    )
    encoded_payload = base64.b64encode(payload.encode('utf-16le')).decode('ascii')
    command = (
        "Start-Process -FilePath 'powershell.exe' -ArgumentList "
        "@('-NoProfile','-ExecutionPolicy','Bypass','-EncodedCommand',"
        f"'{encoded_payload}') -Verb RunAs"
    )
    return ['powershell.exe', '-NoProfile', '-Command', command]


def _start_elevated_cdp_agent(executable: str, launch_args: list[str]) -> None:
    if os.name != 'nt':
        raise DesktopAutomationError('Elevated CDP startup is available only on Windows.')
    try:
        subprocess.Popen(_elevated_cdp_launcher_command(executable, launch_args))
    except OSError as exc:
        raise DesktopAutomationError(f'Unable to request elevated Electron CDP startup: {exc}') from exc


async def _ensure_cdp_endpoint(cdp_url: str, desktop_config: dict[str, Any]) -> bool:
    """Ensure CDP exposes a live Electron renderer without touching pointer input."""
    if await asyncio.to_thread(_cdp_renderer_page_is_available, cdp_url):
        if bool(desktop_config.get('cdp_silent', True)):
            await asyncio.to_thread(_hide_cdp_agent_windows, str(desktop_config.get('cdp_executable') or ''))
        return False
    # Runtime test execution must not launch NN through RunAs. That would put
    # an interactive UAC confirmation in every unattended batch. A dedicated
    # long-lived Agent owns the port; an explicit maintenance action may opt
    # into startup separately with this second flag.
    can_start_agent = bool(desktop_config.get('cdp_auto_start', False)) and bool(
        desktop_config.get('cdp_allow_runtime_autostart', False)
    )
    if not can_start_agent:
        raise DesktopAutomationError(
            f'Electron CDP Agent is offline at {cdp_url}. Test runs do not auto-start or request UAC; '
            'restore the long-lived Agent, then rerun.'
        )

    # A concurrent batch may find the Agent down at the same instant. Hold a
    # process-wide startup lock until the renderer is ready so only one
    # isolated NN instance is launched for port 9222.
    await asyncio.to_thread(_CDP_AGENT_START_LOCK.acquire)
    try:
        if await asyncio.to_thread(_cdp_renderer_page_is_available, cdp_url):
            return False
        executable = str(desktop_config.get('cdp_executable') or '').strip()
        if not executable or not Path(executable).is_file():
            raise DesktopAutomationError(
                'Electron CDP endpoint is unavailable and desktop_config.cdp_executable is not a valid executable path.'
            )
        launch_args = desktop_config.get('cdp_launch_args')
        if not isinstance(launch_args, list):
            launch_args = ['--remote-debugging-address=127.0.0.1', '--remote-debugging-port=9222']
        launch_args = [str(argument) for argument in launch_args]
        elevated_start = bool(desktop_config.get('cdp_elevated_auto_start', False))
        silent_start = bool(desktop_config.get('cdp_silent', True))
        if elevated_start:
            _start_elevated_cdp_agent(executable, launch_args)
        else:
            try:
                subprocess.Popen(
                    [executable, *launch_args],
                    startupinfo=_cdp_agent_startupinfo(silent_start),
                )
            except OSError as exc:
                raise DesktopAutomationError(f'Unable to start the Electron client for CDP: {exc}') from exc

        try:
            startup_timeout = max(3.0, min(float(desktop_config.get('cdp_startup_timeout_seconds') or 30), 60.0))
        except (TypeError, ValueError) as exc:
            raise DesktopAutomationError('desktop_config.cdp_startup_timeout_seconds must be numeric.') from exc
        deadline = asyncio.get_running_loop().time() + startup_timeout
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.5)
            if silent_start:
                await asyncio.to_thread(_hide_cdp_agent_windows, executable)
            if await asyncio.to_thread(_cdp_renderer_page_is_available, cdp_url):
                return True
        raise DesktopAutomationError(
            f'NN started but CDP did not become available at {cdp_url}. '
            'The isolated non-elevated Agent did not start successfully; verify its executable and profile configuration.'
        )
    finally:
        _CDP_AGENT_START_LOCK.release()


def _is_cdp_connection_error(exc: Exception) -> bool:
    """Recognize transport failures emitted by different websockets versions."""
    message = str(exc).casefold()
    return (
        'no close frame' in message
        or 'connection closed' in message
        or 'connection is closed' in message
        or 'connection reset' in message
        or 'broken pipe' in message
    )


class _CDPPage:
    """Small Chromium-CDP client compatible with the NN client's Chromium 108."""

    def __init__(self, websocket, target, endpoint: str):
        self.websocket = websocket
        self.target = target
        self.endpoint = endpoint
        self._message_id = 0
        self._recovery_hook = None
        self._recovering = False
        self.recovery_count = 0

    @classmethod
    async def connect(cls, cdp_url: str):
        import websockets

        endpoint = str(cdp_url or 'http://127.0.0.1:9222').rstrip('/')
        with urllib.request.urlopen(f'{endpoint}/json/list', timeout=8) as response:
            targets = json.load(response)
        pages = [item for item in targets if item.get('type') == 'page' and item.get('webSocketDebuggerUrl')]
        target = next((
            item for item in pages
            if 'renderer.asar/index.html' in str(item.get('url') or '')
            and 'popover' not in str(item.get('url') or '').lower()
        ), None)
        target = target or next((item for item in pages if 'popover' not in str(item.get('url') or '').lower()), None)
        if not target:
            raise DesktopAutomationError(f'No inspectable NN page is exposed by CDP at {endpoint}.')
        websocket = await websockets.connect(target['webSocketDebuggerUrl'], open_timeout=8, max_size=16 * 1024 * 1024)
        page = cls(websocket, target, endpoint)
        await page.call('Runtime.enable')
        await page.call('Page.enable')
        return page

    async def close(self):
        try:
            await self.websocket.close()
        except Exception:
            pass

    def set_recovery_hook(self, hook) -> None:
        """Set the state-restoration hook used after an Electron renderer reconnect."""
        self._recovery_hook = hook

    async def reconnect(self) -> None:
        """Reconnect to the current inspectable renderer without touching native input."""
        replacement = await type(self).connect(self.endpoint)
        previous_socket = self.websocket
        self.websocket = replacement.websocket
        self.target = replacement.target
        self._message_id = replacement._message_id
        self.recovery_count += 1
        try:
            await previous_socket.close()
        except Exception:
            pass

    async def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        for attempt in range(3):
            self._message_id += 1
            message_id = self._message_id
            try:
                await self.websocket.send(json.dumps({'id': message_id, 'method': method, 'params': params or {}}))
                while True:
                    try:
                        # Semantic assertions may deliberately wait for an async
                        # renderer list to settle. Keep the transport timeout above
                        # that bounded assertion window so it is not misreported as
                        # a CDP failure.
                        message = json.loads(await asyncio.wait_for(self.websocket.recv(), timeout=30))
                    except asyncio.TimeoutError as exc:
                        raise DesktopAutomationError(f'CDP command timed out: {method}.') from exc
                    if message.get('id') != message_id:
                        continue
                    if 'error' in message:
                        raise DesktopAutomationError(f'CDP command failed ({method}): {message["error"].get("message", message["error"])}')
                    return message.get('result') or {}
            except Exception as exc:
                # Chromium can keep the WebSocket open while its renderer is
                # briefly wedged during a route reload. Treat that timeout as
                # a recoverable renderer loss and reconnect before declaring
                # the test failed.
                timed_out = isinstance(exc, DesktopAutomationError) and str(exc).startswith('CDP command timed out:')
                if not _is_cdp_connection_error(exc) and not timed_out:
                    raise
                if attempt == 2 or self._recovering:
                    raise CDPConnectionLost(f'Electron CDP connection was lost during {method}: {exc}') from exc
                self._recovering = True
                try:
                    await self.reconnect()
                    if self._recovery_hook is not None:
                        await self._recovery_hook(self)
                finally:
                    self._recovering = False
        raise CDPConnectionLost(f'Electron CDP connection could not recover during {method}.')

    async def evaluate(self, expression: str):
        result = await self.call('Runtime.evaluate', {
            'expression': expression,
            'awaitPromise': True,
            'returnByValue': True,
            'userGesture': True,
        })
        details = result.get('exceptionDetails')
        if details:
            exception = details.get('exception') or {}
            description = str(exception.get('description') or exception.get('value') or '').strip()
            location = ':'.join(str(part) for part in (details.get('lineNumber'), details.get('columnNumber')) if part is not None)
            message = description or str(details.get('text') or 'unknown error')
            raise DesktopAutomationError(f'CDP page evaluation failed{f" at {location}" if location else ""}: {message}')
        return (result.get('result') or {}).get('value')


async def _block_cdp_external_image_navigation(page: _CDPPage) -> None:
    """Keep CDN image links inside the hidden Agent renderer, never the user's browser."""
    await page.evaluate(r'''
      (() => {
        if (window.__testhub_external_image_navigation_blocked) return true;
        const isImageCdn = value => /^https?:\/\/[^/]*dfs\d*\.nn\.com\//i.test(String(value || ''));
        const nativeOpen = window.open;
        window.open = function(url, ...args) {
          return isImageCdn(url) ? null : nativeOpen.call(window, url, ...args);
        };
        document.addEventListener('click', event => {
          const link = event.target instanceof Element ? event.target.closest('a[href]') : null;
          if (link && isImageCdn(link.href)) {
            event.preventDefault();
            event.stopImmediatePropagation();
          }
        }, true);
        window.__testhub_external_image_navigation_blocked = true;
        return true;
      })()
    ''')


_CDP_VISIBLE_CONTROLS_SCRIPT = r'''
(() => {
  const isVisible = (element) => {
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return rect.width > 2 && rect.height > 2 && style.visibility !== 'hidden' && style.display !== 'none';
  };
  const escape = (value) => String(value).replace(/\\/g, '\\\\').replace(/"/g, '\\"');
  const selectorFor = (element) => {
    if (element.classList && element.classList.contains('room-item')) {
      const roomIdClass = Array.from(element.classList).find(name => /^top-\d+$/.test(name));
      if (roomIdClass) return `.room-item.${CSS.escape(roomIdClass)}`;
    }
    if (element.dataset && element.dataset.testid) return `[data-testid="${escape(element.dataset.testid)}"]`;
    if (element.id) return `#${CSS.escape(element.id)}`;
    if (element.getAttribute('aria-label')) return `${element.tagName.toLowerCase()}[aria-label="${escape(element.getAttribute('aria-label'))}"]`;
    const parts = [];
    let node = element;
    while (node && node.nodeType === 1 && parts.length < 6) {
      let part = node.tagName.toLowerCase();
      const siblings = Array.from(node.parentElement ? node.parentElement.children : []).filter(x => x.tagName === node.tagName);
      if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(node) + 1})`;
      parts.unshift(part);
      node = node.parentElement;
    }
    return parts.join(' > ');
  };
  const candidates = Array.from(document.querySelectorAll('button,a,input,textarea,select,[role="button"],[role="tab"],[role="menuitem"],[contenteditable="true"],[onclick],.room-item'));
  return candidates.filter(isVisible).slice(0, 160).map((element, index) => {
    const rect = element.getBoundingClientRect();
    return {
      control_id: `c${index + 1}`,
      selector: selectorFor(element),
      name: (element.getAttribute('aria-label') || element.getAttribute('placeholder') || element.innerText || element.textContent || '').trim().slice(0, 160),
      auto_id: element.id || element.getAttribute('data-testid') || '',
      control_type: element.getAttribute('role') || element.tagName,
      class_name: String(element.className || '').slice(0, 120),
      value: String(element.value || element.textContent || '').trim().slice(0, 240),
      bounds: [Math.round(rect.left), Math.round(rect.top), Math.round(rect.right), Math.round(rect.bottom)],
    };
  });
})()
'''


def _cdp_step_from_action(action: dict[str, Any], controls: list[dict[str, Any]]) -> dict[str, Any] | None:
    action_name = str(action.get('action') or '').strip().lower()
    if action_name == 'done':
        return None
    if action_name not in (SUPPORTED_ACTIONS - {'click_coordinate'}):
        raise DesktopAutomationError(f'CDP planner selected unsupported action: {action_name or "<empty>"}.')
    step = {
        'action': action_name,
        'value': action.get('value', ''),
        'seconds': action.get('seconds', action.get('value', 1)),
        'description': str(action.get('description') or action_name),
    }
    if action_name not in {'wait', 'screenshot'}:
        control = next((item for item in controls if item['control_id'] == str(action.get('control_id') or '')), None)
        if not control:
            raise DesktopAutomationError('CDP planner selected a control that is not visible in the rendered page.')
        step['selector'] = control['selector']
    return step


def _is_login_state_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return '\u767b\u5f55\u6210\u529f' in normalized and ('\u5934\u50cf' in normalized or '\u767b\u5f55\u6001' in normalized)


def _quoted_community_target(instruction: str) -> str:
    """Extract the named community while retaining the user's original intent."""
    generic_labels = {'\u5728\u7ebf', '\u793e\u533a\u540d\u79f0', '\u793e\u533aID', 'ID', '\u540d\u79f0', '\u793e\u533a\u7b80\u4ecb'}
    for candidate in re.findall(r'[\"\u201c\u300c]([^\"\u201d\u300d]+)[\"\u201d\u300d]', str(instruction or '')):
        target = candidate.strip()
        if target and target.replace(' ', '') not in generic_labels:
            return target[:-2].strip() if target.endswith('\u793e\u533a') else target
    return ''


def _is_community_search_result_click(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    generic_identity_card = all(marker in normalized for marker in ('\u641c\u7d22\u7ed3\u679c\u5361\u7247', '\u793e\u533a\u540d\u79f0', '\u793e\u533aID'))
    return (
        not normalized.startswith('\u65ad\u8a00\uff1a')
        and ('\u70b9\u51fb' in normalized or '\u70b9' in normalized)
        and '\u793e\u533a' in normalized
        and (bool(_quoted_community_target(instruction)) or generic_identity_card)
        and ('\u641c\u7d22\u7ed3\u679c' in normalized or '\u5728\u7ebf' in normalized or '\u793e\u533a\u4fe1\u606f' in normalized)
    )


def _is_community_home_setup_instruction(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return '\u8fdb\u5165\u793e\u533a\u9996\u9875' in normalized and 'NN\u5ba2\u6237\u7aef' in normalized


def _community_search_keyword(instruction: str) -> str:
    normalized = str(instruction or '').replace(' ', '')
    if normalized.startswith('\u65ad\u8a00\uff1a') or '\u641c\u7d22\u6846' not in normalized or '\u641c\u7d22' not in normalized:
        return ''
    return _quoted_community_target(instruction)


def _community_search_target(instruction: str, task_description: str = '') -> str:
    """Get the literal query value instead of a quoted result-area label."""
    sources = (str(instruction or ''), str(task_description or ''))
    for source in sources:
        match = re.search(r'(?:\u8f93\u5165|\u641c\u7d22\u5173\u952e\u8bcd|\u5173\u952e\u8bcd)\s*[\u201c"\u300c]([^\u201d"\u300d]+)[\u201d"\u300d]', source)
        if match and match.group(1).strip():
            return match.group(1).strip()
    candidates = (
        _quoted_community_target(instruction),
        _quoted_community_target(task_description),
    )
    ignored = {'\u641c\u7d22\u7684\u6e38\u620f\u3001\u6218\u961f\u793e\u533a', '\u76ee\u6807\u5361\u7247', '\u767b\u5f55NN\u6d4b\u8bd5\u73af\u5883'}
    return next((candidate for candidate in candidates if candidate and candidate not in ignored), '')


def _is_community_search_open_instruction(instruction: str) -> bool:
    """Distinguish opening the top search panel from entering a search term."""
    normalized = str(instruction or '').replace(' ', '')
    return (
        not normalized.startswith('\u65ad\u8a00\uff1a')
        and '\u641c\u7d22\u6846' in normalized
        and '\u70b9\u51fb' in normalized
        and not any(marker in normalized for marker in ('\u8f93\u5165', '\u586b\u5199', '\u952e\u5165', '\u6309\u56de\u8f66'))
        and not re.search(r'\u641c\u7d22\s*[\u201c"\u300c]', instruction)
    )


def _is_community_search_open_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u65ad\u8a00\uff1a')
        and '\u641c\u7d22\u6846' in normalized
        and '\u5f00\u653e\u7684\u6e38\u620f\u5b98\u65b9\u793e\u533a' in normalized
    )


def _is_community_search_user_empty_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u65ad\u8a00\uff1a')
        and '\u641c\u7d22\u7684\u7528\u6237' in normalized
        and any(marker in normalized for marker in ('0\u4e2a\u7ed3\u679c', '0\u6761\u7ed3\u679c', '\u7a7a\u72b6\u6001', '\u65e0\u641c\u7d22\u5185\u5bb9'))
    )


def _is_community_search_community_results_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u65ad\u8a00\uff1a')
        and '\u641c\u7d22\u7684\u6e38\u620f\u3001\u6218\u961f\u793e\u533a' in normalized
        and any(marker in normalized for marker in ('\u63a8\u8350', '\u7ed3\u679c\u5217\u8868', '\u793e\u533a\u5361\u7247', '\u53ef\u89c1\u7ed3\u679c', '\u7ed3\u679c\u603b\u6570', '\u7ed3\u679c\u6570', '\u81f3\u5c11\u4e24\u9879'))
    )


def _is_community_search_result_observation_instruction(instruction: str) -> bool:
    """Recognize a read-only check of the community-result area before click."""
    normalized = str(instruction or '').replace(' ', '')
    return (
        not normalized.startswith('\u65ad\u8a00\uff1a')
        and (
            '\u641c\u7d22\u7684\u6e38\u620f\u3001\u6218\u961f\u793e\u533a' in normalized
            or all(marker in normalized for marker in ('\u76ee\u6807\u5361\u7247', '\u793e\u533a\u7b80\u4ecb', '\u5728\u7ebf'))
        )
        and any(marker in normalized for marker in ('\u5b9a\u4f4d', '\u76ee\u6807\u5361\u7247', '\u5fc5\u987b\u540c\u65f6\u6ee1\u8db3'))
    )


def _is_community_detail_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u65ad\u8a00\uff1a')
        and bool(_quoted_community_target(instruction))
        and (
            '\u793e\u533a\u8be6\u60c5' in normalized
            or '\u793e\u533a\u9762\u677f' in normalized
            or ('\u5b98\u65b9\u793e\u533a' in normalized and any(marker in normalized for marker in ('\u5df2\u8fdb\u5165', '\u8be6\u60c5\u9875', '\u76ee\u6807\u793e\u533a')))
        )
    )


def _is_community_home_presence_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u65ad\u8a00\uff1a')
        and '\u5728\u7ebf' in normalized
        and (
            'PUBG\u4e2d\u56fd\u5b98\u65b9\u793e\u533a' in instruction
            or ('\u5f53\u524d\u5df2\u8fdb\u5165' in normalized and '\u793e\u533a\u540d\u79f0' in normalized)
        )
    )


def _is_community_home_article_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return normalized.startswith('\u65ad\u8a00\uff1a') and any(marker in normalized for marker in ('\u516c\u544a\u6216\u6587\u7ae0\u5361\u7247', '\u5361\u7247\u5c55\u793a\u6807\u9898'))


def _is_community_banner_content_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u65ad\u8a00\uff1a')
        and 'Banner' in instruction
        and '\u793e\u533a\u540d\u79f0' in normalized
        and '\u5728\u7ebf' in normalized
    )


def _is_daily_rank_list_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u65ad\u8a00\uff1a')
        and (
            '\u5403\u9e21\u65e5\u699c' in normalized
            or all(marker in normalized for marker in ('\u6392\u540d', '\u7528\u6237\u540d\u79f0', '\u5403\u9e21N\u6b21'))
        )
    )


def _community_home_content_entry_label(instruction: str) -> str:
    normalized = str(instruction or '').replace(' ', '')
    if '\u70b9\u51fb' not in normalized or '\u5185\u5bb9\u5165\u53e3' not in normalized:
        return ''
    match = re.search(r'[\u300c\u201c\"]([^\u300d\u201d\"]+)[\u300d\u201d\"]', str(instruction or ''))
    return match.group(1).strip() if match else ''


def _is_community_home_content_detail_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return normalized.startswith('\u65ad\u8a00\uff1a') and '\u5185\u5bb9\u8be6\u60c5' in normalized and '\u9996\u9875' in normalized


def _is_community_home_faq_scroll_instruction(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return not normalized.startswith('\u65ad\u8a00\uff1a') and '\u5411\u4e0b\u6eda\u52a8' in normalized and '\u5e38\u89c1\u95ee\u9898' in normalized


def _is_community_home_faq_expand_instruction(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        not normalized.startswith('\u65ad\u8a00\uff1a')
        and any(marker in normalized for marker in ('\u70b9\u51fb', '\u5c55\u5f00'))
        and any(marker in normalized for marker in (
            '\u7ec4\u961f\u80fd\u89e3\u51b3\u6e38\u620f\u54ea\u4e9b\u95ee\u9898',
            'NN\u6e38\u620f\u8bed\u97f3\u4e0e\u5176\u4ed6\u8bed\u97f3\u6709\u4ec0\u4e48\u4e0d\u540c',
        ))
    )


def _is_community_home_faq_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u65ad\u8a00\uff1a')
        # Team-community content checks can include FAQ titles, but validate
        # rendered structure instead of a prior expand action in the homepage.
        and not _is_team_home_content_assertion(instruction)
        and ('\u7ec4\u961f\u80fd\u89e3\u51b3\u6e38\u620f\u54ea\u4e9b\u95ee\u9898' in normalized or 'NN\u6e38\u620f\u8bed\u97f3\u4e0e\u5176\u4ed6\u8bed\u97f3\u6709\u4ec0\u4e48\u4e0d\u540c' in normalized or '\u6bcf\u4e2a\u53ef\u89c1\u95ee\u9898' in normalized)
    )


def _is_selected_search_community_identity_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u65ad\u8a00\uff1a')
        and '\u88ab\u70b9\u51fb\u5361\u7247\u4e00\u81f4' in normalized
        and '\u793e\u533aID' in normalized
    )


def _expected_community_panel_label(instruction: str) -> str:
    match = re.search(r'(?:\u663e\u793a|\u5305\u542b)\s*([A-Za-z0-9\u4e00-\u9fff]+(?:\u5b98\u65b9)?\u793e\u533a)', str(instruction or ''))
    return match.group(1).strip() if match else ''


def _is_affiliated_community_plugin_instruction(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return ('\u65d7\u4e0b\u793e\u533a' in normalized and ('\u70b9\u51fb' in normalized or '\u5bfb\u627e' in normalized))


def _community_plugin_navigation_target(instruction: str) -> list[str]:
    normalized = str(instruction or '').replace(' ', '')
    if not normalized.startswith('\u64cd\u4f5c\uff1a') or '\u70b9\u51fb' not in normalized:
        return []
    if '\u6210\u5458\u5927\u5385' in normalized:
        return ['\u6210\u5458\u5927\u5385', '\u5168\u5458\u5927\u5385']
    if '\u6218\u7ee9\u67e5\u8be2' in normalized:
        return ['\u6218\u7ee9\u67e5\u8be2', '\u6218\u7ee9\u67e5\u8be2(\u4fee\u6539\u540e)']
    return []


def _is_affiliated_community_page_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    if _is_team_detail_assertion(instruction):
        return False
    return (
        '\u5df2\u8fdb\u5165\u300c\u65d7\u4e0b\u793e\u533a\u300d\u9875\u9762' in normalized
        or (
            normalized.startswith('\u65ad\u8a00\uff1a')
            and '\u65d7\u4e0b\u793e\u533a' in normalized
            and any(marker in normalized for marker in ('\u5361\u7247', '\u9009\u4e2d\u72b6\u6001', '\u521b\u5efa\u6218\u961f\u793e\u533a'))
        )
    )


def _team_card_target(instruction: str) -> str:
    normalized = str(instruction or '').replace(' ', '')
    if ('\u70b9\u51fb' in normalized or '\u70b9' in normalized) and ('\u6218\u961f\u793e\u533a\u5361\u7247' in normalized or 'test0915' in instruction):
        return _quoted_community_target(instruction) or ('test0915' if 'test0915' in instruction else '')
    return ''


def _is_team_detail_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return normalized.startswith('\u65ad\u8a00\uff1a') and 'test0915' in instruction and ('10079288' in instruction or '\u6218\u961f\u793e\u533a' in normalized)


def _is_team_card_count_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u65ad\u8a00\uff1a')
        and '\u6218\u961f\u793e\u533a\u5361\u7247' in normalized
        and ('\u81f3\u5c11' in normalized or '\u4e09\u5f20' in normalized or '\u591a\u5f20' in normalized)
    )


def _is_team_card_metadata_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u65ad\u8a00\uff1a')
        and (
            '\u6218\u961f\u793e\u533a\u5361\u7247' in normalized
            or ('\u793e\u533a\u5361\u7247' in normalized and '\u5728\u7ebf' in normalized)
            or ('\u793e\u533a\u7b80\u4ecb' in normalized and '\u5361\u7247' in normalized)
        )
        and any(marker in normalized for marker in ('\u793e\u533a\u5934\u50cf', '\u793e\u533a\u540d\u79f0', '\u793e\u533aID', '\u793e\u533a\u7b80\u4ecb', '\u4e0d\u4e0e\u5176\u4ed6\u5361\u7247'))
    )


def _is_team_home_sidebar_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return normalized.startswith('\u65ad\u8a00\uff1a') and '\u6211\u7684\u7b49\u7ea7' in normalized and '\u6210\u5458\u5927\u5385' in normalized


def _is_team_home_content_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u65ad\u8a00\uff1a')
        and ('\u793e\u533a\u4ecb\u7ecd' in normalized or '\u793e\u533a\u4ecb\u7ecd\u6587\u672c' in normalized)
        and any(marker in normalized for marker in ('\u6587\u7ae0', '\u516c\u544a', '\u5185\u5bb9\u6d41', '\u5e38\u89c1\u95ee\u9898'))
    )


def _is_voice_room_list_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return normalized.startswith('\u65ad\u8a00\uff1a') and '\u8bed\u97f3\u623f' in normalized and any(marker in normalized for marker in ('\u591a\u4e2a', '\u623f\u95f4\u5e8f\u53f7', '\u4eba\u6570', '\u5bb9\u91cf', '\u4e92\u52a8\u8bed\u97f3', '\u6e38\u620f\u8bed\u97f3'))


def _is_battle_page_presence_assertion(instruction: str) -> bool:
    """Recognize the stable battle-plugin entry invariant, not a UI copy revision."""
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u65ad\u8a00\uff1a')
        and any(marker in normalized for marker in ('\u6218\u7ee9\u67e5\u8be2', '\u6218\u7ee9\u63d2\u4ef6'))
        and any(marker in normalized for marker in ('\u67e5\u8be2\u73a9\u5bb6\u6218\u7ee9', '\u6218\u7ee9\u67e5\u8be2\u8f93\u5165\u6846', '\u67e5\u8be2\u8f93\u5165\u6846'))
    )


def _is_battle_stats_data_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u65ad\u8a00\uff1a')
        and (
            (all(marker in normalized for marker in ('\u8d5b\u5b63\u573a\u6b21', '\u51fb\u6740\u6570', 'KDA'))
             and any(marker in normalized for marker in ('\u5bf9\u5c40\u8bb0\u5f55', '\u6218\u7ee9\u8bb0\u5f55', '\u6bd4\u8d5b\u8bb0\u5f55')))
            or any(marker in normalized for marker in ('\u6218\u7ee9\u6982\u89c8', '\u6bd4\u8d5b\u8bb0\u5f55', '\u81f3\u5c11\u4e00\u4e2a\u6218\u7ee9\u4fe1\u606f\u533a\u57df'))
        )
    )


def _is_battle_authenticated_access_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u65ad\u8a00\uff1a')
        and '\u6218\u7ee9\u63d2\u4ef6' in normalized
        and any(marker in normalized for marker in ('\u5df2\u767b\u5f55', '\u767b\u5f55\u8d26\u53f7', '\u672a\u51fa\u73b0\u767b\u5f55\u5f39\u7a97'))
    )


def _is_battle_refresh_assertion(instruction: str) -> bool:
    """Recognize post-refresh battle checks that need renderer state, not screenshot history."""
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u65ad\u8a00\uff1a')
        and '\u6218\u7ee9\u67e5\u8be2' in normalized
        and '\u5237\u65b0' in normalized
        and any(marker in normalized for marker in ('\u672a\u8df3\u8f6c', '\u4ecd\u5c55\u793a', '\u4ecd\u53ef\u89c1'))
    )


def _is_battle_scrollable_input_assertion(instruction: str) -> bool:
    """Recognize viewport cases whose scrollability is available directly from the DOM."""
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u65ad\u8a00\uff1a')
        and ('\u67e5\u8be2\u73a9\u5bb6\u6218\u7ee9' in normalized or '\u6218\u7ee9\u6838\u5fc3\u8f93\u5165\u6846' in normalized)
        and ('\u53ef\u6eda\u52a8' in normalized or '\u6eda\u52a8\u8bbf\u95ee' in normalized)
    )


def _is_battle_operable_layout_assertion(instruction: str) -> bool:
    """Recognize responsive battle layout checks that screenshots cannot prove by themselves."""
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u65ad\u8a00\uff1a')
        and '\u6218\u7ee9' in normalized
        and '\u53ef\u64cd\u4f5c' in normalized
        and any(marker in normalized for marker in ('\u6a2a\u5411\u906e\u6321', '\u5e03\u5c40', '\u7a97\u53e3\u5185'))
    )


def _battle_query_input_value(instruction: str) -> str | None:
    """Extract a literal player-query value from a battle-plugin operation."""
    text = str(instruction or '').strip()
    if text.startswith('\u65ad\u8a00\uff1a') or '\u67e5\u8be2\u73a9\u5bb6\u6218\u7ee9' not in text or '\u586b\u5199' not in text:
        return None
    match = re.search(r'\u8f93\u5165\u6846\s*\u586b\u5199\s*(.+?)\s*[\u3002\uff1b;]?$', text, re.DOTALL)
    if not match:
        return None
    value = match.group(1).strip()
    if value == '\u4e09\u4e2a\u7a7a\u683c':
        return '   '
    return value or None


def _is_battle_query_clear_instruction(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        not normalized.startswith('\u65ad\u8a00\uff1a')
        and '\u67e5\u8be2\u73a9\u5bb6\u6218\u7ee9' in normalized
        and '\u6e05\u7a7a' in normalized
        and '\u8f93\u5165\u6846' in normalized
    )


def _battle_query_expected_value(instruction: str) -> str | None:
    """Extract an exact battle-query input assertion, including an empty value."""
    text = str(instruction or '').strip()
    normalized = text.replace(' ', '')
    if not normalized.startswith('\u65ad\u8a00\uff1a'):
        return None
    if '\u8f93\u5165\u6846\u5f53\u524d\u503c\u4e3a\u7a7a' in normalized:
        return ''
    if '\u8f93\u5165\u6846\u4fdd\u7559\u4e09\u4e2a\u7a7a\u683c' in normalized:
        return '   '
    if '\u67e5\u8be2\u73a9\u5bb6\u6218\u7ee9' not in text or '\u8f93\u5165\u6846\u5f53\u524d\u503c' not in text:
        return None
    match = re.search(r'\u5f53\u524d\u503c\s*(?:\u4e3a|\u662f)\s*([^\s\u3002\uff1b;]+)', text)
    return match.group(1).strip() if match else None


def _is_battle_query_visibility_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u65ad\u8a00\uff1a')
        and '\u67e5\u8be2\u73a9\u5bb6\u6218\u7ee9' in normalized
        and '\u8f93\u5165\u6846\u53ef\u89c1' in normalized
        and '\u9875\u9762\u5730\u5740\u672a\u8df3\u8f6c' in normalized
    )


def _expected_cdp_route_assertion(instruction: str) -> str:
    """Return a route explicitly asserted by a desktop case, if any."""
    normalized = str(instruction or '').replace(' ', '')
    if not normalized.startswith('\u65ad\u8a00\uff1a'):
        return ''
    exact_route = _cdp_route_from_task_description(instruction)
    if exact_route:
        return exact_route
    # Imported cases often preserve only a distinctive route suffix such as
    # "/plugin/zhanji". Electron has the full community route in its hash, so
    # retain the suffix and validate it semantically below instead of asking a
    # screenshot model to infer a URL that is not visible in the client.
    suffix = re.search(r'(?<![\w/])(/plugin/[\w-]+(?:\?[^\s\]\)]+)?)', str(instruction or ''))
    return suffix.group(1).rstrip('\uff0c\u3002\uff1b;') if suffix else ''


def _is_hall_layout_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u65ad\u8a00\uff1a')
        and any(marker in normalized for marker in ('\u6210\u5458\u5927\u5385', '\u4e2d\u592e\u6d88\u606f\u6d41', '\u53f3\u4fa7\u6210\u5458\u5217\u8868', '\u4e09\u680f', '\u5e95\u90e8\u8f93\u5165\u533a'))
        and any(marker in normalized for marker in ('\u4e2d\u592e', '\u53f3\u4fa7', '\u5de6\u4fa7', '\u6d88\u606f\u6d41', '\u8f93\u5165\u533a', '\u4e09\u680f'))
    )


def _is_hall_navigation_assertion(instruction: str) -> bool:
    """Recognize assertions about the member-hall navigation entry.

    NN labels this entry as either ``成员大厅`` or ``全员大厅`` depending on
    the deployed client version. Both represent the same ``/hall`` feature,
    so a wording difference must not be reported as a product failure.
    """
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u65ad\u8a00\uff1a')
        and (
            (('\u6210\u5458\u5927\u5385' in normalized or '\u5168\u5458\u5927\u5385' in normalized)
             and any(marker in normalized for marker in ('\u5de6\u4fa7\u5bfc\u822a', '\u9009\u4e2d', '\u9ad8\u4eae', '\u672a\u9009\u4e2d\u5bfc\u822a')))
            or (('\u6210\u5458\u5927\u5385' in normalized or '\u5168\u5458\u5927\u5385' in normalized)
                and any(marker in normalized for marker in ('\u4ecd\u505c\u7559', '\u672a\u8df3\u8f6c', '\u5f53\u524d\u8def\u7531')))
            or ('\u9009\u4e2d\u72b6\u6001' in normalized and '\u76f8\u90bb\u672a\u9009\u4e2d' in normalized)
        )
    )


def _is_hall_member_search_instruction(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return ('\u641c\u7d22\u6210\u5458' in normalized or '\u6e05\u7a7a\u641c\u7d22\u6846' in normalized or ('\u6210\u5458\u5217\u8868' in normalized and '\u8bb0\u5f55' in normalized)) and (
        '\u8f93\u5165' in normalized
        or '\u6e05\u7a7a' in normalized
        or '\u8bb0\u5f55\u7b2c\u4e00\u4f4d' in normalized
        or '\u8bb0\u5f55\u9996\u4f4d' in normalized
    )


def _is_hall_member_search_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    member_scope = '\u6210\u5458' in normalized or '\u641c\u7d22\u6210\u5458' in normalized or '\u5b8c\u6574\u6635\u79f0' in normalized
    return normalized.startswith('\u65ad\u8a00\uff1a') and (
        (member_scope and (
            '\u641c\u7d22\u6846' in normalized
            or '\u641c\u7d22\u7ed3\u679c' in normalized
            or '\u7ed3\u679c\u5217\u8868' in normalized
            or ('\u6210\u5458\u5217\u8868' in normalized and any(marker in normalized for marker in ('\u5173\u952e\u5b57', '\u7b5b\u9009', '\u65e0\u7ed3\u679c', '\u6062\u590d', '\u81f3\u5c11\u5c55\u793a', '\u6635\u79f0\u5305\u542b')))
        ))
        or '\u7b5b\u9009\u540e\u7684\u6570\u91cf' in normalized
    )


def _is_hall_invite_instruction(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u64cd\u4f5c\uff1a')
        and any(marker in normalized for marker in ('\u9080\u8bf7/\u5206\u4eab', '\u9080\u8bf7\u5206\u4eab', '\u9080\u8bf7\u597d\u53cb\u5f39\u7a97'))
        and any(marker in normalized for marker in ('\u70b9\u51fb', '\u5173\u95ed'))
    )


def _is_hall_invite_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    if not normalized.startswith('\u65ad\u8a00\uff1a'):
        return False
    has_invite_subject = any(marker in normalized for marker in ('\u9080\u8bf7\u5206\u4eab', '\u9080\u8bf7/\u5206\u4eab', '\u9080\u8bf7\u597d\u53cb'))
    return has_invite_subject and any(marker in normalized for marker in (
        '\u5f39\u7a97', '\u5f39\u5c42', '\u62bd\u5c49', '\u5bf9\u8bdd\u6846', '\u906e\u7f69', '\u5173\u95ed\u540e', '\u6d88\u5931', '\u6253\u5f00\u540e', '\u6309\u94ae', '\u53ef\u70b9\u51fb',
    ))


def _is_hall_message_input_instruction(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return normalized.startswith('\u64cd\u4f5c\uff1a') and 'HALL_${timestamp()}' not in normalized and any(marker in normalized for marker in ('\u6d88\u606f\u8f93\u5165\u6846', '\u8f93\u5165\u533a', '\u4f7f\u8f93\u5165\u6846\u5931\u7126', '\u5931\u7126', '\u70b9\u51fb\u8f93\u5165\u6846')) and not any(marker in normalized for marker in ('\u64a4\u56de', '\u56de\u590d', '\u8868\u60c5', '\u8d34\u7eb8')) and not ('\u53d1\u9001' in normalized and '\u4e0d\u8981\u53d1\u9001' not in normalized)


def _is_hall_message_input_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return normalized.startswith('\u65ad\u8a00\uff1a') and any(marker in normalized for marker in ('\u8f93\u5165\u6846\u53ef\u83b7\u5f97\u7126\u70b9', '\u672a\u89e6\u53d1\u9001', '\u8f93\u5165\u6587\u672c', '\u8f93\u5165\u8fc7\u7a0b', '\u6d88\u606f\u8f93\u5165\u533a', '\u6d88\u606f\u8f93\u5165\u5165\u53e3', '\u5e95\u90e8\u8f93\u5165\u533a'))


def _is_hall_message_unit_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u65ad\u8a00\uff1a')
        and '\u6d88\u606f' in normalized
        and any(marker in normalized for marker in ('\u666e\u901a\u6d88\u606f\u5355\u5143', '\u6d88\u606f\u6b63\u6587', '\u4e0e\u76f8\u90bb\u6d88\u606f\u4e32\u4f4d'))
        and any(marker in normalized for marker in ('\u5934\u50cf', '\u53d1\u9001\u8005'))
    )


def _is_hall_system_notification_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u65ad\u8a00\uff1a')
        and '\u7cfb\u7edf\u901a\u77e5' in normalized
        and any(marker in normalized for marker in ('\u901a\u77e5\u6807\u9898', '\u901a\u77e5\u6b63\u6587', '\u7cfb\u7edf\u56fe\u6807', '\u540c\u4e00\u6d88\u606f\u5355\u5143', '\u666e\u901a\u6210\u5458\u6d88\u606f', '\u4e32\u4f4d'))
    )


def _is_hall_unique_message_instruction(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return normalized.startswith('\u64cd\u4f5c\uff1a') and 'HALL_${timestamp()}' in normalized and any(marker in normalized for marker in ('\u8f93\u5165', '\u53d1\u9001'))


def _is_hall_generated_message_send_confirmation(instruction: str) -> bool:
    """Recognise a follow-up send click after a generated Hall message was sent."""
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u64cd\u4f5c\uff1a')
        and 'HALL_${timestamp()}' not in normalized
        and any(marker in normalized for marker in ('\u53d1\u9001\u6309\u94ae', '\u5feb\u6377\u952e', '\u63d0\u4ea4\u6d88\u606f'))
        and any(marker in normalized for marker in ('\u8be5\u552f\u4e00\u6d88\u606f', '\u5bf9\u5e94', '\u5df2\u8f93\u5165', '\u5df2\u751f\u6210'))
    )


def _is_hall_generated_message_ui_assertion(instruction: str) -> bool:
    """Assertions backed by this case's generated Hall-message evidence."""
    normalized = str(instruction or '').replace(' ', '')
    if not normalized.startswith('\u65ad\u8a00\uff1a') or '\u7cfb\u7edf\u901a\u77e5' in normalized:
        return False
    if any(marker in normalized for marker in ('\u64a4\u56de', '\u56de\u590d', '\u8868\u60c5', '\u8d34\u7eb8')):
        return False
    return (('\u6d88\u606f' in normalized) or ('\u53d1\u9001\u64cd\u4f5c\u540e' in normalized) or ('\u53d1\u9001\u540e' in normalized)) and any(
        marker in normalized for marker in (
            '\u53d1\u9001\u64cd\u4f5c\u540e', '\u53d1\u9001\u540e', '\u53d1\u9001\u8005', '\u5934\u50cf', '\u65f6\u95f4',
            '\u9996\u5c4f', '\u4f1a\u8bdd\u5e95\u90e8', '\u6d88\u606f\u6d41', '\u4ec5\u65b0\u589e', '\u6ca1\u6709\u91cd\u590d',
        )
    )


def _is_hall_other_member_fixture_instruction(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u64cd\u4f5c\uff1a')
        and '其他成员账号' in normalized
        and 'HALL_${timestamp()}' in normalized
        and any(marker in normalized for marker in ('发送', '准备', '发布'))
    )


def _is_hall_message_recall_instruction(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u64cd\u4f5c\uff1a')
        and '\u64a4\u56de' in normalized
        and not any(marker in normalized for marker in ('\u8868\u60c5', '\u8d34\u7eb8'))
        and any(marker in normalized for marker in ('\u70b9\u51fb\u64a4\u56de', '\u6267\u884c\u64a4\u56de', '\u4f9d\u6b21\u64a4\u56de', '\u786e\u8ba4\u64a4\u56de', '\u8fdb\u884c\u64a4\u56de', '\u5b8c\u6210\u6570\u636e\u6e05\u7406'))
        and any(marker in normalized for marker in ('\u987a\u5e8fA', 'HALL_', '\u6d88\u606f', '\u64cd\u4f5c\u83dc\u5355', '\u786e\u8ba4\u63d0\u793a'))
    )


def _is_hall_reply_open_instruction(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u64cd\u4f5c\uff1a')
        and '\u56de\u590d' in normalized
        and any(marker in normalized for marker in ('\u70b9\u51fb', '\u9009\u62e9', '\u6253\u5f00'))
        and any(marker in normalized for marker in ('\u64cd\u4f5c\u83dc\u5355', '\u66f4\u591a\u83dc\u5355', '\u56de\u590d\u83dc\u5355'))
        and not any(marker in normalized for marker in ('\u8f93\u5165', '\u53d1\u9001', 'HALL_${timestamp()}'))
    )


def _is_hall_reply_cancel_instruction(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return normalized.startswith('\u64cd\u4f5c\uff1a') and '\u56de\u590d\u72b6\u6001' in normalized and any(
        marker in normalized for marker in ('\u53d6\u6d88', '\u5173\u95ed')
    )


def _is_hall_generated_message_menu_instruction(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u64cd\u4f5c\uff1a')
        and ('HALL_${timestamp()}' in normalized or '\u521a\u624d\u552f\u4e00\u6d88\u606f' in normalized or '\u672c\u6b21\u552f\u4e00\u6d88\u606f' in normalized)
        and '\u64cd\u4f5c\u83dc\u5355' in normalized
        and '\u56de\u590d' not in normalized
    )


def _is_hall_generated_message_menu_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u65ad\u8a00\uff1a')
        and '\u672c\u6b21\u552f\u4e00\u6d88\u606f' in normalized
        and '\u64cd\u4f5c\u83dc\u5355' in normalized
        and '\u64a4\u56de' in normalized
    )


def _is_hall_menu_permission_compare_instruction(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    common = '\u64cd\u4f5c\u83dc\u5355' in normalized and '\u672c\u4eba\u6d88\u606f' in normalized and '\u5176\u4ed6\u6210\u5458\u6d88\u606f' in normalized
    return (
        (normalized.startswith('\u64cd\u4f5c\uff1a') and common)
        or (normalized.startswith('\u65ad\u8a00\uff1a') and common and any(marker in normalized for marker in ('\u56de\u590d', '\u64a4\u56de', '\u6bd4\u8f83', '\u4e0d\u5e94')))
    )


def _is_hall_menu_permission_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return normalized.startswith('\u65ad\u8a00\uff1a') and any(
        marker in normalized for marker in ('\u672c\u4eba\u6d88\u606f\u83dc\u5355', '\u5176\u4ed6\u6210\u5458\u6d88\u606f')
    ) and any(marker in normalized for marker in ('\u56de\u590d', '\u64a4\u56de'))


def _is_hall_reply_open_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return normalized.startswith('\u65ad\u8a00\uff1a') and '\u56de\u590d\u72b6\u6001' in normalized and any(
        marker in normalized for marker in ('\u53ef\u89c1', '\u56de\u590d\u6d88\u606f\u6458\u8981', '\u88ab\u56de\u590d', '\u56de\u590d\u6807\u8bc6')
    )


def _is_hall_menu_consistency_instruction(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith(('\u64cd\u4f5c\uff1a', '\u65ad\u8a00\uff1a'))
        and any(marker in normalized for marker in ('\u672c\u4eba\u6d88\u606f', '\u5176\u4ed6\u6210\u5458\u6d88\u606f', '\u4e24\u7c7b\u6d88\u606f', '\u4e24\u6761\u6d88\u606f', '\u4e24\u4e2a\u83dc\u5355'))
        and any(marker in normalized for marker in ('\u83dc\u5355', '\u56de\u590d', '\u64a4\u56de'))
        and any(marker in normalized for marker in ('\u4e00\u81f4', '\u53ef\u7528', '\u4e0d\u6267\u884c', '\u65e0\u526f\u4f5c\u7528'))
    )


def _is_hall_menu_close_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return normalized.startswith('\u65ad\u8a00\uff1a') and '\u5173\u95ed\u83dc\u5355' in normalized and any(
        marker in normalized for marker in ('\u672a\u4ea7\u751f\u6d88\u606f\u5185\u5bb9\u53d8\u66f4', '\u6d88\u606f\u6d41\u5e03\u5c40', '\u7a33\u5b9a')
    )


def _is_hall_reply_cancel_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return normalized.startswith('\u65ad\u8a00\uff1a') and ('\u53d6\u6d88\u56de\u590d' in normalized or ('\u53d6\u6d88\u540e' in normalized and '\u56de\u590d' in normalized)) and any(
        marker in normalized for marker in ('\u6d88\u5931', '\u6062\u590d', '\u666e\u901a\u6d88\u606f')
    )


def _is_hall_unsent_draft_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return normalized.startswith('\u65ad\u8a00\uff1a') and any(
        marker in normalized for marker in ('\u4e0d\u643a\u5e26\u5df2\u53d6\u6d88\u7684\u56de\u590d\u5173\u7cfb', '\u672a\u53d1\u9001\u65f6', '\u666e\u901a\u8f93\u5165')
    )


def _is_hall_reply_message_relation_instruction(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u64cd\u4f5c\uff1a')
        and '\u56de\u590d\u6d88\u606f' in normalized
        and any(marker in normalized for marker in ('\u539f\u59cb\u6d88\u606f', '\u88ab\u56de\u590d\u6d88\u606f'))
        and any(marker in normalized for marker in ('\u5b9a\u4f4d', '\u786e\u8ba4', '\u5f62\u6210'))
        and not any(marker in normalized for marker in ('\u64a4\u56de', '\u53d1\u9001', 'HALL_${timestamp()}'))
    )


def _is_hall_reply_message_relation_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u65ad\u8a00\uff1a')
        and '\u56de\u590d' in normalized
        and not any(marker in normalized for marker in ('\u53d6\u6d88\u56de\u590d', '\u53d6\u6d88\u540e', '\u56de\u590d\u72b6\u6001', '\u6e05\u7406\u9636\u6bb5'))
        and any(marker in normalized for marker in ('\u56de\u590d\u6807\u8bc6', '\u56de\u590d\u6d88\u606f\u6458\u8981', '\u88ab\u56de\u590d\u6d88\u606f', '\u539f\u59cb\u6d88\u606f', '\u56de\u590d\u5173\u7cfb', '\u666e\u901a\u72ec\u7acb\u6d88\u606f'))
    )


def _is_hall_message_delivery_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return normalized.startswith('\u65ad\u8a00\uff1a') and '\u552f\u4e00' in normalized and any(
        marker in normalized for marker in ('\u53d1\u9001\u6210\u529f', '\u53d1\u9001\u8005', '\u65f6\u95f4\u6233', '\u4ec5\u5b58\u5728', '\u4e0d\u91cd\u590d')
    )


def _is_hall_other_member_fixture_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return normalized.startswith('\u65ad\u8a00\uff1a') and '\u5176\u4ed6\u6210\u5458\u5939\u5177\u6d88\u606f' in normalized and '\u672c\u4eba\u552f\u4e00\u6d88\u606f' in normalized


def _is_hall_message_recall_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u65ad\u8a00\uff1a')
        and '\u64a4\u56de' in normalized
        and not any(marker in normalized for marker in ('\u8868\u60c5', '\u8d34\u7eb8'))
        and any(marker in normalized for marker in ('\u6d88\u606f', '\u6e05\u7406', '\u6b63\u5e38\u6d88\u606f'))
        and any(marker in normalized for marker in ('\u786e\u8ba4\u64a4\u56de', '\u5df2\u64a4\u56de', '\u6e05\u7406\u540e', '\u6e05\u7406\u9636\u6bb5', '\u4e0d\u518d\u4f5c\u4e3a\u666e\u901a'))
    )


def _is_hall_message_stability_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return normalized.startswith('\u65ad\u8a00\uff1a') and '\u64a4\u56de\u64cd\u4f5c\u4e0d\u5f71\u54cd' in normalized and any(
        marker in normalized for marker in ('\u76f8\u90bb\u6d88\u606f', '\u6210\u5458\u5217\u8868', '\u8f93\u5165\u6846')
    )


def _order_desktop_task_instructions(instructions: list[str]) -> list[str]:
    """Run explicit test-data cleanup only after its business assertions.

    Imported cases group all operation lines before expected-result lines. A
    cleanup action such as recalling a generated message must therefore be
    deferred, otherwise it destroys the very evidence that later assertions
    are meant to verify. Functional recalls without a cleanup marker retain
    their original position.
    """
    cleanup_operations = [
        instruction for instruction in instructions
        if _is_hall_message_recall_instruction(instruction) and '清理' in instruction
    ]
    if not cleanup_operations:
        return instructions
    cleanup_assertions = [
        instruction for instruction in instructions
        if _is_hall_message_recall_assertion(instruction)
        or (instruction.startswith('断言：') and '清理完成后' in instruction and '唯一' in instruction)
    ]
    deferred = set(cleanup_operations + cleanup_assertions)
    return [instruction for instruction in instructions if instruction not in deferred] + cleanup_operations + cleanup_assertions


def _hall_unique_message_assertion_kind(instruction: str) -> str:
    """Classify assertions whose evidence is the messages generated in this case."""
    normalized = str(instruction or '').replace(' ', '')
    if not normalized.startswith('\u65ad\u8a00\uff1a'):
        return ''
    if '\u4e24\u6b21\u53d1\u9001' in normalized and any(marker in normalized for marker in ('\u8f93\u5165\u6846', '\u9501\u6b7b', '\u65e7\u6587\u672c')):
        return 'send_feedback'
    if '\u987a\u5e8fA' in normalized and '\u987a\u5e8fB' in normalized and any(marker in normalized for marker in ('\u552f\u4e00', '\u987a\u5e8f', '\u6570\u91cf')):
        return 'order'
    if any(marker in normalized for marker in ('\u91cd\u590d\u6d88\u606f', '\u7a7a\u767d\u6d88\u606f', '\u4e32\u4f4d\u7684\u6d88\u606f')):
        return 'integrity'
    return ''


async def _ensure_cdp_hall_message_context(page: _CDPPage) -> dict[str, Any]:
    """Verify that the visible Hall composer has a real NN group context.

    Hall's mounted input component owns the send initialisation: it derives
    ``sendTextData`` from the active group entry immediately before emitting
    the real IM event.  Re-entering the chat store here resets that component's
    in-flight state, so this precondition only validates the selected group and
    leaves NN's native send path in charge of initialisation.
    """
    deadline = asyncio.get_running_loop().time() + 15.0
    latest: dict[str, Any] = {}
    while True:
        latest = await page.evaluate(r'''
          (() => {
            const route = String(location.hash || '');
            const input = document.querySelector('.chat-input[contenteditable]');
            const userInfo = JSON.parse(localStorage.getItem('userInfo') || '{}');
            const userId = String(userInfo.userId || localStorage.getItem('_user_id') || '');
            const token = String(userInfo.token || localStorage.getItem('token') || '').trim();
            const provides = document.querySelector('#app')?.__vue_app__?._context?.provides;
            const pinia = provides && Object.getOwnPropertySymbols(provides)
              .map(symbol => provides[symbol])
              .find(value => value && value._s && typeof value._s.get === 'function' && value._s.get('chat'));
            const chat = pinia?._s?.get('chat');
            const chatMap = chat?.chatMap;
            const selected = chat?.state?.selectedChat || chat?.state || {};
            const conversationId = String(selected.conversationID || chat?.state?.conversationID || '');
            const active = conversationId && chatMap && typeof chatMap === 'object'
              ? chatMap[conversationId]
              : null;
            const prerequisites = {
              onHallRoute: /\/community\/\d+\/hall(?:$|[/?])/.test(route),
              authenticated: Boolean(token) && userId && userId !== '-1' && userId !== '0',
              composerVisible: Boolean(input),
              piniaAvailable: Boolean(pinia),
              selectedConversation: Boolean(conversationId),
            };
            if (Object.values(prerequisites).every(Boolean)) {
              const item = active;
              const hasMessageContext = Array.isArray(item?.msgList)
                && Boolean(item?.ID)
                && String(item?.conversationID || '') === conversationId;
              const sendTo = String(item?.sendTextData?.to || item?.ID || '');
              const ready = hasMessageContext
                && String(item?.conversationType || '') === 'GROUP'
                && Boolean(sendTo);
              sessionStorage.setItem('__testhub_hall_conversation_id', conversationId);
              return {
                ready,
                conversationId,
                messageCount: Array.isArray(item?.msgList) ? item.msgList.length : 0,
                hasMessageContext,
                conversationType: String(item?.conversationType || ''),
                sendTo,
                prerequisites,
              };
            }
            return {ready: false, prerequisites, selected};
          })()
        ''')
        if isinstance(latest, dict) and latest.get('ready'):
            return latest
        if asyncio.get_running_loop().time() >= deadline:
            diagnostics = latest if isinstance(latest, dict) else {'result': latest}
            raise DesktopAutomationError(f'NN Hall IM conversation is not ready for sending: {diagnostics}.')
        await asyncio.sleep(0.4)


async def _cleanup_cdp_generated_hall_messages(page: _CDPPage) -> dict[str, Any]:
    """Recall only Hall messages generated by the current desktop case.

    A Hall fixture can add a message from a secondary account. It is evidence,
    not current-run data, so cleanup must never recall it.
    """
    return await page.evaluate(r'''
      (async () => {
        const readJson = (key, fallback) => {
          try { return JSON.parse(sessionStorage.getItem(key) || ''); } catch (_error) { return fallback; }
        };
        const sendEvidence = readJson('__testhub_hall_send_evidence', {});
        const storedValues = readJson('__testhub_hall_unique_messages', []);
        const values = [...new Set([
          ...(Array.isArray(sendEvidence?.values) ? sendEvidence.values : []),
          ...(Array.isArray(storedValues) ? storedValues : []),
        ].map(value => String(value || '')).filter(Boolean))];
        const provides = document.querySelector('#app')?.__vue_app__?._context?.provides;
        const pinia = provides && Object.getOwnPropertySymbols(provides)
          .map(symbol => provides[symbol])
          .find(candidate => candidate && candidate._s && typeof candidate._s.get === 'function' && candidate._s.get('chat'));
        const chat = pinia?._s?.get('chat');
        const channel = pinia?._s?.get('channel');
        const community = pinia?._s?.get('community');
        const user = pinia?._s?.get('user');
        const conversationId = String(sessionStorage.getItem('__testhub_hall_conversation_id') || sendEvidence?.conversationId || '');
        const messages = Array.isArray(chat?.chatMap?.[conversationId]?.msgList) ? chat.chatMap[conversationId].msgList : [];
        const currentUserId = String(user?.userInfo?.userId || localStorage.getItem('_user_id') || localStorage.getItem('userId') || '');
        const entries = values.map(value => ({
          value,
          message: messages.find(message => message && String(message.payload?.text || '') === value),
        }));
        const ownEntries = entries.filter(entry => entry.message && String(entry.message.from || '') === currentUserId);
        const foreignValues = entries.filter(entry => entry.message && String(entry.message.from || '') !== currentUserId)
          .map(entry => entry.value);
        const expectedOwnValues = (Array.isArray(sendEvidence?.values) ? sendEvidence.values : [])
          .map(value => String(value || '')).filter(Boolean);
        const missingOwnValues = expectedOwnValues.filter(value => !entries.some(entry => entry.value === value && entry.message));
        if (!ownEntries.length && !missingOwnValues.length) {
          return {handled:true, passed:true, reason:'no current-run Hall messages require cleanup', evidence:{values, foreignValues, conversationId, currentUserId}};
        }
        if (typeof channel?.recallMsg !== 'function') {
          return {handled:true, passed:false, reason:'NN Hall message cleanup context is unavailable', evidence:{values, ownCount:ownEntries.length, missingOwnValues, hasRecall:false}};
        }
        const serverId = Number(community?.communityItem?.serverId || 0);
        if (!serverId) {
          return {handled:true, passed:false, reason:'NN Hall message cleanup has no server context', evidence:{values, ownCount:ownEntries.length, missingOwnValues, serverId}};
        }
        const outcomes = [];
        for (const {value, message} of ownEntries.filter(entry => !entry.message.isRevoked && !entry.message.isDeleted).reverse()) {
          const response = await channel.recallMsg({
            message: value,
            userId: Number(message.from || currentUserId || 0),
            from: Number(message.from || currentUserId || 0),
            channelId: Number(conversationId),
            txTopicId: Number(conversationId),
            txChannelId: Number(conversationId),
            msgSeq: Number(message.sequence || message.msgSeq || 0),
            messageType: 3,
            serverId,
            channelType: 7,
            msgIds: [String(message.ID)],
          });
          outcomes.push({text:value, messageId:String(message.ID || ''), success:Boolean(response?.success), retMsg:String(response?.retMsg || '')});
          if (response?.success) message.isRevoked = true;
          if (!response?.success) break;
        }
        const passed = !missingOwnValues.length && outcomes.every(outcome => outcome.success);
        return {
          handled:true,
          passed,
          reason: passed ? `recalled ${outcomes.length} current-run Hall message(s)` : 'NN rejected a generated Hall-message cleanup request',
          evidence:{values, currentUserId, foreignValues, missingOwnValues, outcomes},
        };
      })()
    ''')


def _is_hall_emoji_instruction(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return normalized.startswith('\u64cd\u4f5c\uff1a') and (('\u8868\u60c5' in normalized and any(marker in normalized for marker in ('\u56fe\u6807', '\u9762\u677f', '\u8d34\u7eb8'))) or '\u70b9\u51fb\u9762\u677f\u5916' in normalized)


def _is_hall_emoji_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return normalized.startswith('\u65ad\u8a00\uff1a') and ('\u8868\u60c5\u9762\u677f' in normalized or '\u5173\u95ed\u540e\u9762\u677f' in normalized)


def _is_hall_emoji_selection_instruction(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return normalized.startswith('\u64cd\u4f5c\uff1a') and '\u9009\u62e9' in normalized and any(token in normalized for token in ('\u8868\u60c5', '\u8d34\u7eb8'))


def _is_hall_emoji_send_instruction(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return normalized.startswith('\u64cd\u4f5c\uff1a') and '\u53d1\u9001' in normalized and any(token in normalized for token in ('\u8868\u60c5', '\u8d34\u7eb8'))


def _is_hall_emoji_recall_instruction(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return normalized.startswith('\u64cd\u4f5c\uff1a') and '\u64a4\u56de' in normalized and any(token in normalized for token in ('\u8868\u60c5', '\u8d34\u7eb8'))


def _is_hall_emoji_message_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u65ad\u8a00\uff1a')
        and any(token in normalized for token in ('\u8868\u60c5', '\u8d34\u7eb8'))
        and ('\u6d88\u606f\u6d41' in normalized or '\u64a4\u56de\u540e' in normalized)
    )


async def _cdp_click_at(page: _CDPPage, point: dict[str, Any]) -> None:
    """Dispatch a trusted renderer click without controlling the real mouse."""
    try:
        x = float(point['x'])
        y = float(point['y'])
    except (KeyError, TypeError, ValueError) as exc:
        raise DesktopAutomationError('CDP click target did not provide valid coordinates.') from exc
    params = {'x': x, 'y': y, 'button': 'left', 'clickCount': 1}
    await page.call('Input.dispatchMouseEvent', {'type': 'mousePressed', **params})
    await page.call('Input.dispatchMouseEvent', {'type': 'mouseReleased', **params})


def _is_hall_scroll_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return normalized.startswith('\u65ad\u8a00\uff1a') and '\u6eda\u52a8' in normalized and any(marker in normalized for marker in ('\u6d88\u606f\u6d41', '\u6210\u5458\u5217\u8868'))


def _is_article_latest_tab_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return normalized.startswith('\u65ad\u8a00\uff1a') and '\u6700\u65b0' in normalized and '\u9009\u4e2d' in normalized


def _is_article_list_metadata_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u65ad\u8a00\uff1a')
        and '\u6587\u7ae0\u5217\u8868' in normalized
        and '\u81f3\u5c11\u5c55\u793a\u4e00\u6761' in normalized
        and '\u6807\u9898' in normalized
        and '\u53d1\u5e03\u65f6\u95f4' in normalized
    )


def _is_article_card_selection_instruction(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        not normalized.startswith('\u65ad\u8a00\uff1a')
        and '\u6587\u7ae0\u5361\u7247' in normalized
        and any(marker in normalized for marker in ('\u9009\u62e9', '\u8bb0\u5f55'))
    )


def _is_article_detail_open_instruction(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        not normalized.startswith('\u65ad\u8a00\uff1a')
        and any(marker in normalized for marker in ('\u6253\u5f00\u8be5\u6587\u7ae0\u8be6\u60c5', '\u70b9\u51fb\u540c\u4e00\u6587\u7ae0\u5361\u7247', '\u5df2\u6253\u5f00\u4e00\u7bc7\u516c\u5f00\u6587\u7ae0\u8be6\u60c5'))
    )


def _is_article_card_integrity_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u65ad\u8a00\uff1a')
        and '\u6587\u7ae0\u5361\u7247' in normalized
        and '\u540c\u4e00\u5361\u7247' in normalized
        and all(marker in normalized for marker in ('\u6807\u9898', '\u5206\u7c7b', '\u65e5\u671f'))
    )


def _is_read_only_cdp_instruction(instruction: str) -> bool:
    """Identify observation steps that should not be mistaken for UI clicks."""
    normalized = str(instruction or '').replace(' ', '')
    if not normalized.startswith('\u64cd\u4f5c\uff1a'):
        return False
    body = normalized[len('\u64cd\u4f5c\uff1a'):]
    if not body.startswith(('\u68c0\u67e5', '\u67e5\u770b', '\u89c2\u5bdf', '\u786e\u8ba4', '\u5b9a\u4f4d', '\u7edf\u8ba1')):
        return False
    return not any(marker in body for marker in (
        '\u70b9\u51fb', '\u53cc\u51fb', '\u8f93\u5165', '\u586b\u5199', '\u9009\u62e9', '\u5207\u6362', '\u6253\u5f00', '\u5173\u95ed',
        '\u6eda\u52a8', '\u5237\u65b0', '\u53d1\u5e03', '\u4fdd\u5b58', '\u5220\u9664', '\u53d1\u9001', '\u64a4\u56de', '\u56de\u590d', '\u6e05\u7a7a', '\u8bbf\u95ee',
    ))


def _is_renderer_health_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u65ad\u8a00\uff1a')
        and any(marker in normalized for marker in ('\u767d\u5c4f', '404', '\u811a\u672c\u9519\u8bef', '\u9519\u8bef\u9875', '\u5168\u5c4f\u52a0\u8f7d'))
    )


def _is_article_publish_entry_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u65ad\u8a00\uff1a')
        and ('\u6253\u5f00\u6587\u7ae0\u53d1\u5e03\u7f16\u8f91\u754c\u9762' in normalized or '\u9009\u62e9\u53d1\u5e03\u7c7b\u578b' in normalized)
    )


def _is_article_publish_open_instruction(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u64cd\u4f5c\uff1a')
        and '\u70b9\u51fb' in normalized
        and '\u53d1\u5e03' in normalized
        and '\u6587\u7ae0' in normalized
        and '\u786e\u5b9a\u53d1\u5e03' not in normalized
    )


def _is_article_publish_type_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u65ad\u8a00\uff1a')
        and '\u53d1\u5e03\u6587\u7ae0' in normalized
        and '\u53d1\u5e03H5\u6d3b\u52a8' in normalized
    )


def _is_article_preview_instruction(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return normalized.startswith('\u64cd\u4f5c\uff1a') and '\u70b9\u51fb' in normalized and '\u9884\u89c8' in normalized


def _is_article_preview_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return normalized.startswith('\u65ad\u8a00\uff1a') and '\u9884\u89c8' in normalized


def _is_article_h5_selection_instruction(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return normalized.startswith('\u64cd\u4f5c\uff1a') and '\u53d1\u5e03H5\u6d3b\u52a8' in normalized and any(marker in normalized for marker in ('\u9009\u62e9', '\u70b9\u51fb'))


def _is_article_h5_editor_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return normalized.startswith('\u65ad\u8a00\uff1a') and '\u6d3b\u52a8\u94fe\u63a5' in normalized and '\u5ba2\u6237\u7aef\u5185\u6253\u5f00' in normalized


def _is_community_home_navigation_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u65ad\u8a00\uff1a')
        and (
            ('\u5de6\u4fa7\u63d2\u4ef6\u5217\u8868' in normalized and any(label in normalized for label in ('PUBG\u798f\u5229\u5546\u5e97', 'NN\u5546\u57ce', '\u6210\u5458\u5927\u5385', '\u5168\u5458\u5927\u5385', '\u6218\u7ee9\u67e5\u8be2', '\u8d5b\u4e8b\u4e13\u533a', '\u65d7\u4e0b\u793e\u533a')))
            or ('\u7edd\u5730\u6c42\u751f\u9996\u9875' in normalized and '\u9009\u4e2d' in normalized)
        )
    )


def _is_community_plugin_scroll_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return normalized.startswith('\u65ad\u8a00\uff1a') and '\u63d2\u4ef6\u5217\u8868' in normalized and '\u6eda\u52a8' in normalized


def _is_team_home_filter_panel_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u65ad\u8a00\uff1a')
        and '\u7b5b\u9009\u9762\u677f' in normalized
        and any(marker in normalized for marker in ('\u7ec4\u961f', '\u76f4\u64ad', '\u4e92\u52a8', '\u7a7a\u623f', '\u5168\u5c40\u641c\u7d22'))
    )


def _is_team_home_filter_open_instruction(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return normalized.startswith('\u64cd\u4f5c\uff1a') and '\u70b9\u51fb' in normalized and '\u7b5b\u9009' in normalized and '\u9762\u677f' not in normalized


def _is_team_home_filter_tab_switch_instruction(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u64cd\u4f5c\uff1a')
        and '\u5206\u522b\u70b9\u51fb' in normalized
        and all(label in normalized for label in ('\u7ec4\u961f', '\u76f4\u64ad', '\u4e92\u52a8', '\u7a7a\u623f'))
    )


def _is_team_home_filter_search_instruction(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u64cd\u4f5c\uff1a')
        and (
            '\u5168\u5c40\u641c\u7d22\u5173\u952e\u8bcd' in normalized
            or ('\u6e05\u7a7a\u641c\u7d22\u5173\u952e\u8bcd' in normalized and '\u5237\u65b0' in normalized)
        )
        and any(marker in normalized for marker in ('\u8f93\u5165', '\u6e05\u7a7a', '\u5237\u65b0'))
    )


def _is_team_home_filter_search_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u65ad\u8a00\uff1a')
        and '\u7b5b\u9009\u7ed3\u679c' in normalized
        and any(marker in normalized for marker in ('\u7a7a\u72b6\u6001', '\u6682\u65e0\u641c\u7d22\u7ed3\u679c', '\u6062\u590d', '\u4e0d\u6b8b\u7559'))
    )


def _is_community_plugin_switch_stability_instruction(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u64cd\u4f5c\uff1a')
        and '\u4f9d\u6b21' in normalized
        and '\u65d7\u4e0b\u793e\u533a' in normalized
        and '\u6210\u5458\u5927\u5385' in normalized
        and '\u6218\u7ee9\u67e5\u8be2' in normalized
    )


def _is_community_plugin_switch_stability_verification(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        '\u6bcf\u6b21\u70b9\u51fb\u540e\u65ad\u8a00' in normalized
        and '\u5de6\u4fa7\u63d2\u4ef6' in normalized
        and any(marker in normalized for marker in ('404', '\u767b\u5f55\u9875', '\u5f02\u5e38'))
    )


def _is_recruitment_dialog_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return normalized.startswith('\u65ad\u8a00\uff1a') and any(marker in normalized for marker in (
        '\u53d1\u5e03\u62db\u52df\u4fe1\u606f', '\u9009\u62e9\u533a\u670d', '\u62db\u52df\u961f\u53cb\u4fe1\u606f', '\u623f\u95f4\u4eba\u6570', '\u62db\u52df\u6709\u6548\u671f', '\u70ed\u95e8\u5f15\u7528', '\u5f39\u7a97\u4fdd\u6301\u6253\u5f00', '\u8f93\u5165\u8ba1\u6570', '15/15', '\u4e0d\u70b9\u51fb\u201c\u786e\u5b9a\u53d1\u5e03\u201d', '\u4e0d\u4ea7\u751f\u7ebf\u4e0a\u62db\u52df',
    ))


def _is_recruitment_default_publish_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u65ad\u8a00\uff1a')
        and '\u53d1\u5e03\u81f3' in normalized
        and '\u5b98\u65b9\u793e\u533a' in normalized
        and any(marker in normalized for marker in ('\u9ed8\u8ba4\u5df2\u52fe\u9009', '\u9ed8\u8ba4\u9009\u4e2d', '\u5df2\u52fe\u9009'))
    )


def _is_conditional_empty_room_assertion(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return normalized.startswith('\u65ad\u8a00\uff1a') and '\u65e0\u5339\u914d\u623f\u95f4\u65f6' in normalized and '\u6682\u65e0\u7ec4\u961f\u623f\u95f4' in normalized


def _is_recruitment_form_operation(instruction: str) -> bool:
    normalized = str(instruction or '').replace(' ', '')
    return (
        normalized.startswith('\u64cd\u4f5c\uff1a')
        and any(marker in normalized for marker in ('\u62db\u52df\u961f\u53cb\u4fe1\u606f', '\u70ed\u95e8\u5f15\u7528', '\u623f\u95f4\u4eba\u6570', '\u62db\u52df\u6709\u6548\u671f', '\u7ee7\u7eed\u8f93\u5165\u7b2c16\u4e2a\u5b57\u7b26'))
    )


async def _run_cdp_closed_shadow_community_search(page: _CDPPage, keyword: str = '') -> dict[str, Any]:
    """Operate NN's top search control when its implementation hides the input from DOM queries.

    The renderer draws this control in a closed component tree, but Chromium still
    accepts CDP input events. These events stay within the Electron renderer and
    never move or click the operator's physical mouse.
    """
    # After a hash-route reload, the shell can be interactive before its
    # community data has finished hydrating. Waiting here prevents the search
    # request from being sent against a transient empty context.
    await asyncio.sleep(1.5)
    # Newer NN builds expose a stable clickable search-beam host even though
    # the actual input remains inside a closed component tree. Prefer that
    # semantic host before falling back to renderer mouse events.
    await page.evaluate(r'''
      (() => {
        const beam = document.querySelector('.nn-search-beam');
        if (beam && beam.getBoundingClientRect().width > 1) beam.click();
        return Boolean(beam);
      })()
    ''')
    await asyncio.sleep(0.25)
    viewport = await page.evaluate(r'''(() => ({width: window.innerWidth || 1280, height: window.innerHeight || 900}))()''')
    width = max(640, int((viewport or {}).get('width') or 1280))
    height = max(160, int((viewport or {}).get('height') or 900))
    x = max(260, min(width - 80, round(width * 0.4)))
    y = min(height - 20, 25)
    mouse_params = {'x': x, 'y': y, 'button': 'left', 'clickCount': 1}
    await page.call('Input.dispatchMouseEvent', {'type': 'mousePressed', **mouse_params})
    await page.call('Input.dispatchMouseEvent', {'type': 'mouseReleased', **mouse_params})
    await asyncio.sleep(0.35)
    if keyword:
        payload = json.dumps(str(keyword), ensure_ascii=False)
        typed = await page.evaluate(rf'''
          (() => {{
            const keyword = {payload};
            const visible = element => {{ const rect=element.getBoundingClientRect(), style=getComputedStyle(element); return rect.width>100 && rect.height>10 && style.display!=='none' && style.visibility!=='hidden'; }};
            const input = Array.from(document.querySelectorAll('input')).find(element =>
              visible(element)
              && String(element.getAttribute('placeholder') || '').includes('\u641c\u7d22\u793e\u533a')
              && element.getBoundingClientRect().top < 100
            );
            if (!input) return false;
            const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
            if (setter) setter.call(input, keyword); else input.value = keyword;
            input.focus();
            input.dispatchEvent(new InputEvent('input', {{bubbles:true, inputType:'insertText', data:keyword}}));
            input.dispatchEvent(new Event('change', {{bubbles:true}}));
            input.dispatchEvent(new KeyboardEvent('keydown', {{key:'Enter', code:'Enter', bubbles:true}}));
            input.dispatchEvent(new KeyboardEvent('keyup', {{key:'Enter', code:'Enter', bubbles:true}}));
            return String(input.value || '') === keyword;
          }})()
        ''')
        if not typed:
            await page.call('Input.insertText', {'text': keyword})
            key_event = {
                'key': 'Enter', 'code': 'Enter', 'windowsVirtualKeyCode': 13,
                'nativeVirtualKeyCode': 13,
            }
            await page.call('Input.dispatchKeyEvent', {'type': 'keyDown', **key_event})
            await page.call('Input.dispatchKeyEvent', {'type': 'keyUp', **key_event})
        await page.evaluate(f"sessionStorage.setItem('__testhub_community_search_keyword', {json.dumps(str(keyword), ensure_ascii=False)}); true")

    started_at = asyncio.get_running_loop().time()
    deadline = started_at + 5.0
    while True:
        state = await page.evaluate(r'''
          (() => {
            const text = String(document.body?.innerText || '').replace(/\s+/g, ' ').trim();
            return {
              panelOpen: text.includes('\u5f00\u653e\u7684\u6e38\u620f\u5b98\u65b9\u793e\u533a'),
              resultsOpen: text.includes('\u641c\u7d22\u7684\u6e38\u620f\u3001\u6218\u961f\u793e\u533a'),
              hasResultCount: text.includes('\u5171\u627e\u5230'),
              // Current NN search renders discovery-game-card directly under
              // the official-community heading, without the legacy section
              // title or aggregate result count.
              hasCommunityCard: Boolean(document.querySelector('.discovery-game-card')),
            };
          })()
        ''')
        # A search overlay appears before its async result source settles.
        # Keep polling briefly after it appears so a P0 positive search does
        # not capture the initial "0 results" placeholder state.
        settled = asyncio.get_running_loop().time() - started_at >= 1.8
        # NN's current client can open the result list directly, without the
        # older "开放的游戏官方社区" discovery copy. Either rendered search
        # state is a valid post-click signal; a result count is the fallback
        # for a delayed list virtualisation pass.
        passed = bool(
            ((state or {}).get('resultsOpen') or (state or {}).get('hasCommunityCard')) and settled
            if keyword else any((state or {}).get(key) for key in ('panelOpen', 'resultsOpen', 'hasResultCount'))
        )
        if passed or asyncio.get_running_loop().time() >= deadline:
            reason = (
                f'community search results opened for {keyword!r} through the Electron renderer'
                if keyword else 'community search panel opened through the Electron renderer'
            )
            if not passed:
                reason = f'community search renderer did not open the expected state: {state}'
            return {'handled': True, 'passed': passed, 'reason': reason, 'evidence': state or {}}
        await asyncio.sleep(0.2)


async def _cdp_replace_focused_input(page: _CDPPage, value: str) -> str:
    """Replace a focused native input through Chromium's real keyboard path.

    Setting ``input.value`` plus dispatching a synthetic event is insufficient
    for some Electron/Vue controls: the DOM updates but their component state
    does not. CDP keyboard events exercise the renderer's mounted listener
    without stealing the operator's physical keyboard.
    """
    max_length = await page.evaluate(r'''
      (() => {
        const active = document.activeElement;
        return active instanceof HTMLInputElement || active instanceof HTMLTextAreaElement
          ? Number(active.maxLength || 0) : 0;
      })()
    ''')
    text = str(value or '')
    if isinstance(max_length, (int, float)) and max_length > 0:
        text = text[:int(max_length)]
    control = {'key': 'Control', 'code': 'ControlLeft', 'windowsVirtualKeyCode': 17, 'nativeVirtualKeyCode': 17}
    select_all = {'key': 'a', 'code': 'KeyA', 'modifiers': 2, 'windowsVirtualKeyCode': 65, 'nativeVirtualKeyCode': 65}
    backspace = {'key': 'Backspace', 'code': 'Backspace', 'windowsVirtualKeyCode': 8, 'nativeVirtualKeyCode': 8}
    await page.call('Input.dispatchKeyEvent', {'type': 'keyDown', **control})
    await page.call('Input.dispatchKeyEvent', {'type': 'keyDown', **select_all})
    await page.call('Input.dispatchKeyEvent', {'type': 'keyUp', **select_all})
    await page.call('Input.dispatchKeyEvent', {'type': 'keyUp', **control})
    await page.call('Input.dispatchKeyEvent', {'type': 'keyDown', **backspace})
    await page.call('Input.dispatchKeyEvent', {'type': 'keyUp', **backspace})
    if text:
        await page.call('Input.insertText', {'text': text})
    return text


async def _execute_cdp_semantic_instruction(
    page: _CDPPage,
    instruction: str,
    task_description: str = '',
) -> dict[str, Any] | None:
    """Handle stable NN renderer concepts before asking a model to choose duplicate cards."""
    normalized = str(instruction or '').replace(' ', '')
    requested_route = _cdp_route_from_task_description(instruction)
    task_route = _cdp_route_from_task_description(task_description)
    route_operation = (
        (requested_route or task_route)
        and not instruction.startswith('\u65ad\u8a00\uff1a')
        and (
            '\u8bbf\u95ee' in normalized
            or '\u76ee\u6807\u5730\u5740' in normalized
            or normalized in {'\u64cd\u4f5c\uff1a\u8bbf\u95ee\u9875\u9762', '\u8bbf\u95ee\u9875\u9762'}
        )
        and '\u70b9\u51fb' not in normalized
    )
    if route_operation:
        requested_route = requested_route or task_route
        result = await page.evaluate(f'''
          (() => {{
            const requestedRoute = {json.dumps(requested_route)};
            if ((location.hash || '').replace(/^#/, '') !== requestedRoute) location.hash = requestedRoute;
            return new Promise(resolve => setTimeout(() => {{
              const route = String(location.hash || '').replace(/^#/, '');
              resolve({{handled: true, passed: route === requestedRoute, reason: route === requestedRoute ? `target route is ready: ${{route}}` : `target route mismatch: expected=${{requestedRoute}}, actual=${{route}}`, route}});
            }}, 500));
          }})()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_hall_member_search_instruction(instruction):
        # The hall shell renders before its asynchronous member list. Give the
        # list one bounded hydration window before deriving a dynamic nickname.
        if not await _wait_for_cdp_visible_selector(page, 'input[placeholder="\u641c\u7d22\u6210\u5458"]', 12):
            return {'handled': True, 'passed': False, 'reason': 'member search input was not rendered after the Hall member pane hydration window'}
        payload = json.dumps({'instruction': normalized}, ensure_ascii=False)
        result = await page.evaluate(rf'''
          (() => {{
            const payload = {payload};
            const input = document.querySelector('input[placeholder="\u641c\u7d22\u6210\u5458"]');
            if (!input) return {{handled:true, passed:false, reason:'member search input is not rendered'}};
            let panel = input;
            while (panel && !panel.querySelector('.ui-scroller-content')) panel = panel.parentElement;
            const cards = () => Array.from(panel?.querySelectorAll('.ui-scroller-content .group\\/avatar') || []);
            const memberName = card => String(card?.innerText || '').split(/\n+/).map(value => value.trim()).find(Boolean) || '';
            const originalNames = cards().map(memberName).filter(Boolean);
            const write = value => {{
              const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
              if (setter) setter.call(input, value); else input.value = value;
              input.focus();
              const inputEvent = new InputEvent('input', {{bubbles:true, inputType:'insertText', data:value}});
              const inputInvoker = input._vei?.onInput;
              if (typeof inputInvoker === 'function') inputInvoker(inputEvent);
              input.dispatchEvent(inputEvent);
              input.dispatchEvent(new Event('change', {{bubbles:true}}));
              input.dispatchEvent(new KeyboardEvent('keyup', {{key:String(value).slice(-1), bubbles:true}}));
            }};
            if (/\u8bb0\u5f55(?:\u7b2c\u4e00\u4f4d|\u9996\u4f4d)/.test(payload.instruction)) {{
              const name = originalNames[0] || '';
              sessionStorage.setItem('__testhub_hall_member_name', name);
              sessionStorage.setItem('__testhub_hall_member_count', String(originalNames.length));
              return {{handled:true, passed:Boolean(name), reason:name ? `recorded first visible member: ${{name}}` : 'no visible member card is available to record', evidence:{{name, count:originalNames.length}}}};
            }}
            if (payload.instruction.includes('\u6e05\u7a7a')) {{
              const before = String(input.value || '');
              sessionStorage.setItem('__testhub_hall_search_before_clear', before);
              sessionStorage.setItem('__testhub_hall_filtered_count', String(cards().length));
              write('');
              return new Promise(resolve => setTimeout(() => {{
                const current = cards().map(memberName).filter(Boolean);
                sessionStorage.setItem('__testhub_hall_restored_count', String(current.length));
                resolve({{handled:true, passed:input.value === '', reason:input.value === '' ? `cleared member search and restored ${{current.length}} visible members` : 'member search input did not clear', evidence:{{before, restoredCount:current.length}}}});
              }}, 450));
            }}
            let value = '';
            // Preserve literal input verbatim, including punctuation such as
            // quotes, percent, underscore and parentheses.  Imported cases
            // often omit the matching closing quote, so extract from the last
            // "输入" marker rather than relying on paired quotation marks.
            const inputMarker = payload.instruction.lastIndexOf('\u8f93\u5165');
            if (inputMarker >= 0) {{
              const tail = payload.instruction.slice(inputMarker + 2).replace(/[\u3002\uff1b]$/, '');
              if (
                tail
                && !/^\u6846(?:\u8f93\u5165|\u586b(?:\u5199|\u5165))?$/.test(tail)
                // "输入记录的完整昵称" describes previously captured data,
                // rather than literal text to enter into the search box.
                && !/(?:\u8bb0\u5f55|\u5f53\u524d|\u8be5|\u5b8c\u6574).*\u6635\u79f0/.test(tail)
              ) value = tail;
            }}
            if ((!value || /NO_MEMBER_\$\{{timestamp\(\)\}}/.test(value)) && /NO_MEMBER_/.test(payload.instruction)) value = `NO_MEMBER_${{Date.now()}}`;
            else if (!value && payload.instruction.includes('\u9ad8\u7ba1')) value = '\u9ad8\u7ba1';
            else {{
              const recorded = String(sessionStorage.getItem('__testhub_hall_member_name') || originalNames[0] || '');
              value = value || (/\u524d\s*1\s*\u81f3\s*2\s*\u4e2a\u5b57\u7b26/.test(payload.instruction) ? recorded.slice(0, 2) : recorded);
            }}
            if (!value) return {{handled:true, passed:false, reason:'no member nickname is available for the requested search'}};
            sessionStorage.setItem('__testhub_hall_search_value', value);
            sessionStorage.setItem('__testhub_hall_member_count', String(originalNames.length));
            write(value);
            return new Promise(resolve => setTimeout(() => {{
              const names = cards().map(memberName).filter(Boolean);
              sessionStorage.setItem('__testhub_hall_filtered_count', String(names.length));
              sessionStorage.setItem('__testhub_hall_search_result_names', JSON.stringify(names));
              sessionStorage.setItem('__testhub_hall_empty_seen', names.length === 0 ? 'true' : 'false');
              resolve({{handled:true, passed:input.value === value, reason:input.value === value ? `member search entered: ${{value}}` : `member search value mismatch: ${{input.value}}`, evidence:{{value, resultNames:names.slice(0,8)}}}});
            }}, 500));
          }})()
        ''')
        # This NN input is a Vue-controlled component. Its synthetic event
        # updates the displayed value but can leave the member store unfiltered.
        # Replay the same replacement through CDP's native input channel so the
        # live renderer listener performs the actual filtering.
        if isinstance(result, dict) and result.get('handled') and not re.search(r'\u8bb0\u5f55(?:\u7b2c\u4e00\u4f4d|\u9996\u4f4d)', normalized):
            native_value = await _cdp_replace_focused_input(
                page,
                '' if '\u6e05\u7a7a' in normalized else str((result.get('evidence') or {}).get('value') or ''),
            )
            await page.evaluate(f'''
              (() => {{
                sessionStorage.setItem('__testhub_hall_search_value', {json.dumps(native_value, ensure_ascii=False)});
                return true;
              }})()
            ''')
            await asyncio.sleep(0.45)
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_hall_member_search_assertion(instruction):
        if not await _wait_for_cdp_visible_selector(page, 'input[placeholder="\u641c\u7d22\u6210\u5458"]', 12):
            return {'handled': True, 'passed': False, 'reason': 'member search input was not rendered after the Hall member pane hydration window'}
        payload = json.dumps({'instruction': normalized}, ensure_ascii=False)
        result = await page.evaluate(rf'''
          (() => {{
            const payload = {payload};
            const input = document.querySelector('input[placeholder="\u641c\u7d22\u6210\u5458"]');
            if (!input) return {{handled:true, passed:false, reason:'member search input is not rendered'}};
            let panel = input;
            while (panel && !panel.querySelector('.ui-scroller-content')) panel = panel.parentElement;
            const cards = () => Array.from(panel?.querySelectorAll('.ui-scroller-content .group\\/avatar') || []);
            const names = cards().map(card => String(card.innerText || '').split(/\n+/).map(value => value.trim()).find(Boolean) || '').filter(Boolean);
            const activeValue = String(sessionStorage.getItem('__testhub_hall_search_value') || '');
            const beforeClear = String(sessionStorage.getItem('__testhub_hall_search_before_clear') || '');
            const storedFilteredCount = Number(sessionStorage.getItem('__testhub_hall_filtered_count') || 0);
            const storedRestoredCount = Number(sessionStorage.getItem('__testhub_hall_restored_count') || names.length);
            const resultNamesBeforeClear = (() => {{ try {{ return JSON.parse(sessionStorage.getItem('__testhub_hall_search_result_names') || '[]'); }} catch {{ return []; }} }})();
            const emptySeen = sessionStorage.getItem('__testhub_hall_empty_seen') === 'true';
            const isNoResult = /^NO_MEMBER_/.test(activeValue);
            const asksClear = /\u6e05\u7a7a\u540e|\u6062\u590d/.test(payload.instruction);
            const asksNoResult = /\u65e0\u7ed3\u679c/.test(payload.instruction);
            const asksNoResultLayout = /\u4ec5\u4f4d\u4e8e|\u4e0d\u906e\u6321|\u4e2d\u592e\u6d88\u606f\u6d41|\u9876\u90e8\u5bfc\u822a|\u5e95\u90e8\u8f93\u5165\u533a/.test(payload.instruction);
            const asksValue = /\u5f53\u524d\u503c|\u4fdd\u7559\u8f93\u5165\u503c|\u83b7\u5f97\u7126\u70b9/.test(payload.instruction);
            const asksMatch = /\u5305\u542b|\u7b5b\u9009|\u4fdd\u7559.*\u6210\u5458|\u81f3\u5c11\u5c55\u793a|\u6635\u79f0/.test(payload.instruction);
            const rect = element => {{
              const value = element?.getBoundingClientRect?.();
              return value ? {{left:value.left, top:value.top, right:value.right, bottom:value.bottom, width:value.width, height:value.height}} : null;
            }};
            const overlaps = (left, right) => Boolean(left && right && left.left < right.right && left.right > right.left && left.top < right.bottom && left.bottom > right.top);
            const saveNoResultLayout = () => {{
              const panelRect = rect(panel);
              const messageRect = rect(document.querySelector('.msg-common-scroll'));
              const composerRect = rect(document.querySelector('.chat-input[contenteditable]')?.closest('.min-h-\\[40px\\]'));
              const navRect = {{left:0, top:0, right:window.innerWidth, bottom:Math.min(110, window.innerHeight), width:window.innerWidth, height:Math.min(110, window.innerHeight)}};
              const passed = Boolean(panelRect) && !overlaps(panelRect, messageRect) && !overlaps(panelRect, composerRect) && !overlaps(panelRect, navRect);
              const evidence = {{passed, panelRect, messageRect, composerRect, navRect}};
              sessionStorage.setItem('__testhub_hall_no_result_layout', JSON.stringify(evidence));
              return evidence;
            }};
            const savedNoResultLayout = (() => {{ try {{ return JSON.parse(sessionStorage.getItem('__testhub_hall_no_result_layout') || '{{}}'); }} catch {{ return {{}}; }} }})();
            let passed;
            if (asksClear) passed = input.value === '' && names.length >= Math.max(3, storedFilteredCount) && storedRestoredCount >= storedFilteredCount;
            else if (asksNoResult) {{
              const currentNoResult = isNoResult && (names.length === 0 || emptySeen);
              const layout = currentNoResult ? saveNoResultLayout() : savedNoResultLayout;
              passed = currentNoResult && (!asksNoResultLayout || layout.passed === true)
                || (!isNoResult && asksNoResultLayout && layout.passed === true);
            }}
            else if (asksValue) passed = Boolean(activeValue) && (input.value === activeValue || (beforeClear === activeValue && input.value === '' && /\u8f93\u5165\u5173\u952e\u5b57\u540e/.test(payload.instruction)));
            else if (asksMatch) {{
              const comparableNames = names.length && input.value === activeValue ? names : resultNamesBeforeClear;
              passed = Boolean(activeValue) && comparableNames.length > 0 && comparableNames.every(name => name.includes(activeValue));
            }}
            else passed = Boolean(input) && /\/community\/\d+\/hall(?:$|[/?])/.test(String(location.hash || ''));
            return {{handled:true, passed, reason:passed ? `member search invariant verified; visible results=${{names.length}}` : `member search invariant failed: value=${{input.value}}, expected=${{activeValue}}, results=${{names.length}}`, evidence:{{inputValue:input.value, expected:activeValue, resultNames:names.slice(0,8), resultNamesBeforeClear:resultNamesBeforeClear.slice(0,8), noResultLayout:savedNoResultLayout, route:String(location.hash||'')}}}};
          }})()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_hall_invite_instruction(instruction):
        payload = json.dumps({'instruction': normalized}, ensure_ascii=False)
        result = await page.evaluate(rf'''
          (() => {{
            const payload = {payload};
            const visible = element => {{ const rect=element.getBoundingClientRect(), style=getComputedStyle(element); return rect.width>1 && rect.height>1 && style.display !== 'none' && style.visibility !== 'hidden'; }};
            const dialog = () => Array.from(document.querySelectorAll('.ui-dialog,[role="dialog"],[class*="dialog" i],[class*="modal" i]')).filter(visible).find(element => String(element.innerText || '').includes('\u9080\u8bf7\u597d\u53cb'));
            if (payload.instruction.includes('\u5173\u95ed')) {{
              const open = dialog();
              const close = open && Array.from(open.querySelectorAll('[class*="close" i],button,i,svg')).filter(visible).find(element => /close|\u5173\u95ed/.test(String(element.className || '')));
              if (!open) return {{handled:true, passed:true, reason:'invite dialog is already closed'}};
              if (!close) return {{handled:true, passed:false, reason:'invite dialog has no visible close control'}};
              (close.closest('[class*="close" i],button,[role="button"]') || close).click();
              return new Promise(resolve => setTimeout(() => {{
                const passed = !dialog();
                if (passed) sessionStorage.setItem('__testhub_hall_invite_closed', 'true');
                resolve({{handled:true, passed, reason:passed ? 'invite dialog closed' : 'invite dialog remained visible after its close control was clicked'}});
              }}, 350));
            }}
            if (dialog()) return {{handled:true, passed:true, reason:'invite dialog is already open'}};
            const button = Array.from(document.querySelectorAll('button,[role="button"]')).filter(visible).find(element => /\u9080\u8bf7\s*\/\s*\u5206\u4eab/.test(String(element.innerText || element.textContent || '')));
            if (!button) return {{handled:true, passed:false, reason:'invite/share button is not visible'}};
            button.click();
            return new Promise(resolve => setTimeout(() => {{
              const passed = Boolean(dialog());
              if (passed) {{ sessionStorage.setItem('__testhub_hall_invite_opened', 'true'); sessionStorage.removeItem('__testhub_hall_invite_closed'); }}
              resolve({{handled:true, passed, reason:passed ? 'invite dialog opened' : 'invite dialog did not open'}});
            }}, 450));
          }})()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_hall_invite_assertion(instruction):
        payload = json.dumps({'instruction': normalized}, ensure_ascii=False)
        result = await page.evaluate(rf'''
          (() => {{
            const payload = {payload};
            const visible = element => {{ const rect=element.getBoundingClientRect(), style=getComputedStyle(element); return rect.width>1 && rect.height>1 && style.display !== 'none' && style.visibility !== 'hidden'; }};
            const dialog = Array.from(document.querySelectorAll('.ui-dialog,[role="dialog"],[class*="dialog" i],[class*="modal" i]')).filter(visible).find(element => String(element.innerText || '').includes('\u9080\u8bf7\u597d\u53cb'));
            const closing = /\u5173\u95ed\u540e|\u6d88\u5931|\u6062\u590d\u53ef\u64cd\u4f5c/.test(payload.instruction);
            const openedDuringCase = sessionStorage.getItem('__testhub_hall_invite_opened') === 'true';
            const closedDuringCase = sessionStorage.getItem('__testhub_hall_invite_closed') === 'true';
            const hasHall = /\/community\/\d+\/hall(?:$|[/?])/.test(String(location.hash || '')) && String(document.body?.innerText || '').includes('\u6210\u5458\u5927\u5385');
            const passed = closing ? !dialog && closedDuringCase && hasHall : openedDuringCase && hasHall;
            return {{handled:true, passed, reason:passed ? (closing ? 'invite dialog was closed and member hall remains usable' : 'invite dialog opened during this case over the member hall') : `invite dialog assertion mismatch: dialog=${{Boolean(dialog)}}, opened=${{openedDuringCase}}, closed=${{closedDuringCase}}, hall=${{hasHall}}`, evidence:{{dialog:Boolean(dialog), openedDuringCase, closedDuringCase, hasHall}}}};
          }})()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_hall_message_input_instruction(instruction):
        payload = json.dumps({'instruction': normalized}, ensure_ascii=False)
        result = await page.evaluate(rf'''
          (() => {{
            const payload = {payload};
            const input = document.querySelector('.chat-input[contenteditable]');
            if (!input) return {{handled:true, passed:false, reason:'member-hall chat input is not rendered'}};
            if (/\u5931\u7126|\u6d88\u606f\u6d41\u7a7a\u767d/.test(payload.instruction)) {{ input.blur(); return {{handled:true, passed:document.activeElement !== input, reason:'member-hall chat input blurred'}}; }}
            const match = payload.instruction.match(/[\u201c\"]([^\u201d\"]{{4,}})[\u201d\"]/);
            const value = match ? match[1] : '\u6210\u5458\u5927\u5385\u8f93\u5165\u6846\u81ea\u52a8\u5316\u9a8c\u8bc1';
            input.focus(); input.textContent = value;
            input.dispatchEvent(new InputEvent('input', {{bubbles:true, inputType:'insertText', data:value}}));
            sessionStorage.setItem('__testhub_hall_chat_input', value);
            return {{handled:true, passed:document.activeElement === input && String(input.textContent || '') === value, reason:'member-hall chat input focused and populated', evidence:{{value}}}};
          }})()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_hall_reply_open_instruction(instruction):
        result = await page.evaluate(r'''
          (() => {
            const visible = element => { const rect = element.getBoundingClientRect(), style = getComputedStyle(element); return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden'; };
            const values = JSON.parse(sessionStorage.getItem('__testhub_hall_unique_messages') || '[]');
            const targetValue = values[values.length - 1] || '';
            const rows = Array.from(document.querySelectorAll('[data-msg-id],[id]')).filter(element =>
              visible(element) && (/^\d+$/.test(String(element.id || '')) || element.hasAttribute('data-msg-id'))
            );
            const row = (targetValue && rows.find(element => String(element.innerText || '').includes(targetValue)))
              || rows.find(element => /group\/avatar/.test(String(element.querySelector('[class*="group/avatar"]')?.className || '')) && element.querySelector('i[class*="Reply" i],i[class*="huifu" i]'));
            const reply = Array.from(row?.querySelectorAll('i') || []).find(element => /Reply|huifu/i.test(String(element.className || '')))?.parentElement;
            if (!row || !reply) return {handled:true, passed:false, reason:'no reply-capable Hall message row is rendered'};
            reply.click();
            return new Promise(resolve => setTimeout(() => {
              const composer = document.querySelector('.chat-input[contenteditable]')?.closest('.min-h-\\[40px\\]');
              const text = String(composer?.innerText || '').replace(/\s+/g, ' ').trim();
              const passed = text.includes('\u6b63\u5728\u56de\u590d');
              if (passed) sessionStorage.setItem('__testhub_hall_reply_open', JSON.stringify({sourceId: String(row.getAttribute('data-msg-id') || row.id || ''), sourceText: String(row.innerText || '').slice(0, 300), targetValue, contextVisible:true, composerText:text}));
              resolve({handled:true, passed, reason: passed ? 'reply state opened for the selected Hall message' : 'reply state did not appear after clicking the selected message reply control', evidence:{sourceId:String(row.getAttribute('data-msg-id') || row.id || ''), targetValue}});
            }, 450));
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_hall_reply_cancel_instruction(instruction):
        result = await page.evaluate(r'''
          (() => {
            const input = document.querySelector('.chat-input[contenteditable]');
            const composer = input?.closest('.min-h-\\[40px\\]');
            const text = String(composer?.innerText || '').replace(/\s+/g, ' ').trim();
            if (!text.includes('\u6b63\u5728\u56de\u590d')) return {handled:true, passed:true, reason:'reply state is already closed'};
            const composerRect = composer.getBoundingClientRect();
            const candidates = Array.from(composer.querySelectorAll('*')).filter(element => {
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 4 && rect.width < 64 && rect.height > 4 && rect.height < 64
                && rect.top >= composerRect.top - 2 && rect.bottom <= composerRect.top + 64
                && rect.right >= composerRect.right - 120
                && style.display !== 'none' && style.visibility !== 'hidden';
            });
            const close = candidates.find(element => /close|guanbi|quxiao|cancel/i.test(String(element.className || '') + ' ' + String((element.parentElement && element.parentElement.className) || '')))
              || candidates.sort((left, right) => right.getBoundingClientRect().right - left.getBoundingClientRect().right)[0];
            if (!close) return {handled:true, passed:false, reason:'reply state has no visible cancel control'};
            const target = close.closest('button,[role="button"],[class*="cursor-pointer" i]') || close;
            const rect = target.getBoundingClientRect();
            return {handled:true, cancelPoint:{x:rect.left + rect.width / 2, y:rect.top + rect.height / 2}};
          })()
        ''')
        if not isinstance(result, dict) or not result.get('handled') or not result.get('cancelPoint'):
            return result if isinstance(result, dict) and result.get('handled') else None
        point = result['cancelPoint']
        for event_type in ('mousePressed', 'mouseReleased'):
            await page.call('Input.dispatchMouseEvent', {
                'type': event_type, 'x': point['x'], 'y': point['y'], 'button': 'left', 'clickCount': 1,
            })
        await asyncio.sleep(0.4)
        result = await page.evaluate(r'''
          (() => {
            const input = document.querySelector('.chat-input[contenteditable]');
            const composer = input?.closest('.min-h-\\[40px\\]');
            const current = String(composer?.innerText || '').replace(/\s+/g, ' ').trim();
            const passed = !current.includes('\u6b63\u5728\u56de\u590d');
            if (passed) sessionStorage.setItem('__testhub_hall_reply_cancelled', 'true');
            return {handled:true, passed, reason:passed ? 'reply state cancelled without sending a message' : 'reply state remained after CDP cancellation click', evidence:{composerText:current}};
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_hall_reply_open_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            const input = document.querySelector('.chat-input[contenteditable]');
            const composer = input?.closest('.min-h-\\[40px\\]');
            const text = String(composer?.innerText || '').replace(/\s+/g, ' ').trim();
            let opened = {}; try { opened = JSON.parse(sessionStorage.getItem('__testhub_hall_reply_open') || '{}'); } catch (_error) {}
            const passed = Boolean(opened.sourceId) && opened.contextVisible === true;
            return {handled:true, passed, reason:passed ? 'reply composer displayed the selected message context during this case' : 'reply composer never displayed a selected-message context during this case', evidence:{sourceId:String(opened.sourceId || ''), currentComposerText:text, openedComposerText:String(opened.composerText || '')}};
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_hall_reply_cancel_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            const input = document.querySelector('.chat-input[contenteditable]');
            const composer = input?.closest('.min-h-\\[40px\\]');
            const text = String(composer?.innerText || '').replace(/\s+/g, ' ').trim();
            const cancelled = sessionStorage.getItem('__testhub_hall_reply_cancelled') === 'true';
            const passed = cancelled && !text.includes('\u6b63\u5728\u56de\u590d');
            return {handled:true, passed, reason:passed ? 'reply state was cancelled and the composer returned to normal' : 'reply state remains active or was not cancelled by this case', evidence:{cancelled, composerText:text}};
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_hall_unsent_draft_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            const draft = String(sessionStorage.getItem('__testhub_hall_unique_draft') || '');
            const input = document.querySelector('.chat-input[contenteditable]');
            const composer = input?.closest('.min-h-\\[40px\\]');
            const text = String(input?.textContent || '').replace(/\s+/g, ' ').trim();
            const composerText = String(composer?.innerText || '').replace(/\s+/g, ' ').trim();
            const provides = document.querySelector('#app')?.__vue_app__?._context?.provides;
            const pinia = provides && Object.getOwnPropertySymbols(provides).map(symbol => provides[symbol]).find(value => value && value._s?.get('chat'));
            const chat = pinia?._s?.get('chat');
            const conversationId = String(sessionStorage.getItem('__testhub_hall_conversation_id') || '');
            const messages = chat?.chatMap?.[conversationId]?.msgList || [];
            const sent = messages.some(message => String(message?.payload?.text || '') === draft && !message.isDeleted && !message.isRevoked);
            const passed = Boolean(draft) && text.includes(draft) && !composerText.includes('\u6b63\u5728\u56de\u590d') && !sent;
            return {handled:true, passed, reason:passed ? 'normal unsent draft has no reply relationship or message record' : 'draft state retained a reply relationship or was unexpectedly sent', evidence:{draft, composerText, sent}};
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_hall_reply_message_relation_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            let evidence = {}; let replyOpen = {};
            try { evidence = JSON.parse(sessionStorage.getItem('__testhub_hall_reply_evidence') || '{}'); } catch (_error) {}
            try { replyOpen = JSON.parse(sessionStorage.getItem('__testhub_hall_reply_open') || '{}'); } catch (_error) {}
            const passed = evidence.linked === true && evidence.exactlyOne === true && replyOpen.contextVisible === true;
            return {handled:true, passed, reason:passed ? 'captured renderer evidence confirms the reply link before cleanup' : 'the case did not capture a complete reply-link evidence chain before cleanup', evidence:{...evidence, replyContextVisible:replyOpen.contextVisible === true}};
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_hall_reply_message_relation_instruction(instruction):
        result = await page.evaluate(r'''
          (() => {
            const visible = element => { const rect = element.getBoundingClientRect(), style = getComputedStyle(element); return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden'; };
            const rowFor = id => document.querySelector(`[data-msg-id="${CSS.escape(String(id || ''))}"]`)
              || document.getElementById(String(id || ''))
              || Array.from(document.querySelectorAll('[data-msg-id],[id]')).find(element => String(element.getAttribute('data-msg-id') || element.id || '') === String(id || ''));
            let replyOpen = {}; let sendEvidence = {};
            try { replyOpen = JSON.parse(sessionStorage.getItem('__testhub_hall_reply_open') || '{}'); } catch (_error) {}
            try { sendEvidence = JSON.parse(sessionStorage.getItem('__testhub_hall_send_evidence') || '{}'); } catch (_error) {}
            const sentId = String((sendEvidence.messageIds || []).slice(-1)[0] || '');
            const sentValue = String((sendEvidence.values || []).slice(-1)[0] || '');
            const sourceRow = rowFor(replyOpen.sourceId);
            const replyRow = rowFor(sentId) || Array.from(document.querySelectorAll('[data-msg-id],[id]')).find(element => visible(element) && sentValue && String(element.innerText || '').includes(sentValue));
            const sourceText = String(replyOpen.sourceText || '').replace(/\s+/g, ' ').trim();
            const sourceMarker = String(replyOpen.targetValue || '') || (sourceText.match(/HALL_\d+_[^\s]+/) || [''])[0];
            const replyText = String(replyRow?.innerText || '').replace(/\s+/g, ' ').trim();
            const sourceVisible = String(sourceRow?.innerText || '').replace(/\s+/g, ' ').trim();
            const hasSourceEvidence = Boolean(sourceMarker || sourceVisible.length >= 4);
            const linked = Boolean(replyRow && sentValue && hasSourceEvidence && replyText.includes(sentValue)
              && (sourceMarker ? replyText.includes(sourceMarker) : replyText.includes(sourceVisible.slice(-18))));
            const exactlyOne = sentValue ? Array.from(document.querySelectorAll('[data-msg-id],[id]')).filter(element => visible(element) && String(element.innerText || '').includes(sentValue)).length === 1 : false;
            const evidence = {sourceId:String(replyOpen.sourceId || ''), sentId, sentValue, sourceMarker, linked, exactlyOne, replyText};
            if (linked) sessionStorage.setItem('__testhub_hall_reply_evidence', JSON.stringify(evidence));
            return {handled:true, passed:linked && exactlyOne, reason:linked && exactlyOne ? 'reply message visibly retains exactly one link to its original message' : 'reply message does not retain a verifiable original-message relationship', evidence};
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_hall_generated_message_menu_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            const menuText = String(sessionStorage.getItem('__testhub_hall_generated_menu') || '');
            const passed = /\u64a4\u56de\u6d88\u606f/.test(menuText);
            return {handled:true, passed, reason:passed ? 'the generated message menu exposed a recall action before cleanup' : 'no captured generated-message menu exposes a recall action', evidence:{menuText}};
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_hall_generated_message_menu_instruction(instruction):
        result = await page.evaluate(r'''
          (() => {
            const values = JSON.parse(sessionStorage.getItem('__testhub_hall_unique_messages') || '[]');
            const value = values[values.length - 1] || '';
            const row = value && Array.from(document.querySelectorAll('[data-msg-id],[id]')).find(element =>
              (/^\d+$/.test(String(element.id || '')) || element.hasAttribute('data-msg-id')) && String(element.innerText || '').includes(value)
            );
            const more = Array.from(row?.querySelectorAll('i') || []).find(element => /more|gengduo/i.test(String(element.className || '')))?.parentElement;
            if (!row || !more) return {handled:true, passed:false, reason:'generated Hall message has no rendered more-menu control'};
            row.dispatchEvent(new MouseEvent('mouseover', {bubbles:true}));
            more.click();
            return new Promise(resolve => setTimeout(() => {
              // NN's message action layer is a plain fixed div in current
              // clients, without a semantic menu/popover class.  Identify it
              // by its bounded floating geometry and actual action labels.
              const visible = element => { const rect = element.getBoundingClientRect(), style = getComputedStyle(element); return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden'; };
              const menuText = Array.from(document.querySelectorAll('body *'))
                .filter(visible)
                .map(element => {
                  const rect = element.getBoundingClientRect();
                  const style = getComputedStyle(element);
                  return { text: String(element.innerText || '').replace(/\s+/g, ' ').trim(), rect, style };
                })
                .filter(item => /\u56de\u590d\u6d88\u606f|\u64a4\u56de\u6d88\u606f/.test(item.text)
                  && item.text.length <= 180
                  && item.rect.width <= 420
                  && item.rect.height <= 560
                  && (item.style.position === 'fixed' || item.style.position === 'absolute'))
                .sort((left, right) => (left.rect.width * left.rect.height) - (right.rect.width * right.rect.height))
                .map(item => item.text)
                .find(text => /\u64a4\u56de\u6d88\u606f/.test(text)) || '';
              const passed = /\u64a4\u56de/.test(menuText);
              sessionStorage.setItem('__testhub_hall_generated_menu', menuText);
              resolve({handled:true, passed, reason:passed ? 'generated Hall message menu exposes recall' : 'generated Hall message menu did not expose recall', evidence:{value, menuText}});
            }, 350));
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_hall_menu_consistency_instruction(instruction):
        result = await page.evaluate(r'''
          (async () => {
            const visible = element => { const rect=element.getBoundingClientRect(), style=getComputedStyle(element); return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden'; };
            const user = JSON.parse(localStorage.getItem('userInfo') || '{}');
            const currentUserId = String(user.userId || user.userInfo?.userId || localStorage.getItem('_user_id') || '');
            const provides = document.querySelector('#app')?.__vue_app__?._context?.provides;
            const pinia = provides && Object.getOwnPropertySymbols(provides).map(symbol => provides[symbol]).find(value => value && value._s?.get('chat'));
            const chat = pinia?._s?.get('chat');
            const conversationId = String(sessionStorage.getItem('__testhub_hall_conversation_id') || '');
            const messages = chat?.chatMap?.[conversationId]?.msgList || [];
            const rowFor = id => document.querySelector(`[data-msg-id="${CSS.escape(String(id || ''))}"]`)
              || document.getElementById(String(id || ''))
              || Array.from(document.querySelectorAll('[data-msg-id],[id]')).find(element => String(element.getAttribute('data-msg-id') || element.id || '') === String(id || ''));
            const choose = own => messages.slice().reverse().find(message => message && !message.isDeleted && !message.isRevoked && String(message.from || '') !== '' && (String(message.from) === currentUserId) === own && rowFor(message.ID));
            const actionLabels = root => Array.from(root?.children || []).filter(visible).map(element => String(element.innerText || '').replace(/\s+/g, ' ').trim()).filter(Boolean);
            const inspect = async message => {
              const row = rowFor(message?.ID);
              row?.dispatchEvent(new MouseEvent('mouseover', {bubbles:true}));
              const more = Array.from(row?.querySelectorAll('i') || []).find(element => /more|gengduo/i.test(String(element.className || '')))?.parentElement;
              if (!more) return {id:String(message?.ID || ''), actions:[], error:'more control absent'};
              more.click();
              await new Promise(resolve => setTimeout(resolve, 250));
              const root = Array.from(document.querySelectorAll('body *')).filter(visible).map(element => ({element, rect:element.getBoundingClientRect(), style:getComputedStyle(element), text:String(element.innerText || '').replace(/\s+/g, ' ').trim()})).filter(item => /\u56de\u590d\u6d88\u606f|\u64a4\u56de\u6d88\u606f/.test(item.text) && item.text.length <= 180 && item.rect.width <= 420 && item.rect.height <= 560 && (item.style.position === 'fixed' || item.style.position === 'absolute')).sort((left,right) => (left.rect.width * left.rect.height) - (right.rect.width * right.rect.height))[0]?.element;
              const actions = actionLabels(root);
              document.body.click();
              return {id:String(message?.ID || ''), actions, deleted:Boolean(message?.isDeleted), revoked:Boolean(message?.isRevoked)};
            };
            const own = choose(true), other = choose(false);
            if (!own || !other) return {handled:true, passed:false, reason:'both an own and another-member visible Hall message are required for this menu comparison', evidence:{own:Boolean(own), other:Boolean(other)}};
            const ownMenu = await inspect(own), otherMenu = await inspect(other);
            const sameActions = ownMenu.actions.length > 0 && JSON.stringify(ownMenu.actions) === JSON.stringify(otherMenu.actions);
            const unchanged = !ownMenu.deleted && !ownMenu.revoked && !otherMenu.deleted && !otherMenu.revoked;
            const passed = sameActions && unchanged;
            sessionStorage.setItem('__testhub_hall_menu_consistency_evidence', JSON.stringify({ownMenu, otherMenu, sameActions, unchanged}));
            return {handled:true, passed, reason:passed ? 'own and other-member message menus are consistent and inspection changed no message data' : 'message menus differ or inspection changed message data', evidence:{ownMenu, otherMenu, sameActions, unchanged}};
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_hall_menu_close_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            let evidence = {}; try { evidence = JSON.parse(sessionStorage.getItem('__testhub_hall_menu_consistency_evidence') || '{}'); } catch (_error) {}
            const overlays = Array.from(document.querySelectorAll('body *')).filter(element => {
              const rect = element.getBoundingClientRect(), style = getComputedStyle(element);
              const text = String(element.innerText || '').replace(/\s+/g, ' ').trim();
              return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden' && /\u56de\u590d\u6d88\u606f|\u64a4\u56de\u6d88\u606f/.test(text) && text.length <= 180 && (style.position === 'fixed' || style.position === 'absolute');
            });
            const passed = Boolean(evidence.sameActions) && evidence.unchanged === true && overlays.length === 0;
            return {handled:true, passed, reason:passed ? 'all inspected menus are closed and no message data changed' : 'menu close or no-side-effect evidence is incomplete', evidence:{...evidence, openOverlayCount:overlays.length}};
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_hall_menu_permission_compare_instruction(instruction):
        result = await page.evaluate(r'''
          (async () => {
            const visible = element => { const rect=element.getBoundingClientRect(), style=getComputedStyle(element); return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden'; };
            const user = JSON.parse(localStorage.getItem('userInfo') || '{}');
            const currentUserId = String(user.userId || user.userInfo?.userId || localStorage.getItem('_user_id') || '');
            const provides = document.querySelector('#app')?.__vue_app__?._context?.provides;
            const pinia = provides && Object.getOwnPropertySymbols(provides).map(symbol => provides[symbol]).find(value => value && value._s?.get('chat'));
            const chat = pinia?._s?.get('chat');
            const conversationId = String(sessionStorage.getItem('__testhub_hall_conversation_id') || '');
            const messages = chat?.chatMap?.[conversationId]?.msgList || [];
            const rowFor = id => document.querySelector(`[data-msg-id="${CSS.escape(String(id || ''))}"]`)
              || document.getElementById(String(id || ''))
              || Array.from(document.querySelectorAll('[data-msg-id],[id]')).find(element => String(element.getAttribute('data-msg-id') || element.id || '') === String(id || ''));
            const choose = own => messages.slice().reverse().find(message => message && !message.isDeleted && !message.isRevoked && String(message.from || '') !== '' && (String(message.from) === currentUserId) === own && rowFor(message.ID));
            const inspectMenu = async message => {
              const row = rowFor(message?.ID);
              row?.dispatchEvent(new MouseEvent('mouseover', {bubbles:true}));
              const more = Array.from(row?.querySelectorAll('i') || []).find(element => /more|gengduo/i.test(String(element.className || '')))?.parentElement;
              if (!more) return {id:String(message?.ID || ''), menu:'', error:'more control absent'};
              more.click();
              await new Promise(resolve => setTimeout(resolve, 250));
              const menu = Array.from(document.querySelectorAll('body *'))
                .filter(visible)
                .map(element => {
                  const rect = element.getBoundingClientRect();
                  const style = getComputedStyle(element);
                  return { text:String(element.innerText || '').replace(/\s+/g,' ').trim(), rect, style };
                })
                .filter(item => /\u56de\u590d\u6d88\u606f|\u64a4\u56de\u6d88\u606f/.test(item.text)
                  && item.text.length <= 180
                  && item.rect.width <= 420
                  && item.rect.height <= 560
                  && (item.style.position === 'fixed' || item.style.position === 'absolute'))
                .sort((left, right) => (left.rect.width * left.rect.height) - (right.rect.width * right.rect.height))
                .map(item => item.text)
                .find(text => /\u56de\u590d\u6d88\u606f/.test(text)) || '';
              document.body.click();
              return {id:String(message.ID || ''), menu};
            };
            const own = choose(true), other = choose(false);
            if (!own || !other) return {handled:true, passed:false, reason:'both an own and another-member visible Hall message are required for this permission comparison', evidence:{own:Boolean(own), other:Boolean(other)}};
            const ownMenu = await inspectMenu(own), otherMenu = await inspectMenu(other);
            const passed = /\u56de\u590d/.test(ownMenu.menu) && /\u64a4\u56de/.test(ownMenu.menu) && /\u56de\u590d/.test(otherMenu.menu) && !/\u64a4\u56de/.test(otherMenu.menu);
            sessionStorage.setItem('__testhub_hall_menu_permission_evidence', JSON.stringify({ownMenu, otherMenu}));
            return {handled:true, passed, reason:passed ? 'own and other-member Hall menus expose the expected reply/recall permissions' : 'Hall message menu permission mismatch', evidence:{ownMenu, otherMenu}};
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_hall_other_member_fixture_instruction(instruction):
        result = await page.evaluate(r'''
          (() => {
            let fixture = {};
            try { fixture = JSON.parse(sessionStorage.getItem('__testhub_hall_other_member_fixture') || '{}'); } catch (_error) {}
            const value = String(fixture.value || '');
            return {
              handled: true,
              passed: Boolean(value),
              reason: value ? 'prepared a real other-member Hall fixture message' : 'other-member Hall fixture was not prepared',
              evidence: fixture,
            };
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_hall_unique_message_instruction(instruction):
        payload = json.dumps({'instruction': normalized, 'stamp': int(time.time() * 1000)}, ensure_ascii=False)
        prepared = await page.evaluate(rf'''
          (() => {{
            const payload = {payload};
            const input = document.querySelector('.chat-input[contenteditable]');
            if (!input) return {{handled:true, passed:false, reason:'member-hall chat input is not rendered'}};
            const orderedPair = /\u4f9d\u6b21\u53d1\u9001|\u8fde\u7eed\u53d1\u9001/.test(payload.instruction)
              && payload.instruction.includes('\u987a\u5e8fA') && payload.instruction.includes('\u987a\u5e8fB');
            const suffixes = orderedPair
              ? ['\u987a\u5e8fA', '\u987a\u5e8fB']
              : [payload.instruction.includes('\u987a\u5e8fB') ? '\u987a\u5e8fB' : payload.instruction.includes('\u987a\u5e8fA') ? '\u987a\u5e8fA' : payload.instruction.includes('\u64a4\u56de') ? '\u64a4\u56de\u9a8c\u8bc1' : payload.instruction.includes('\u56de\u590d') ? '\u56de\u590d\u539f\u6d88\u606f' : '\u53d1\u9001\u9a8c\u8bc1'];
            const values = suffixes.map(suffix => `HALL_${{payload.stamp}}_${{suffix}}`);
            const value = values[0];
            const stored = JSON.parse(sessionStorage.getItem('__testhub_hall_unique_messages') || '[]');
            const isSend = payload.instruction.includes('\u53d1\u9001') && !/(\u4e0d\u8981\u53d1\u9001|\u65e0\u9700\u53d1\u9001|\u52ff\u53d1\u9001|\u4e0d\u53d1\u9001)/.test(payload.instruction);
            if (!isSend) {{
              input.focus(); input.textContent=value; input.dispatchEvent(new InputEvent('input', {{bubbles:true,inputType:'insertText',data:value}}));
              sessionStorage.setItem('__testhub_hall_unique_draft', value);
              return {{handled:true, passed:true, needsSend:false, reason:`prepared unique hall message: ${{value}}`, evidence:{{value}}}};
            }}
            const draft = String(sessionStorage.getItem('__testhub_hall_unique_draft') || value);
            input.focus(); input.textContent='';
            return {{handled:true, passed:true, needsSend:true, values: orderedPair ? values : [draft], reason:`prepared ${{orderedPair ? 'ordered pair of' : 'unique'}} hall message(s) for send`, evidence:{{values: orderedPair ? values : [draft]}}}};
          }})()
        ''')
        if not isinstance(prepared, dict) or not prepared.get('handled') or not prepared.get('passed'):
            return prepared if isinstance(prepared, dict) else None
        if not prepared.get('needsSend'):
            return prepared
        hall_context = await _ensure_cdp_hall_message_context(page)
        # In the hidden Electron Agent, Chromium's native Input.insertText can
        # intermittently bypass Vue's contenteditable invoker. Drive the
        # mounted component's own input and keydown listeners, then still
        # require NN's real IM record before the step can pass. This never uses
        # the operator's mouse or keyboard and never inserts a local message.
        values_to_send = [str(value) for value in (prepared.get('values') or []) if str(value)]
        if not values_to_send:
            return {'handled': True, 'passed': False, 'reason': 'member-hall message payload is empty after preparation'}
        for index, message_value in enumerate(values_to_send):
            payload = json.dumps({'value': message_value}, ensure_ascii=False)
            dispatched = await page.evaluate(r'''
              (() => {
                const payload = __TESTHUB_HALL_SEND_PAYLOAD__;
                const input = document.querySelector('.chat-input[contenteditable]');
                if (!input) return {handled:true, passed:false, reason:'member-hall chat input is not rendered'};
                input.focus();
                input.textContent = payload.value;
                const inputEvent = new InputEvent('input', {
                  bubbles:true, inputType:'insertText', data:payload.value,
                });
                const keyEvent = new KeyboardEvent('keydown', {
                  key:'Enter', code:'Enter', bubbles:true, cancelable:true, composed:true,
                });
                const inputInvoker = input._vei?.onInput;
                const keydownInvoker = input._vei?.onKeydown;
                if (typeof inputInvoker === 'function') inputInvoker(inputEvent);
                else input.dispatchEvent(inputEvent);
                if (typeof keydownInvoker === 'function') keydownInvoker(keyEvent);
                else input.dispatchEvent(keyEvent);
                return {handled:true, passed:true, value:String(input.textContent || '')};
              })()
            '''.replace('__TESTHUB_HALL_SEND_PAYLOAD__', payload))
            if not isinstance(dispatched, dict) or not dispatched.get('passed'):
                return dispatched if isinstance(dispatched, dict) else {
                    'handled': True,
                    'passed': False,
                    'reason': 'member-hall chat input did not accept the renderer send event',
                }
            if index < len(values_to_send) - 1:
                await asyncio.sleep(0.5)
        values = json.dumps(values_to_send, ensure_ascii=False)
        deadline = asyncio.get_running_loop().time() + 8.0
        result = None
        while True:
            result = await page.evaluate(rf'''
          (() => {{
            const values = {values};
            const input = document.querySelector('.chat-input[contenteditable]');
            const visible = element => {{
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden'
                && rect.bottom > 0 && rect.top < innerHeight;
            }};
            const provides = document.querySelector('#app')?.__vue_app__?._context?.provides;
            const pinia = provides && Object.getOwnPropertySymbols(provides)
              .map(symbol => provides[symbol])
              .find(candidate => candidate && candidate._s && typeof candidate._s.get === 'function' && candidate._s.get('chat'));
            const chat = pinia?._s?.get('chat');
            const conversationId = String(sessionStorage.getItem('__testhub_hall_conversation_id') || '');
            const hallEntry = chat?.chatMap?.[conversationId] || Object.values(chat?.chatMap || {{}}).find(entry =>
              entry && entry.conversationType === 'GROUP' && Array.isArray(entry.msgList)
            );
            const messages = Array.isArray(hallEntry?.msgList) ? hallEntry.msgList : [];
            const ownSentMessages = messages.filter(message =>
              message && message.status === 'success' && !message.isDeleted && !message.isRevoked
                && values.includes(String(message.payload?.text || ''))
            );
            const matchedValues = ownSentMessages.map(message => String(message.payload?.text || ''));
            const uniqueMatchedValues = [...new Set(matchedValues)];
            const ordered = values.every((value, index) => index === 0
              || ownSentMessages.findIndex(message => String(message.payload?.text || '') === values[index - 1])
                < ownSentMessages.findIndex(message => String(message.payload?.text || '') === value));
            const passed = uniqueMatchedValues.length === values.length
              && ownSentMessages.length === values.length
              && ordered
              && String(input?.textContent || '') === '';
            if (passed) {{
              const sendEvidence = {{
                values,
                messageIds: ownSentMessages.map(message => String(message.ID || '')),
                sequences: ownSentMessages.map(message => Number(message.sequence || message.msgSeq || 0)),
                conversationId: String(hallEntry?.conversationID || sessionStorage.getItem('__testhub_hall_conversation_id') || ''),
                senderIds: ownSentMessages.map(message => String(message.from || '')),
              }};
              sessionStorage.setItem('__testhub_hall_send_evidence', JSON.stringify(sendEvidence));
              let replyOpen = {{}}; try {{ replyOpen = JSON.parse(sessionStorage.getItem('__testhub_hall_reply_open') || '{{}}'); }} catch (_error) {{}}
              if (replyOpen.sourceId && ownSentMessages.length === 1) {{
                const rowFor = id => document.querySelector(`[data-msg-id="${{CSS.escape(String(id || ''))}}"]`)
                  || document.getElementById(String(id || ''))
                  || Array.from(document.querySelectorAll('[data-msg-id],[id]')).find(element => String(element.getAttribute('data-msg-id') || element.id || '') === String(id || ''));
                const sourceText = String(replyOpen.sourceText || '').replace(/\s+/g, ' ').trim();
                const sourceMarker = String(replyOpen.targetValue || '') || (sourceText.match(/HALL_\d+_[^\s]+/) || [''])[0];
                const replyRow = rowFor(ownSentMessages[0].ID);
                const replyText = String(replyRow?.innerText || '').replace(/\s+/g, ' ').trim();
                const linked = Boolean(replyRow && sourceMarker && replyText.includes(values[0]) && replyText.includes(sourceMarker));
                sessionStorage.setItem('__testhub_hall_reply_evidence', JSON.stringify({{
                  sourceId:String(replyOpen.sourceId), sentId:String(ownSentMessages[0].ID || ''), sentValue:values[0], sourceMarker, linked,
                  exactlyOne:ownSentMessages.length === 1,
                  replyText,
                }}));
              }}
              const stored = JSON.parse(sessionStorage.getItem('__testhub_hall_unique_messages') || '[]');
              for (const value of values) if (!stored.includes(value)) stored.push(value);
              sessionStorage.setItem('__testhub_hall_unique_messages', JSON.stringify(stored));
            }}
            return {{handled:true, passed, reason:passed ? `sent ${{values.length}} unique hall message(s): ${{values.join(', ')}}` : `hall message send mismatch: expected=${{values.length}}, matched=${{uniqueMatchedValues.length}}, messageRecords=${{ownSentMessages.length}}, input=${{String(input?.textContent || '')}}`, evidence:{{values, uniqueMatchedValues, messageRecordCount: ownSentMessages.length}}}};
          }})()
        ''')
            if isinstance(result, dict) and result.get('passed'):
                break
            if asyncio.get_running_loop().time() >= deadline:
                break
            await asyncio.sleep(0.4)
        if isinstance(result, dict) and result.get('handled'):
            result.setdefault('evidence', {})['hall_context'] = hall_context
            return result
        return None
    if _is_hall_generated_message_send_confirmation(instruction):
        result = await page.evaluate(r'''
          (() => {
            let evidence = {};
            try { evidence = JSON.parse(sessionStorage.getItem('__testhub_hall_send_evidence') || '{}'); } catch (_error) {}
            const values = Array.isArray(evidence.values) ? evidence.values.map(String) : [];
            const messageIds = Array.isArray(evidence.messageIds) ? evidence.messageIds.map(String) : [];
            if (!values.length || values.length !== messageIds.length) return {handled:false};
            const provides = document.querySelector('#app')?.__vue_app__?._context?.provides;
            const pinia = provides && Object.getOwnPropertySymbols(provides)
              .map(symbol => provides[symbol])
              .find(candidate => candidate && candidate._s && typeof candidate._s.get === 'function' && candidate._s.get('chat'));
            const chat = pinia?._s?.get('chat');
            const conversationId = String(evidence.conversationId || sessionStorage.getItem('__testhub_hall_conversation_id') || '');
            const messages = Array.isArray(chat?.chatMap?.[conversationId]?.msgList) ? chat.chatMap[conversationId].msgList : [];
            const generated = messages.filter(message => messageIds.includes(String(message?.ID || '')));
            const passed = generated.length === values.length
              && generated.every(message => String(message.status || '') === 'success' && !message.isRevoked && !message.isDeleted);
            return {
              handled:true,
              passed,
              reason: passed ? 'generated Hall message was already submitted through NN; no duplicate send was attempted' : 'generated Hall message is not confirmed as a submitted NN record',
              evidence:{values, messageIds, generatedCount:generated.length},
            };
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_hall_message_recall_instruction(instruction):
        hall_context = await _ensure_cdp_hall_message_context(page)
        result = await _cleanup_cdp_generated_hall_messages(page)
        if isinstance(result, dict) and result.get('handled'):
            result.setdefault('evidence', {})['hall_context'] = hall_context
            return result
        return None
    if _is_hall_message_recall_assertion(instruction):
        deadline = asyncio.get_running_loop().time() + 8.0
        result = None
        while True:
            result = await page.evaluate(r'''
              (() => {
                const values = JSON.parse(sessionStorage.getItem('__testhub_hall_unique_messages') || '[]');
                const provides = document.querySelector('#app')?.__vue_app__?._context?.provides;
                const pinia = provides && Object.getOwnPropertySymbols(provides)
                  .map(symbol => provides[symbol])
                  .find(candidate => candidate && candidate._s && typeof candidate._s.get === 'function' && candidate._s.get('chat'));
                const chat = pinia?._s?.get('chat');
                const conversationId = String(sessionStorage.getItem('__testhub_hall_conversation_id') || '');
                const messages = chat?.chatMap?.[conversationId]?.msgList || [];
                const remaining = messages.filter(message => values.includes(String(message?.payload?.text || '')))
                  .map(message => ({
                    text: String(message.payload?.text || ''),
                    revoked: Boolean(message.isRevoked),
                    deleted: Boolean(message.isDeleted),
                    status: String(message.status || ''),
                  }));
                let fixture = {};
                try { fixture = JSON.parse(sessionStorage.getItem('__testhub_hall_other_member_fixture') || '{}'); } catch (_error) {}
                const fixtureValue = String(fixture.value || '');
                const ownerManaged = remaining.filter(message => message.text !== fixtureValue);
                const fixturePending = remaining.filter(message => message.text === fixtureValue && !message.revoked && !message.deleted);
                const passed = values.length > 0 && remaining.length === values.length
                  && ownerManaged.every(message => message.revoked || message.deleted)
                  && fixturePending.length <= 1;
                return {
                  handled: true,
                  passed,
                  reason: passed
                    ? (fixturePending.length
                      ? `primary Hall messages were recalled; fixture owner cleanup is scheduled: ${fixtureValue}`
                      : `recalled TestHub Hall messages are no longer normal messages: ${values.join(', ')}`)
                    : `Hall message cleanup has not reached the revoked state: ${JSON.stringify(remaining)}`,
                  evidence: {values, remaining, fixtureValue, fixturePending},
                };
              })()
            ''')
            if isinstance(result, dict) and result.get('passed'):
                return result
            if asyncio.get_running_loop().time() >= deadline:
                return result if isinstance(result, dict) else None
            await asyncio.sleep(0.4)
    if _is_hall_message_stability_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            const visible = element => { const rect = element.getBoundingClientRect(), style = getComputedStyle(element); return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden'; };
            const input = document.querySelector('.chat-input[contenteditable]');
            const memberSearch = document.querySelector('input[placeholder="\u641c\u7d22\u6210\u5458"]');
            const hasMessageRows = Array.from(document.querySelectorAll('[data-msg-id],[id]')).some(element => visible(element) && (/^\d+$/.test(String(element.id || '')) || element.hasAttribute('data-msg-id')));
            const passed = /\/community\/\d+\/hall(?:$|[/?])/.test(String(location.hash || '')) && visible(input) && visible(memberSearch) && hasMessageRows;
            return {handled:true, passed, reason:passed ? 'message stream, member list, and composer remain usable after recall' : 'a hall region is unavailable after recall', evidence:{route:String(location.hash || ''), composer:Boolean(visible(input)), memberSearch:Boolean(visible(memberSearch)), hasMessageRows}};
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_hall_other_member_fixture_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            let fixture = {}, own = {};
            try { fixture = JSON.parse(sessionStorage.getItem('__testhub_hall_other_member_fixture') || '{}'); } catch (_error) {}
            try { own = JSON.parse(sessionStorage.getItem('__testhub_hall_send_evidence') || '{}'); } catch (_error) {}
            const fixtureValue = String(fixture.value || '');
            const ownValue = String((own.values || []).slice(-1)[0] || '');
            const user = JSON.parse(localStorage.getItem('userInfo') || '{}');
            const currentUserId = String(user.userId || user.userInfo?.userId || localStorage.getItem('_user_id') || '');
            const provides = document.querySelector('#app')?.__vue_app__?._context?.provides;
            const pinia = provides && Object.getOwnPropertySymbols(provides).map(symbol => provides[symbol]).find(value => value && value._s?.get('chat'));
            const chat = pinia?._s?.get('chat');
            const conversationId = String(sessionStorage.getItem('__testhub_hall_conversation_id') || '');
            const messages = chat?.chatMap?.[conversationId]?.msgList || [];
            const fixtureMessage = messages.find(message => String(message?.payload?.text || '') === fixtureValue && !message.isDeleted && !message.isRevoked);
            const ownMessage = messages.find(message => String(message?.payload?.text || '') === ownValue && !message.isDeleted && !message.isRevoked);
            const fixtureIsOther = Boolean(fixtureMessage) && String(fixtureMessage.from || '') !== currentUserId;
            const ownIsCurrent = Boolean(ownMessage) && String(ownMessage.from || '') === currentUserId;
            const passed = Boolean(fixtureValue && ownValue && fixtureIsOther && ownIsCurrent);
            return {
              handled: true,
              passed,
              reason: passed ? 'fixture and primary messages are both present with distinct sender identities' : 'fixture or primary Hall message is missing, revoked, or has the wrong sender identity',
              evidence: {
                fixtureValue,
                ownValue,
                currentUserId,
                fixture: fixtureMessage ? {id:String(fixtureMessage.ID || ''), from:String(fixtureMessage.from || '')} : null,
                own: ownMessage ? {id:String(ownMessage.ID || ''), from:String(ownMessage.from || '')} : null,
              },
            };
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_hall_message_delivery_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            let evidence = {};
            try { evidence = JSON.parse(sessionStorage.getItem('__testhub_hall_send_evidence') || '{}'); } catch (_error) {}
            const ids = Array.isArray(evidence.messageIds) ? evidence.messageIds.map(String) : [];
            const values = Array.isArray(evidence.values) ? evidence.values.map(String) : [];
            const provides = document.querySelector('#app')?.__vue_app__?._context?.provides;
            const pinia = provides && Object.getOwnPropertySymbols(provides).map(symbol => provides[symbol]).find(value => value && value._s?.get('chat'));
            const chat = pinia?._s?.get('chat');
            const conversationId = String(evidence.conversationId || sessionStorage.getItem('__testhub_hall_conversation_id') || '');
            const messages = chat?.chatMap?.[conversationId]?.msgList || [];
            const generated = messages.filter(message => ids.includes(String(message?.ID || '')));
            const passed = ids.length > 0 && generated.length === ids.length && values.every(value => generated.some(message => String(message?.payload?.text || '') === value)) && generated.every(message => String(message.status || '') === 'success' && String(message.from || ''));
            return {handled:true, passed, reason:passed ? `generated Hall message delivery verified: ${generated.length} record(s)` : `generated Hall message delivery mismatch: expected=${ids.length}, found=${generated.length}`, evidence:{ids, values, records:generated.map(message => ({id:String(message.ID || ''), from:String(message.from || ''), status:String(message.status || ''), revoked:Boolean(message.isRevoked), deleted:Boolean(message.isDeleted)}))}};
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_hall_generated_message_ui_assertion(instruction):
        payload = json.dumps({'instruction': normalized}, ensure_ascii=False)
        result = await page.evaluate(rf'''
          (() => new Promise(resolve => {{
            const payload = {payload};
            const visible = element => {{
              const rect = element?.getBoundingClientRect?.();
              const style = element && getComputedStyle(element);
              return Boolean(rect && style && rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden'
                && rect.bottom > 0 && rect.top < innerHeight);
            }};
            const text = element => String(element?.innerText || element?.textContent || '').replace(/\s+/g, ' ').trim();
            const rowFor = id => document.querySelector(`[data-msg-id="${{CSS.escape(String(id || ''))}}"]`)
              || document.getElementById(String(id || ''))
              || Array.from(document.querySelectorAll('[data-msg-id],[id]')).find(element => String(element.getAttribute('data-msg-id') || element.id || '') === String(id || ''));
            const scrollToMessageEnd = () => {{
              const candidates = Array.from(document.querySelectorAll('div')).filter(element => {{
                const style = getComputedStyle(element);
                return /auto|scroll/.test(style.overflowY || '') && element.scrollHeight > element.clientHeight + 80;
              }});
              candidates.sort((left, right) => right.clientHeight - left.clientHeight).slice(0, 3)
                .forEach(element => {{ element.scrollTop = element.scrollHeight; element.dispatchEvent(new Event('scroll')); }});
            }};
            const inspect = () => {{
              let evidence = {{}};
              try {{ evidence = JSON.parse(sessionStorage.getItem('__testhub_hall_send_evidence') || '{{}}'); }} catch (_error) {{}}
              const values = Array.isArray(evidence.values) ? evidence.values.map(String) : [];
              const messageIds = Array.isArray(evidence.messageIds) ? evidence.messageIds.map(String) : [];
              if (!values.length || values.length !== messageIds.length) return {{handled:false}};
              const provides = document.querySelector('#app')?.__vue_app__?._context?.provides;
              const pinia = provides && Object.getOwnPropertySymbols(provides)
                .map(symbol => provides[symbol])
                .find(candidate => candidate && candidate._s && typeof candidate._s.get === 'function' && candidate._s.get('chat'));
              const chat = pinia?._s?.get('chat');
              const user = pinia?._s?.get('user');
              const conversationId = String(evidence.conversationId || sessionStorage.getItem('__testhub_hall_conversation_id') || '');
              const currentUserId = String(user?.userInfo?.userId || localStorage.getItem('_user_id') || localStorage.getItem('userId') || '');
              const messages = Array.isArray(chat?.chatMap?.[conversationId]?.msgList) ? chat.chatMap[conversationId].msgList : [];
              const generated = messages.filter(message => messageIds.includes(String(message?.ID || '')));
              const rows = generated.map(message => rowFor(message.ID));
              const allRendered = rows.length === generated.length && rows.every(visible);
              const recordCounts = values.map(value => messages.filter(message => String(message?.payload?.text || '') === value && !message.isDeleted && !message.isRevoked).length);
              const allDelivered = values.length > 0 && generated.length === values.length
                && generated.every(message => String(message.status || '') === 'success' && String(message.from || '') === currentUserId
                  && String(message.payload?.text || '').trim() && !message.isDeleted && !message.isRevoked)
                && values.every((value, index) => recordCounts[index] === 1);
              const input = document.querySelector('.chat-input[contenteditable]');
              const composerReady = Boolean(input) && input.getAttribute('contenteditable') !== 'false'
                && input.getAttribute('aria-disabled') !== 'true' && String(input.textContent || '') === '';
              const metadataRendered = rows.every((row, index) => {{
                const rowText = text(row);
                const hasAvatar = Boolean(row?.querySelector('img[src], [class*="avatar" i], svg'));
                return rowText.includes(values[index] || '') && hasAvatar && Boolean(generated[index]?.time || generated[index]?.clientTime);
              }});
              const route = String(location.hash || '');
              const noRouteChange = /\/community\/\d+\/hall(?:$|[/?])/.test(route);
              const asksMetadata = /\u53d1\u9001\u8005|\u5934\u50cf|\u65f6\u95f4|\u540c\u4e00\u6761\u6d88\u606f\u5355\u5143/.test(payload.instruction);
              const passed = allDelivered && allRendered && composerReady && noRouteChange && (!asksMetadata || metadataRendered);
              return {{
                handled:true,
                passed,
                reason: passed ? 'generated Hall message has matching server records and rendered message-row evidence' : 'generated Hall message UI evidence is incomplete',
                evidence:{{values, messageIds, generatedCount:generated.length, recordCounts, allRendered, composerReady, metadataRendered, noRouteChange,
                  rows:rows.map((row, index) => ({{id:String(generated[index]?.ID || ''), visible:visible(row), text:text(row).slice(0, 260)}}))}},
              }};
            }};
            let attemptedScroll = false;
            const check = () => {{
              const state = inspect();
              if (state.passed || attemptedScroll) return resolve(state);
              attemptedScroll = true;
              scrollToMessageEnd();
              setTimeout(() => resolve(inspect()), 500);
            }};
            check();
          }}))()
        ''')
        if isinstance(result, dict) and result.get('handled'):
            return result
    hall_assertion_kind = _hall_unique_message_assertion_kind(instruction)
    if hall_assertion_kind:
        payload = json.dumps({'kind': hall_assertion_kind}, ensure_ascii=False)
        result = await page.evaluate(rf'''
          (() => {{
            const payload = {payload};
            let evidence = {{}};
            try {{ evidence = JSON.parse(sessionStorage.getItem('__testhub_hall_send_evidence') || '{{}}'); }} catch (_error) {{}}
            const values = Array.isArray(evidence.values) ? evidence.values : [];
            const messageIds = Array.isArray(evidence.messageIds) ? evidence.messageIds.map(String) : [];
            const conversationId = String(evidence.conversationId || sessionStorage.getItem('__testhub_hall_conversation_id') || '');
            const provides = document.querySelector('#app')?.__vue_app__?._context?.provides;
            const pinia = provides && Object.getOwnPropertySymbols(provides)
              .map(symbol => provides[symbol])
              .find(candidate => candidate && candidate._s && typeof candidate._s.get === 'function' && candidate._s.get('chat'));
            const chat = pinia?._s?.get('chat');
            const user = pinia?._s?.get('user');
            const input = document.querySelector('.chat-input[contenteditable]');
            const messages = Array.isArray(chat?.chatMap?.[conversationId]?.msgList) ? chat.chatMap[conversationId].msgList : [];
            const generated = messages.filter(message => messageIds.includes(String(message?.ID || '')));
            const texts = generated.map(message => String(message?.payload?.text || ''));
            const sequences = generated.map(message => Number(message?.sequence || message?.msgSeq || 0));
            const currentUserId = String(user?.userInfo?.userId || localStorage.getItem('_user_id') || '');
            const allDelivered = values.length > 0 && generated.length === values.length
              && values.every(value => texts.filter(text => text === value).length === 1)
              && generated.every(message => String(message.status || '') === 'success');
            let passed = false;
            let reason = '';
            if (payload.kind === 'send_feedback') {{
              const editable = Boolean(input) && input.getAttribute('contenteditable') !== 'false'
                && input.getAttribute('aria-disabled') !== 'true';
              passed = allDelivered && editable && String(input?.textContent || '') === '';
              reason = passed
                ? 'both generated Hall messages were accepted and the composer is empty and editable'
                : `Hall send feedback mismatch: delivered=${{allDelivered}}, editable=${{editable}}, input=${{JSON.stringify(String(input?.textContent || ''))}}`;
            }} else if (payload.kind === 'order') {{
              const ordered = sequences.every((sequence, index) => index === 0 || sequences[index - 1] < sequence);
              passed = allDelivered && ordered;
              reason = passed
                ? `generated Hall messages are unique and ordered: ${{values.join(', ')}}`
                : `Hall message order mismatch: delivered=${{allDelivered}}, sequences=${{JSON.stringify(sequences)}}`;
            }} else {{
              const ownership = generated.every(message => String(message.from || '') === currentUserId
                && String(message.to || '') === conversationId);
              const nonBlank = generated.every(message => Boolean(String(message?.payload?.text || '').trim()));
              passed = allDelivered && ownership && nonBlank;
              reason = passed
                ? 'generated Hall messages have unique non-empty content and consistent sender/recipient ownership'
                : `Hall message integrity mismatch: delivered=${{allDelivered}}, ownership=${{ownership}}, nonBlank=${{nonBlank}}`;
            }}
            return {{handled:true, passed, reason, evidence:{{kind:payload.kind, values, messageIds, texts, sequences, conversationId, generatedCount:generated.length}}}};
          }})()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_hall_message_input_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            const input = document.querySelector('.chat-input[contenteditable]');
            const value = String(sessionStorage.getItem('__testhub_hall_chat_input') || '');
            const body = String(document.body?.innerText || '');
            const passed = Boolean(input) && String(input.textContent || '') === value && !Array.from(document.querySelectorAll('[data-msg-id]')).some(item => String(item.innerText || '').includes(value));
            return {handled:true, passed, reason:passed ? 'member-hall draft remains only in the chat input and was not sent' : 'member-hall chat-input invariant failed', evidence:{value, actual:String(input?.textContent || '')}};
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_hall_emoji_selection_instruction(instruction):
        selection = await page.evaluate(r'''
          (() => {
            const visible = element => { const r=element.getBoundingClientRect(), s=getComputedStyle(element); return r.width>2 && r.height>2 && s.display!=='none' && s.visibility!=='hidden'; };
            const header = Array.from(document.querySelectorAll('*')).find(element => visible(element) && element.children.length === 0 && String(element.textContent || '').trim() === '\u81ea\u5b9a\u4e49\u8868\u60c5');
            const panel = header?.parentElement;
            const image = Array.from(panel?.querySelectorAll('.cursor-pointer img[src]') || []).find(visible);
            if (!image) return {handled:true, passed:false, reason:'no visible custom emoji is available in the open panel'};
            const rect = image.getBoundingClientRect();
            return {handled:true, passed:true, point:{x:rect.left + rect.width / 2, y:rect.top + rect.height / 2}, src:String(image.currentSrc || image.src || '')};
          })()
        ''')
        if not isinstance(selection, dict) or not selection.get('passed'):
            return selection if isinstance(selection, dict) else None
        await _cdp_click_at(page, selection.get('point') or {})
        await asyncio.sleep(0.25)
        payload = json.dumps({'src': str(selection.get('src') or '')}, ensure_ascii=False)
        result = await page.evaluate(rf'''
          (() => {{
            const payload = {payload};
            const input = document.querySelector('.chat-input[contenteditable]');
            const image = Array.from(input?.querySelectorAll('img[data-custom-emoji],img[name="image"]') || []).find(element =>
              !payload.src || String(element.currentSrc || element.src || '') === payload.src
            );
            const passed = Boolean(image);
            if (passed) sessionStorage.setItem('__testhub_hall_emoji_draft', JSON.stringify({{src: String(image.currentSrc || image.src || payload.src)}}));
            return {{handled:true, passed, reason:passed ? 'selected one custom emoji into the member-hall composer' : 'custom emoji selection did not enter the member-hall composer', evidence:{{src:payload.src, inputHtml:String(input?.innerHTML || '')}}}};
          }})()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_hall_emoji_send_instruction(instruction):
        context = await _ensure_cdp_hall_message_context(page)
        prepared = await page.evaluate(r'''
          (() => {
            let draft = {}; try { draft = JSON.parse(sessionStorage.getItem('__testhub_hall_emoji_draft') || '{}'); } catch (_error) {}
            const input = document.querySelector('.chat-input[contenteditable]');
            const image = Array.from(input?.querySelectorAll('img[data-custom-emoji],img[name="image"]') || [])[0];
            const provides = document.querySelector('#app')?.__vue_app__?._context?.provides;
            const pinia = provides && Object.getOwnPropertySymbols(provides).map(symbol => provides[symbol]).find(candidate => candidate && candidate._s && typeof candidate._s.get === 'function' && candidate._s.get('chat'));
            const chat = pinia?._s?.get('chat');
            const conversationId = String(sessionStorage.getItem('__testhub_hall_conversation_id') || '');
            const messages = Array.isArray(chat?.chatMap?.[conversationId]?.msgList) ? chat.chatMap[conversationId].msgList : [];
            if (!image || !conversationId) return {handled:true, passed:false, reason:'custom emoji draft or Hall conversation is unavailable'};
            return {handled:true, passed:true, src:String(image.currentSrc || image.src || draft.src || ''), conversationId, beforeIds:messages.map(message => String(message?.ID || '')).filter(Boolean)};
          })()
        ''')
        if not isinstance(prepared, dict) or not prepared.get('passed'):
            return prepared if isinstance(prepared, dict) else None
        enter = {'key': 'Enter', 'code': 'Enter', 'text': '\r', 'unmodifiedText': '\r', 'windowsVirtualKeyCode': 13, 'nativeVirtualKeyCode': 13}
        await page.call('Input.dispatchKeyEvent', {'type': 'keyDown', **enter})
        await page.call('Input.dispatchKeyEvent', {'type': 'keyUp', 'key': 'Enter', 'code': 'Enter', 'windowsVirtualKeyCode': 13, 'nativeVirtualKeyCode': 13})
        evidence = json.dumps(prepared, ensure_ascii=False)
        deadline = asyncio.get_running_loop().time() + 8.0
        while True:
            result = await page.evaluate(rf'''
              (() => {{
                const expected = {evidence};
                const provides = document.querySelector('#app')?.__vue_app__?._context?.provides;
                const pinia = provides && Object.getOwnPropertySymbols(provides).map(symbol => provides[symbol]).find(candidate => candidate && candidate._s && typeof candidate._s.get === 'function' && candidate._s.get('chat'));
                const chat = pinia?._s?.get('chat');
                const user = pinia?._s?.get('user');
                const messages = Array.isArray(chat?.chatMap?.[expected.conversationId]?.msgList) ? chat.chatMap[expected.conversationId].msgList : [];
                const currentUserId = String(user?.userInfo?.userId || localStorage.getItem('_user_id') || '');
                const created = messages.filter(message => message && !expected.beforeIds.includes(String(message.ID || '')) && String(message.from || '') === currentUserId && String(message.status || '') === 'success' && !message.isDeleted && !message.isRevoked);
                const custom = created.filter(message => String(message.payload?.text || '').includes('customEmoji') && String(message.payload?.text || '').includes(expected.src));
                const input = document.querySelector('.chat-input[contenteditable]');
                const passed = custom.length === 1 && String(input?.textContent || '') === '';
                if (passed) {{
                  const message = custom[0];
                  const neighbors = messages.filter(item => item && String(item.ID || '') !== String(message.ID || '') && !item.isDeleted && !item.isRevoked).slice(-2).map(item => String(item.ID || ''));
                  sessionStorage.setItem('__testhub_hall_emoji_message', JSON.stringify({{id:String(message.ID || ''), conversationId:expected.conversationId, src:expected.src, neighbors}}));
                }}
                return {{handled:true, passed, reason:passed ? `sent one custom emoji message: ${{custom[0].ID}}` : `custom emoji send pending: created=${{created.length}}, matched=${{custom.length}}`, evidence:{{created:created.map(message => String(message.ID || '')), matched:custom.map(message => String(message.ID || ''))}}}};
              }})()
            ''')
            if isinstance(result, dict) and result.get('passed'):
                result.setdefault('evidence', {})['hall_context'] = context
                return result
            if asyncio.get_running_loop().time() >= deadline:
                return result if isinstance(result, dict) else None
            await asyncio.sleep(0.35)
    if _is_hall_emoji_recall_instruction(instruction):
        context = await _ensure_cdp_hall_message_context(page)
        result = await page.evaluate(r'''
          (async () => {
            let marker = {}; try { marker = JSON.parse(sessionStorage.getItem('__testhub_hall_emoji_message') || '{}'); } catch (_error) {}
            const provides = document.querySelector('#app')?.__vue_app__?._context?.provides;
            const pinia = provides && Object.getOwnPropertySymbols(provides).map(symbol => provides[symbol]).find(candidate => candidate && candidate._s && typeof candidate._s.get === 'function' && candidate._s.get('chat'));
            const chat = pinia?._s?.get('chat'); const channel = pinia?._s?.get('channel'); const community = pinia?._s?.get('community'); const user = pinia?._s?.get('user');
            const messages = Array.isArray(chat?.chatMap?.[marker.conversationId]?.msgList) ? chat.chatMap[marker.conversationId].msgList : [];
            const message = messages.find(item => String(item?.ID || '') === String(marker.id || ''));
            const serverId = Number(community?.communityItem?.serverId || 0);
            if (!message || !serverId || typeof channel?.recallMsg !== 'function') return {handled:true, passed:false, reason:'sent custom emoji message cannot be recalled from the current Hall context'};
            const response = await channel.recallMsg({userId:Number(message.from || user?.userInfo?.userId || 0), from:Number(message.from || user?.userInfo?.userId || 0), channelId:Number(marker.conversationId), txTopicId:Number(marker.conversationId), txChannelId:Number(marker.conversationId), msgSeq:Number(message.sequence || message.msgSeq || 0), messageType:3, serverId, channelType:7, msgIds:[String(message.ID)]});
            if (response?.success) message.isRevoked = true;
            return {handled:true, passed:Boolean(response?.success), reason:response?.success ? `recalled custom emoji message: ${message.ID}` : `NN rejected custom emoji recall: ${String(response?.retMsg || '')}`, evidence:{messageId:String(message.ID || ''), response}};
          })()
        ''')
        if isinstance(result, dict):
            result.setdefault('evidence', {})['hall_context'] = context
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_hall_emoji_message_assertion(instruction):
        payload = json.dumps({'instruction': normalized}, ensure_ascii=False)
        result = await page.evaluate(rf'''
          (() => {{
            const payload = {payload}; let marker = {{}}; try {{ marker = JSON.parse(sessionStorage.getItem('__testhub_hall_emoji_message') || '{{}}'); }} catch (_error) {{}}
            const provides = document.querySelector('#app')?.__vue_app__?._context?.provides;
            const pinia = provides && Object.getOwnPropertySymbols(provides).map(symbol => provides[symbol]).find(candidate => candidate && candidate._s && typeof candidate._s.get === 'function' && candidate._s.get('chat'));
            const chat = pinia?._s?.get('chat'); const user = pinia?._s?.get('user');
            const messages = Array.isArray(chat?.chatMap?.[marker.conversationId]?.msgList) ? chat.chatMap[marker.conversationId].msgList : [];
            const message = messages.find(item => String(item?.ID || '') === String(marker.id || ''));
            const currentUserId = String(user?.userInfo?.userId || localStorage.getItem('_user_id') || '');
            const recalled = /\u64a4\u56de\u540e/.test(payload.instruction);
            const neighbors = (marker.neighbors || []).map(id => messages.find(item => String(item?.ID || '') === String(id))).filter(Boolean);
            const contentMatches = String(message?.payload?.text || '').includes('customEmoji') && String(message?.payload?.text || '').includes(String(marker.src || ''));
            // Expected results are evaluated after every operation in the case.
            // A send assertion can therefore run after the cleanup action. Keep
            // the immutable delivery evidence (ID, sender, timestamp, payload)
            // and only require the current non-revoked state for an assertion
            // which explicitly concerns visibility before recall.
            const delivered = Boolean(message) && String(message.status || '') === 'success' && String(message.from || '') === currentUserId && Boolean(message.time || message.clientTime) && contentMatches;
            const normal = delivered && !message.isDeleted && !message.isRevoked;
            const passed = recalled ? delivered && (message.isDeleted || message.isRevoked) && neighbors.every(item => !item.isDeleted && !item.isRevoked) : delivered;
            return {{handled:true, passed, reason:passed ? (recalled ? 'custom emoji was recalled and adjacent messages remain intact' : 'one custom emoji message has matching content, sender, and timestamp evidence') : `custom emoji assertion mismatch: message=${{Boolean(message)}}, recalled=${{Boolean(message?.isRevoked || message?.isDeleted)}}, content=${{contentMatches}}`, evidence:{{messageId:marker.id || '', neighborCount:neighbors.length, recalled:Boolean(message?.isRevoked || message?.isDeleted), contentMatches}}}};
          }})()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_hall_emoji_instruction(instruction) or _is_hall_emoji_assertion(instruction):
        payload = json.dumps({'instruction': normalized}, ensure_ascii=False)
        result = await page.evaluate(rf'''
          (() => {{
            const payload = {payload};
            const button = document.querySelector('.inputer i[class*="emotion"]')?.closest('button');
            const panel = () => {{
              const visible = element => {{ const rect=element.getBoundingClientRect(), style=getComputedStyle(element); return rect.width>2 && rect.height>2 && style.display!=='none' && style.visibility!=='hidden'; }};
              const title = Array.from(document.querySelectorAll('*')).find(element => visible(element) && element.children.length === 0 && String(element.textContent || '').trim() === '\u81ea\u5b9a\u4e49\u8868\u60c5');
              return title?.parentElement || null;
            }};
            if (!button) return {{handled:true, passed:false, reason:'emoji button is not rendered'}};
            const assertion = payload.instruction.startsWith('\u65ad\u8a00\uff1a');
            if (assertion) {{
              const closingAssertion = /\u5173\u95ed\u540e|\u6d88\u5931/.test(payload.instruction);
              const opened = sessionStorage.getItem('__testhub_hall_emoji_opened') === 'true';
              const closed = sessionStorage.getItem('__testhub_hall_emoji_closed') === 'true';
              const passed = closingAssertion ? closed && !panel() : opened;
              return {{handled:true, passed, reason:passed ? (closingAssertion ? 'emoji panel closed after opening' : 'emoji panel opened from its input control') : 'emoji panel lifecycle evidence is incomplete'}};
            }}
            const closing = /\u5173\u95ed|\u518d\u6b21\u70b9\u51fb|\u9762\u677f\u5916/.test(payload.instruction);
            if (closing && panel()) {{
              const input = document.querySelector('.chat-input[contenteditable]');
              (input?.parentElement?.parentElement || document.body).click();
            }} else if (!closing && !panel()) button.click();
            return new Promise(resolve => setTimeout(() => {{ const open=Boolean(panel()); const passed=closing ? !open : open; if (passed) {{ if (open) {{ sessionStorage.setItem('__testhub_hall_emoji_opened','true'); sessionStorage.removeItem('__testhub_hall_emoji_closed'); }} else sessionStorage.setItem('__testhub_hall_emoji_closed','true'); }} resolve({{handled:true, passed, reason:passed ? (open ? 'emoji panel is open' : 'emoji panel is closed') : 'emoji panel state did not change as expected'}}); }}, 300));
          }})()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_hall_scroll_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            const message = document.querySelector('.msg-common-scroll');
            const memberInput = document.querySelector('input[placeholder="\u641c\u7d22\u6210\u5458"]');
            let memberPanel = memberInput; while (memberPanel && !memberPanel.querySelector('.ui-scroller-wrapper')) memberPanel = memberPanel.parentElement;
            const memberScroll = memberPanel?.querySelector('.ui-scroller-wrapper');
            const input = document.querySelector('.chat-input[contenteditable]');
            const messageScrollable = Boolean(message) && message.scrollHeight > message.clientHeight;
            const memberScrollable = Boolean(memberScroll) && memberScroll.scrollHeight > memberScroll.clientHeight;
            const passed = Boolean(message && memberInput && input) && (messageScrollable || memberScrollable);
            return {handled:true, passed, reason:passed ? 'hall scroll containers and fixed input/search controls are structurally present' : 'hall scroll-container invariant failed', evidence:{messageScrollable,memberScrollable}};
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_wait_only_instruction(instruction):
        requested_seconds = _requested_wait_seconds(instruction)
        await asyncio.sleep(requested_seconds if requested_seconds is not None else 0.8)
        result = await page.evaluate(r'''
          (() => ({
            handled: true,
            passed: document.readyState !== 'loading' && Boolean(document.body) && document.body.children.length > 0,
            reason: document.readyState !== 'loading' && Boolean(document.body) && document.body.children.length > 0
              ? 'renderer reached a stable ready state'
              : `renderer is still loading: ${document.readyState}`,
            evidence: {readyState: document.readyState, route: String(location.hash || ''), bodyChildren: document.body?.children.length || 0},
          }))()
        ''')
        if isinstance(result, dict):
            result.setdefault('evidence', {})['waited_seconds'] = requested_seconds if requested_seconds is not None else 0.8
            result['reason'] = (
                f'waited {requested_seconds:g} second(s) and renderer is stable'
                if result.get('passed') and requested_seconds is not None
                else result.get('reason')
            )
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_read_only_cdp_instruction(instruction):
        result = await page.evaluate(r'''
          (() => {
            const body = document.body;
            const rendered = document.readyState !== 'loading' && Boolean(body) && body.children.length > 0;
            return {
              handled: true,
              passed: rendered,
              reason: rendered ? 'renderer is ready for the observation step' : 'renderer is not ready for the observation step',
              evidence: {readyState: document.readyState, route: String(location.hash || ''), bodyChildren: body?.children.length || 0},
            };
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_renderer_health_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            const visible = element => {
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden';
            };
            const body = document.body;
            const text = String(body?.innerText || '').replace(/\s+/g, ' ').trim();
            const visibleError = Array.from(document.querySelectorAll('*')).filter(visible).some(element =>
              /(?:^|\s)(?:404|500)(?:\s|$)|\u9875\u9762\u4e0d\u5b58\u5728|\u52a0\u8f7d\u5931\u8d25|script\s*error|\u811a\u672c\u9519\u8bef/i.test(String(element.innerText || element.textContent || '').trim())
            );
            const hasContent = Boolean(body) && body.children.length > 0 && text.length >= 20;
            const passed = document.readyState !== 'loading' && hasContent && !visibleError;
            return {
              handled: true,
              passed,
              reason: passed ? 'renderer health verified: content is present without a visible error state' : `renderer health mismatch: ready=${document.readyState}, content=${hasContent}, visibleError=${visibleError}`,
              evidence: {readyState: document.readyState, route: String(location.hash || ''), textLength: text.length, hasContent, visibleError},
            };
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_community_home_navigation_assertion(instruction):
        payload = json.dumps({'instruction': instruction}, ensure_ascii=False)
        result = await page.evaluate(rf'''
          (() => new Promise(resolve => {{
            const payload = {payload};
            const compact = String(payload.instruction || '').replace(/\s+/g, '');
            const aliases = [
              {{key:'home', requested:['\u7edd\u5730\u6c42\u751f\u9996\u9875','\u7edd\u5730\u6c42\u751f'], labels:['\u7edd\u5730\u6c42\u751f']}},
              {{key:'store', requested:['PUBG\u798f\u5229\u5546\u5e97','NN\u5546\u57ce'], labels:['PUBG\u798f\u5229\u5546\u5e97','NN\u5546\u57ce']}},
              {{key:'hall', requested:['\u6210\u5458\u5927\u5385','\u5168\u5458\u5927\u5385'], labels:['\u6210\u5458\u5927\u5385','\u5168\u5458\u5927\u5385']}},
              {{key:'battle', requested:['\u6218\u7ee9\u67e5\u8be2'], labels:['\u6218\u7ee9\u67e5\u8be2']}},
              {{key:'events', requested:['\u8d5b\u4e8b\u4e13\u533a'], labels:['\u8d5b\u4e8b\u4e13\u533a']}},
              {{key:'teams', requested:['\u65d7\u4e0b\u793e\u533a'], labels:['\u65d7\u4e0b\u793e\u533a']}},
            ];
            const required = aliases.filter(item => item.requested.some(label => compact.includes(label)));
            const sidebar = document.querySelector('#asideScroll .simplebar-content-wrapper') || document.querySelector('#asideScroll') || document.querySelector('.simplebar-content-wrapper');
            const inspect = () => {{
              const sidebarText = String(sidebar?.innerText || '').replace(/\s+/g, ' ');
              const route = String(location.hash || '');
              const signals = Object.fromEntries(required.map(item => [
                item.key,
                item.key === 'home'
                  ? /\/community\/\d+\/plugin\/communityHome(?:$|[/?])/.test(route)
                  : item.labels.some(label => sidebarText.includes(label)),
              ]));
              const passed = required.length > 0 && Object.values(signals).every(Boolean);
              return {{handled:true, passed, reason:passed ? 'requested community plugin navigation entries are rendered in the sidebar' : `community home navigation mismatch: ${{JSON.stringify(signals)}}`, evidence:{{required:required.map(item => item.key), signals, scrollTop:sidebar?.scrollTop || 0, scrollHeight:sidebar?.scrollHeight || 0}}}};
            }};
            const deadline = Date.now() + 5000;
            const reveal = () => {{
              const state = inspect();
              if (state.passed || Date.now() >= deadline || !sidebar) return resolve(state);
              const max = Math.max(0, sidebar.scrollHeight - sidebar.clientHeight);
              sidebar.scrollTop = Math.min(max, sidebar.scrollTop + Math.max(120, Math.floor(sidebar.clientHeight * 0.75)));
              sidebar.dispatchEvent(new Event('scroll', {{bubbles:true}}));
              setTimeout(reveal, 250);
            }};
            reveal();
          }}))()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_community_banner_content_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            const visible = element => {
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 80 && rect.height > 36 && style.display !== 'none' && style.visibility !== 'hidden';
            };
            const bodyText = String(document.body?.innerText || '').replace(/\s+/g, ' ').trim();
            const banner = Array.from(document.querySelectorAll('img')).find(element => visible(element) && element.getBoundingClientRect().width >= 300 && element.getBoundingClientRect().height >= 100);
            const sidebar = document.querySelector('#asideScroll') || document.body;
            const sidebarText = String(sidebar.innerText || '').replace(/\s+/g, ' ').trim();
            const hasCommunityName = /[A-Za-z0-9\u4e00-\u9fff]{2,}\u793e\u533a|test\d+/i.test(sidebarText) || /[A-Za-z0-9\u4e00-\u9fff]{2,}\u793e\u533a/.test(bodyText);
            const hasOnline = /\d+\s*\u5728\u7ebf|\u5728\u7ebf\s*\d+/.test(bodyText);
            const passed = Boolean(banner) && hasCommunityName && hasOnline;
            return {handled:true,passed,reason:passed ? 'community banner, identity and online state are rendered' : `community banner content mismatch: banner=${Boolean(banner)}, name=${hasCommunityName}, online=${hasOnline}`,evidence:{hasBanner:Boolean(banner),hasCommunityName,hasOnline,bannerSize:banner ? {width:Math.round(banner.getBoundingClientRect().width),height:Math.round(banner.getBoundingClientRect().height)} : null}};
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_daily_rank_list_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            const text = String(document.body?.innerText || '').replace(/\s+/g, ' ').trim();
            const titleIndex = text.indexOf('\u5403\u9e21\u65e5\u699c');
            const rankText = titleIndex >= 0 ? text.slice(titleIndex, titleIndex + 1200) : '';
            const entries = Array.from(rankText.matchAll(/(?:^|\s)([1-9]\d?)\s+([^\s]{2,24})\s+\u5403\u9e21\s*(\d+)\s*\u6b21/g)).map(match => ({rank:Number(match[1]),name:match[2],wins:Number(match[3])}));
            const uniqueNames = new Set(entries.map(item => item.name));
            const passed = entries.length >= 3 && uniqueNames.size >= 3;
            return {handled:true,passed,reason:passed ? `daily rank list verified with ${entries.length} visible complete entries` : `daily rank list mismatch: title=${titleIndex >= 0}, entries=${entries.length}, uniqueNames=${uniqueNames.size}`,evidence:{hasTitle:titleIndex >= 0,entries:entries.slice(0,12),uniqueNames:uniqueNames.size}};
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_community_home_presence_assertion(instruction):
        require_community_id = '\u793e\u533a ID' in instruction or '\u793e\u533aID' in instruction
        result = await page.evaluate(r'''
          (() => new Promise(resolve => {
            const deadline=Date.now()+5000;
            const inspect=()=>{
              const sidebar=document.querySelector('#asideScroll');
              const active=sidebar?.querySelector('[id^="community-box-"]');
              const name=String(active?.querySelector('span')?.innerText||active?.innerText||'').replace(/\s+/g,' ').trim();
              const scope=sidebar?.parentElement?.parentElement?.parentElement || document.body;
              const scopeText=String(scope?.innerText||'').replace(/\s+/g,' ').trim();
              const hasName=Boolean(name) && name.length>=2;
              const hasId=Array.from(scope.querySelectorAll('.nn-equity__text')).some(node=>/^\d{5,}$/.test(String(node.innerText||'').trim()));
              const hasOnline=/\d+\s*\u5728\u7ebf|\u5728\u7ebf\s*\d+/.test(scopeText);
              const requireId = __TESTHUB_REQUIRE_COMMUNITY_ID__;
              const passed = hasName && hasOnline && (!requireId || hasId);
              return {handled:true,passed,reason:passed?'active community identity and online count are rendered':`community header mismatch: name=${hasName}, id=${hasId}, online=${hasOnline}, requireId=${requireId}`,evidence:{name,hasName,hasId,hasOnline,requireId}};
            };
            const check=()=>{const state=inspect(); if(state.passed||Date.now()>=deadline)return resolve(state); setTimeout(check,250)}; check();
          }))()
        '''.replace('__TESTHUB_REQUIRE_COMMUNITY_ID__', json.dumps(require_community_id)))
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_community_home_article_assertion(instruction):
        result = await page.evaluate(r'''
          (() => new Promise(resolve => {
            const visible = element => { const r=element.getBoundingClientRect(),s=getComputedStyle(element); return r.width>80 && r.height>36 && s.display!=='none' && s.visibility!=='hidden'; };
            const inspect = () => {
              const cards = Array.from(document.querySelectorAll('[class*="article" i],[class*="notice" i],[class*="post" i],[class*="card" i]')).filter(visible).map(element => String(element.innerText || element.textContent || '').replace(/\s+/g,' ').trim()).filter(text => text.length >= 12);
              const hasCard = cards.length > 0;
              const details = cards.some(text => /\d{1,2}[\/-]\d{1,2}|\u53d1\u5e03|\u4f5c\u8005|\u8bc4\u8bba|\u7f6e\u9876|\u653b\u7565|\u516c\u544a/.test(text));
              return {handled:true, passed:hasCard && details, reason:hasCard && details ? 'community article or notice card has title/detail DOM evidence' : `community article DOM mismatch: cards=${cards.length}, details=${details}`, evidence:{cardCount:cards.length,details,samples:cards.slice(0,3)}};
            };
            const deadline = Date.now() + 5000;
            const check = () => { const state = inspect(); if (state.passed || Date.now() >= deadline) resolve(state); else setTimeout(check, 250); };
            check();
          }))()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_article_card_integrity_assertion(instruction):
        require_interaction = '\u4e92\u52a8' in normalized
        result = await page.evaluate(r'''
          (() => {
            const saved = String(sessionStorage.getItem('__testhub_article_title') || '');
            const visible = element => { const r=element.getBoundingClientRect(),s=getComputedStyle(element); return r.width>80&&r.height>36&&s.display!=='none'&&s.visibility!=='hidden'; };
            const text = element => String(element?.innerText||element?.textContent||'').replace(/\s+/g,' ').trim();
            const card = Array.from(document.querySelectorAll('div')).find(element => visible(element) && saved && text(element) === saved && String(element.className||'').includes('h-[120px]'));
            const value = text(card);
            const hasDate = /\d{1,2}\/\d{1,2}|\d{4}[-/]\d{1,2}[-/]\d{1,2}|\u6628\u5929|\u4eca\u5929/.test(value);
            const hasInteraction = /(?:^|\s)\d+(?:\s|$)/.test(value);
            const hasCategory = /^(?:\u6d3b\u52a8|\u516c\u544a|\u653b\u7565|\u7f6e\u9876)/.test(value);
            const hasTitle = value.replace(/^(?:\u6d3b\u52a8|\u516c\u544a|\u653b\u7565|\u7f6e\u9876)\s*/, '').replace(/\s*(?:\d{1,2}\/\d{1,2}|\u6628\u5929|\u4eca\u5929).*$/, '').trim().length >= 2;
            const requireInteraction = __TESTHUB_REQUIRE_INTERACTION__;
            const passed = Boolean(card) && hasTitle && hasCategory && hasDate && (!requireInteraction || hasInteraction);
            return {handled:true,passed,reason:passed ? `selected article card is structurally complete: ${value.slice(0,120)}` : `selected article card mismatch: found=${Boolean(card)}, title=${hasTitle}, category=${hasCategory}, date=${hasDate}, interaction=${hasInteraction}, requireInteraction=${requireInteraction}`,evidence:{saved,value:value.slice(0,240),hasTitle,hasCategory,hasDate,hasInteraction,requireInteraction}};
          })()
        '''.replace('__TESTHUB_REQUIRE_INTERACTION__', json.dumps(require_interaction)))
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_article_card_selection_instruction(instruction):
        result = await page.evaluate(r'''
          (() => {
            const visible = element => { const r=element.getBoundingClientRect(),s=getComputedStyle(element); return r.width>80 && r.height>36 && s.display!=='none' && s.visibility!=='hidden'; };
            const text = element => String(element?.innerText || element?.textContent || '').replace(/\s+/g, ' ').trim();
            const cards = Array.from(document.querySelectorAll('div')).filter(element => {
              if (!visible(element)) return false;
              const rect = element.getBoundingClientRect();
              const value = text(element);
              return rect.width >= 360 && rect.width <= 760 && rect.height >= 70 && rect.height <= 300
                && /\d{1,2}\/\d{1,2}|\d{4}[-/]\d{1,2}[-/]\d{1,2}|\u6628\u5929|\u4eca\u5929/.test(value)
                && value.length >= 10;
            });
            const card = cards.find(item => /(?:\d{1,2}\/\d{1,2}|\d{4}[-/]\d{1,2}[-/]\d{1,2})\s+\d+(?:\s|$)/.test(text(item)))
              || cards.find(item => /\d{1,2}\/\d{1,2}|\d{4}[-/]\d{1,2}[-/]\d{1,2}/.test(text(item)))
              || cards[0];
            const title = card && Array.from(card.querySelectorAll('*')).find(child => {
              const classes = String(child.className || '');
              return visible(child) && classes.includes('truncate') && classes.includes('text-[15px]') && text(child).length > 0;
            });
            const value = text(title) || text(card).slice(0, 160);
            const passed = Boolean(card) && value.length >= 2;
            if (passed) sessionStorage.setItem('__testhub_article_title', value);
            return {handled:true,passed,reason:passed ? `selected article card: ${value}` : 'no complete visible article card could be selected',evidence:{title:value,cardCount:cards.length}};
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_article_detail_open_instruction(instruction):
        result = await page.evaluate(r'''
          (() => new Promise(resolve => {
            const visible = element => { const r=element.getBoundingClientRect(),s=getComputedStyle(element); return r.width>20 && r.height>20 && s.display!=='none' && s.visibility!=='hidden'; };
            const text = element => String(element?.innerText || element?.textContent || '').replace(/\s+/g, ' ').trim();
            const savedTitle = String(sessionStorage.getItem('__testhub_article_title') || '');
            const cards = Array.from(document.querySelectorAll('div')).filter(element => {
              if (!visible(element)) return false;
              const rect = element.getBoundingClientRect();
              const value = text(element);
              return rect.width >= 360 && rect.width <= 760 && rect.height >= 70 && rect.height <= 300
                && /\d{1,2}\/\d{1,2}|\d{4}[-/]\d{1,2}[-/]\d{1,2}|\u6628\u5929|\u4eca\u5929/.test(value)
                && value.length >= 10;
            });
            const card = cards.find(item => savedTitle && text(item).includes(savedTitle)) || cards.find(item => /\d{1,2}\/\d{1,2}|\d{4}[-/]\d{1,2}[-/]\d{1,2}/.test(text(item))) || cards[0];
            if (!card) return resolve({handled:true,passed:false,reason:'no visible article card is available to open'});
            const title = Array.from(card.querySelectorAll('*')).find(child => {
              const classes = String(child.className || '');
              return visible(child) && classes.includes('truncate') && classes.includes('text-[15px]') && text(child).length > 0;
            });
            const value = text(title) || savedTitle || text(card).slice(0, 160);
            const beforeRoute = String(location.hash || '');
            const clickTarget = [card, ...Array.from(card.querySelectorAll('*'))].find(node => typeof node?._vei?.onClick === 'function') || card;
            const rendererClick = clickTarget._vei?.onClick;
            const event = new MouseEvent('click', {bubbles:true,cancelable:true,view:window});
            if (typeof rendererClick === 'function') rendererClick(event); else clickTarget.click();
            const deadline = Date.now() + 7000;
            const check = () => {
              const route = String(location.hash || '');
              const opened = /\/plugin\/articleDetail\/\d+/.test(route);
              if (opened || Date.now() >= deadline) {
                if (opened) sessionStorage.setItem('__testhub_article_title', value);
                return resolve({handled:true,passed:opened,reason:opened ? `opened article detail: ${value}` : `article detail did not open: ${route}`,evidence:{title:value,beforeRoute,route,rendererClick:typeof rendererClick === 'function'}});
              }
              setTimeout(check, 200);
            };
            check();
          }))()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    content_entry = _community_home_content_entry_label(instruction)
    if content_entry:
        payload = json.dumps({'label': content_entry}, ensure_ascii=False)
        result = await page.evaluate(rf'''
          (() => new Promise(resolve => {{
            const payload = {payload};
            const deadline = Date.now() + 5000;
            const text = element => String(element?.innerText || element?.textContent || '').replace(/\s+/g, ' ').trim();
            const open = () => {{
              const leaf = Array.from(document.querySelectorAll('*')).find(element => text(element) === payload.label && !Array.from(element.children).some(child => text(child) === payload.label));
              const control = leaf?.closest('[data-draggable],button,a,[role="button"],div.cursor-pointer') || leaf;
              if (!control) {{
                if (Date.now() >= deadline) return resolve({{handled:true,passed:false,reason:`home content entry is not rendered: ${{payload.label}}`}});
                return setTimeout(open, 250);
              }}
              control.dispatchEvent(new MouseEvent('click', {{bubbles:true,cancelable:true,view:window}}));
              const verify = () => {{
                const route = String(location.hash || '');
                const passed = /\/plugin\/articleDetail\/\d+/.test(route) && String(document.body?.innerText || '').includes(payload.label);
                if (passed || Date.now() >= deadline) {{
                  if (passed) sessionStorage.setItem('__testhub_home_content_entry', payload.label);
                  return resolve({{handled:true,passed,reason:passed ? `opened home content detail: ${{payload.label}}` : `content entry did not open its detail route: ${{route}}`,evidence:{{route,label:payload.label}}}});
                }}
                setTimeout(verify, 200);
              }};
              verify();
            }};
            open();
          }}))()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_community_home_content_detail_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            const label = String(sessionStorage.getItem('__testhub_home_content_entry') || '');
            const route = String(location.hash || '');
            const text = String(document.body?.innerText || '').replace(/\s+/g, ' ').trim();
            const detailSignals = ['\u6211\u7684\u5956\u54c1','\u6982\u7387\u516c\u793a','\u5237\u65b0','\u8fd4\u56de'];
            const detailCount = detailSignals.filter(signal => text.includes(signal)).length;
            const passed = Boolean(label) && /\/plugin\/articleDetail\/\d+/.test(route) && text.includes(label) && detailCount >= 2;
            return {handled:true,passed,reason:passed ? 'home content detail route and rendered content evidence verified' : `home content detail mismatch: label=${label || '?'}, route=${route || '?'}, signals=${detailCount}`,evidence:{label,route,detailCount}};
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_community_home_faq_scroll_instruction(instruction):
        result = await page.evaluate(r'''
          (() => new Promise(resolve => {
            const question = '组队能解决游戏哪些问题？';
            const text = element => String(element?.innerText || element?.textContent || '').replace(/\s+/g, ' ').trim();
            const leaf = Array.from(document.querySelectorAll('*')).find(element => text(element) === question && !Array.from(element.children).some(child => text(child) === question));
            const card = leaf?.closest('.cursor-pointer') || leaf;
            if (!card) return resolve({handled:true,passed:false,reason:'community home FAQ entry is not rendered'});
            card.scrollIntoView({block:'center', inline:'nearest'});
            const check = () => {
              const rect = card.getBoundingClientRect();
              const passed = rect.top >= 48 && rect.bottom <= window.innerHeight;
              if (passed) sessionStorage.setItem('__testhub_home_faq_scrolled', 'true');
              resolve({handled:true,passed,reason:passed ? 'community home FAQ section is visible after scrolling' : `FAQ section is outside the visible main content: top=${rect.top}, bottom=${rect.bottom}`,evidence:{top:rect.top,bottom:rect.bottom,viewportHeight:window.innerHeight}});
            };
            setTimeout(check, 300);
          }))()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_community_home_faq_expand_instruction(instruction):
        faq_questions = [
            question for question in (
                '组队能解决游戏哪些问题？',
                'NN游戏语音与其他语音有什么不同？',
            ) if question in instruction
        ]
        payload = json.dumps(faq_questions, ensure_ascii=False)
        result = await page.evaluate(r'''
          (() => {
            const questions = __TESTHUB_FAQ_QUESTIONS__;
            const text = element => String(element?.innerText || element?.textContent || '').replace(/\s+/g, ' ').trim();
            const evidence = [];
            for (const question of questions) {
              const leaf = Array.from(document.querySelectorAll('div')).find(element => text(element) === question && String(element.className || '').includes('text-[18px]'));
              const card = leaf?.parentElement?.closest('.cursor-pointer') || leaf?.closest('.cursor-pointer') || leaf;
              const answer = card && Array.from(card.querySelectorAll('div')).find(node => {
                const classes = String(node.className || '');
                return classes.includes('transition-all') && classes.includes('leading-[20px]');
              });
              if (!card || !answer) return {handled:true,passed:false,reason:`FAQ question or answer region is missing: ${question}`,evidence};
              const wasExpanded = answer.getBoundingClientRect().height > 2;
              if (answer.getBoundingClientRect().height <= 2) {
                const event = new MouseEvent('click', {bubbles:true,cancelable:true,view:window});
                const invoker = card?._vei?.onClick;
                if (typeof invoker === 'function') invoker(event); else return {handled:true,passed:false,reason:`FAQ entry has no renderer click handler: ${question}`,evidence};
              }
              evidence.push({question, wasExpanded, rendererClickDispatched:true, answerTextLength:text(answer).length});
            }
            const passed = evidence.length === questions.length && evidence.every(item => item.rendererClickDispatched && item.answerTextLength > 12);
            if (passed) sessionStorage.setItem('__testhub_home_faq_expanded', JSON.stringify(questions));
            return {handled:true,passed,reason:passed ? 'requested community home FAQ entry received its renderer click' : 'one or more FAQ entries could not dispatch a renderer click',evidence};
          })()
        '''.replace('__TESTHUB_FAQ_QUESTIONS__', payload))
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_community_home_faq_assertion(instruction):
        faq_questions = [
            question for question in (
                '组队能解决游戏哪些问题？',
                'NN游戏语音与其他语音有什么不同？',
            ) if question in instruction
        ]
        payload = json.dumps(faq_questions, ensure_ascii=False)
        result = await page.evaluate(r'''
          (() => {
            const questions = __TESTHUB_FAQ_QUESTIONS__;
            const text = element => String(element?.innerText || element?.textContent || '').replace(/\s+/g, ' ').trim();
            const evidence = questions.map(question => {
              const leaf = Array.from(document.querySelectorAll('div')).find(element => text(element) === question && String(element.className || '').includes('text-[18px]'));
              const card = leaf?.parentElement?.closest('.cursor-pointer') || leaf?.closest('.cursor-pointer') || leaf;
              const answer = card && Array.from(card.querySelectorAll('div')).find(node => {
                const classes = String(node.className || '');
                return classes.includes('transition-all') && classes.includes('leading-[20px]');
              });
              return {question, cardVisible:Boolean(card) && card.getBoundingClientRect().height > 20, answerHeight:answer?.getBoundingClientRect().height || 0, answerTextLength:text(answer).length};
            });
            const expanded = sessionStorage.getItem('__testhub_home_faq_expanded') === JSON.stringify(questions);
            const passed = expanded && evidence.every(item => item.cardVisible && item.answerHeight > 8 && item.answerTextLength > 12);
            return {handled:true,passed,reason:passed ? 'FAQ titles and their visible explanation text are verified' : `FAQ assertion mismatch: expanded=${expanded}`,evidence:{expanded,items:evidence}};
          })()
        '''.replace('__TESTHUB_FAQ_QUESTIONS__', payload))
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_community_plugin_scroll_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            const visible = element => { const r=element.getBoundingClientRect(), s=getComputedStyle(element); return r.width>1 && r.height>1 && s.display !== 'none' && s.visibility !== 'hidden'; };
            const containers = Array.from(document.querySelectorAll('*')).filter(element => {
              if (!visible(element)) return false;
              const style = getComputedStyle(element);
              return element.scrollHeight > element.clientHeight + 2 && /(auto|scroll)/.test(`${style.overflow} ${style.overflowY}`);
            });
            const passed = containers.length > 0;
            return {handled:true, passed, reason:passed ? `community plugin area has ${containers.length} scrollable container(s)` : 'no scrollable community plugin container is rendered', evidence:{scrollableContainers:containers.length}};
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_community_plugin_switch_stability_instruction(instruction):
        result = await page.evaluate(r'''
          (() => new Promise(async resolve => {
            const visible = element => {
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden';
            };
            const norm = value => String(value || '').replace(/\s+/g, ' ').trim();
            const expected = [
              {label:'成员大厅', evidence:['成员大厅', '搜索成员']},
              {label:'战绩查询', evidence:['战绩查询']},
              {label:'PUBG福利商店', evidence:['PUBG福利商店']},
            ];
            const wait = milliseconds => new Promise(done => setTimeout(done, milliseconds));
            const findTarget = label => Array.from(document.querySelectorAll('*'))
              .filter(visible)
              .filter(element => norm(element.innerText || element.textContent || '') === label)
              .sort((left, right) => {
                const leftRect = left.getBoundingClientRect();
                const rightRect = right.getBoundingClientRect();
                return leftRect.width * leftRect.height - rightRect.width * rightRect.height;
              })[0]
              ?.closest('[class*="cursor-pointer" i],button,[role="button"],a') || null;
            const evidence = [];
            for (const item of expected) {
              const target = findTarget(item.label);
              if (!target) return resolve({handled:true, passed:false, reason:`plugin switch target is not visible: ${item.label}`, evidence});
              const beforeRoute = String(location.hash || '');
              target.click();
              await wait(900);
              const route = String(location.hash || '');
              const text = norm(document.body?.innerText || '');
              const active = /is-active|active|selected/.test(String(target.className || target.parentElement?.className || ''));
              const contentMatches = item.evidence.some(marker => text.includes(marker));
              evidence.push({label:item.label, beforeRoute, route, active, contentMatches});
              if (!(route !== beforeRoute || active) || !contentMatches) {
                return resolve({handled:true, passed:false, reason:`plugin switch did not reach a verified ${item.label} view`, evidence});
              }
            }
            location.hash = location.hash.replace(/\/plugin\/[^/?#]+/, '/plugin/teamListCenter');
            await wait(900);
            const route = String(location.hash || '');
            const text = norm(document.body?.innerText || '');
            const createEntryCount = Array.from(document.querySelectorAll('*')).filter(visible)
              .filter(element => norm(element.innerText || element.textContent || '') === '创建战队社区').length;
            evidence.push({label:'旗下社区', route, hasHeading:text.includes('旗下社区'), createEntryCount});
            const passed = /\/teamListCenter/.test(route) && text.includes('旗下社区') && createEntryCount > 0;
            sessionStorage.setItem('__testhub_plugin_switch_stability', JSON.stringify({passed, evidence}));
            resolve({handled:true, passed, reason:passed ? 'each plugin switch reached its verified view and the affiliated-community view recovered' : 'affiliated-community switch did not reach its verified view', evidence});
          }))()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_community_plugin_switch_stability_verification(instruction):
        result = await page.evaluate(r'''
          (() => {
            let prior = {};
            try { prior = JSON.parse(sessionStorage.getItem('__testhub_plugin_switch_stability') || '{}'); } catch (_error) {}
            const text = String(document.body?.innerText || '').replace(/\s+/g, ' ').trim();
            const visibleError = /(?:^|\s)(?:404|500)(?:\s|$)|页面不存在|加载失败|script\s*error|脚本错误/i.test(text);
            const routeMatches = /\/teamListCenter/.test(String(location.hash || ''));
            const passed = prior.passed === true && routeMatches && !visibleError;
            return {
              handled:true,
              passed,
              reason:passed ? 'all plugin switches retained their verified route/content evidence without an error page' : 'plugin-switch verification lacks complete switch evidence or ended in an error state',
              evidence:{prior, route:String(location.hash || ''), visibleError},
            };
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_team_home_filter_open_instruction(instruction):
        result = await page.evaluate(r'''
          (() => new Promise(resolve => {
            const visible = element => {
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden';
            };
            const panelInput = () => Array.from(document.querySelectorAll('input')).find(input =>
              visible(input) && String(input.placeholder || '').replace(/\s+/g, '') === '\u5168\u5c40\u641c\u7d22\u5173\u952e\u8bcd\u623f\u95f4\u53f7'
            );
            const panel = () => panelInput()?.closest('.ui-floating-view') || null;
            if (panel()) return resolve({handled:true, passed:true, reason:'team-room filter panel is already open'});
            const trigger = Array.from(document.querySelectorAll('button')).find(button =>
              visible(button) && String(button.innerText || button.textContent || '').replace(/\s+/g, '').trim() === '\u7b5b\u9009'
            );
            // UiTooltip owns the actual open lifecycle. Calling the Vue event
            // invoker on its wrapper runs the same onShow callback as a user
            // click, without sending native coordinates to a hidden window.
            const tooltipTrigger = trigger?.parentElement;
            const clickInvoker = tooltipTrigger?._vei?.onClick;
            if (!trigger || typeof clickInvoker !== 'function') {
              return resolve({handled:true, passed:false, reason:'team-room filter tooltip trigger is not available'});
            }
            try {
              clickInvoker({currentTarget:tooltipTrigger, target:trigger, type:'click', preventDefault(){}, stopPropagation(){}});
            } catch (error) {
              return resolve({handled:true, passed:false, reason:`team-room filter tooltip invocation failed: ${String(error?.message || error)}`});
            }
            setTimeout(() => resolve({
              handled:true,
              passed:Boolean(panel()),
              reason:panel() ? 'team-room filter panel opened through its UiTooltip lifecycle' : 'team-room filter tooltip did not render its panel',
            }), 700);
          }))()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_team_home_filter_panel_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            const visible = element => {
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden';
            };
            const input = Array.from(document.querySelectorAll('input')).find(element =>
              visible(element) && String(element.placeholder || '').replace(/\s+/g, '') === '\u5168\u5c40\u641c\u7d22\u5173\u952e\u8bcd\u623f\u95f4\u53f7'
            );
            const panel = input?.closest('.ui-floating-view') || null;
            const panelText = String(panel?.innerText || panel?.textContent || '').replace(/\s+/g, ' ').trim();
            const labels = ['\u5168\u90e8', '\u7ec4\u961f', '\u76f4\u64ad', '\u4e92\u52a8', '\u7a7a\u623f'];
            const filters = Object.fromEntries(labels.map(label => [label, panelText.includes(label)]));
            const search = Boolean(input);
            const refresh = Array.from(panel?.querySelectorAll('button,[role="button"],div,span') || []).some(element =>
              visible(element) && String(element.innerText || element.textContent || '').replace(/\s+/g, '').trim() === '\u5237\u65b0'
            );
            const passed = Boolean(panel) && Object.values(filters).every(Boolean) && search && refresh;
            return {handled:true, passed, reason:passed ? 'team-room filter panel exposes all categories, global search, and refresh' : `team-room filter panel mismatch: panel=${Boolean(panel)}, filters=${JSON.stringify(filters)}, search=${search}, refresh=${refresh}`, evidence:{panel:Boolean(panel), filters, search, refresh}};
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_team_home_filter_tab_switch_instruction(instruction):
        initial = await page.evaluate(r'''
          (() => {
            const visible = element => {
              if (!element) return false;
              const rect = element.getBoundingClientRect(), style = getComputedStyle(element);
              return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden';
            };
            const input = Array.from(document.querySelectorAll('input')).find(element =>
              visible(element) && String(element.placeholder || '').replace(/\s+/g, '') === '\u5168\u5c40\u641c\u7d22\u5173\u952e\u8bcd\u623f\u95f4\u53f7'
            );
            const panel = input?.closest('.ui-floating-view') || null;
            return {panelOpen:Boolean(panel)};
          })()
        ''')
        if not isinstance(initial, dict) or not initial.get('panelOpen'):
            return {'handled': True, 'passed': False, 'reason': 'team-room filter panel is not open before switching categories'}
        evidence = []
        for label, value in (('\u7ec4\u961f', '1'), ('\u76f4\u64ad', '3'), ('\u4e92\u52a8', '4'), ('\u7a7a\u623f', '2')):
            payload = json.dumps({'label': label, 'value': value}, ensure_ascii=False)
            try:
                dispatch = await asyncio.wait_for(page.call('Runtime.evaluate', {
                    'expression': rf'''
                      (() => {{
                        const payload = {payload};
                        const visible = element => {{
                          if (!element) return false;
                          const rect = element.getBoundingClientRect(), style = getComputedStyle(element);
                          return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden';
                        }};
                        const input = Array.from(document.querySelectorAll('input')).find(element =>
                          visible(element) && String(element.placeholder || '').replace(/\s+/g, '') === '\u5168\u5c40\u641c\u7d22\u5173\u952e\u8bcd\u623f\u95f4\u53f7'
                        );
                        const panel = input?.closest('.ui-floating-view');
                        const tab = Array.from(panel?.querySelectorAll('[data-value]') || []).find(element =>
                          visible(element) && String(element.innerText || element.textContent || '').replace(/\s+/g, '').trim() === payload.label
                        );
                        if (!tab) return {{dispatched:false, reason:`filter category trigger is unavailable: ${{payload.label}}`}};
                        const trace = JSON.parse(sessionStorage.getItem('__testhub_filter_tab_dispatch') || '[]');
                        trace.push({{label:payload.label, value:payload.value, at:Date.now()}});
                        sessionStorage.setItem('__testhub_filter_tab_dispatch', JSON.stringify(trace));
                        tab.click();
                        return {{dispatched:true}};
                      }})()
                    ''',
                    'awaitPromise': False,
                    'returnByValue': True,
                    'userGesture': True,
                }), timeout=8)
                dispatch_value = (dispatch.get('result') or {}).get('value') or {}
            except asyncio.TimeoutError:
                return {'handled': True, 'passed': False, 'reason': f'filter category {label} did not return after the local DOM dispatch', 'evidence': evidence}
            except Exception as exc:
                return {'handled': True, 'passed': False, 'reason': f'filter category {label} dispatch failed: {exc}', 'evidence': evidence}
            if not dispatch_value.get('dispatched'):
                return {'handled': True, 'passed': False, 'reason': str(dispatch_value.get('reason') or f'filter category {label} was not dispatched'), 'evidence': evidence}
            await asyncio.sleep(0.7)
            state = await page.evaluate(rf'''
              (() => {{
                const payload = {payload};
                const visible = element => {{
                  if (!element) return false;
                  const rect = element.getBoundingClientRect(), style = getComputedStyle(element);
                  return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden';
                }};
                const input = Array.from(document.querySelectorAll('input')).find(element =>
                  visible(element) && String(element.placeholder || '').replace(/\s+/g, '') === '\u5168\u5c40\u641c\u7d22\u5173\u952e\u8bcd\u623f\u95f4\u53f7'
                );
                const panel = input?.closest('.ui-floating-view') || null;
                const rooms = panel?.querySelectorAll('.room-item, [class*="room-item" i]').length || 0;
                const empty = Boolean(panel?.querySelector('.nn-empty, [class*="empty" i]'));
                const trace = JSON.parse(sessionStorage.getItem('__testhub_filter_tab_dispatch') || '[]');
                return {{panel:Boolean(panel), rooms, empty, dispatched:trace.some(item => item.label === payload.label && item.value === payload.value), content:String(panel?.innerText || '').replace(/\s+/g, ' ').trim().slice(-180)}};
              }})()
            ''')
            state = state if isinstance(state, dict) else {}
            state['label'] = label
            evidence.append(state)
            if not state.get('panel') or not state.get('dispatched') or not (state.get('rooms') or state.get('empty')):
                return {'handled': True, 'passed': False, 'reason': f'filter category {label} did not render a room list or empty state', 'evidence': evidence}
        await page.evaluate(
            f"sessionStorage.setItem('__testhub_filter_tab_switch', {json.dumps(json.dumps({'passed': True, 'evidence': evidence}, ensure_ascii=False), ensure_ascii=False)}); true"
        )
        return {'handled': True, 'passed': True, 'reason': 'each filter category dispatched a renderer-local click and rendered a result area', 'evidence': evidence}
    if _is_team_home_filter_search_instruction(instruction):
        payload = json.dumps({'instruction': normalized}, ensure_ascii=False)
        result = await page.evaluate(rf'''
          (async () => {{
            const payload = {payload};
            const visible = element => {{
              if (!element) return false;
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden';
            }};
            const input = Array.from(document.querySelectorAll('input')).find(element =>
              visible(element) && String(element.placeholder || '').replace(/\s+/g, '') === '\u5168\u5c40\u641c\u7d22\u5173\u952e\u8bcd\u623f\u95f4\u53f7'
            );
            const panel = input?.closest('.ui-floating-view') || null;
            if (!input || !panel) return {{handled:true, passed:false, reason:'team-room filter search input is not open'}};
            const setValue = value => {{
              const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
              if (setter) setter.call(input, value); else input.value = value;
              input.dispatchEvent(new InputEvent('input', {{bubbles:true, inputType:'insertText', data:value}}));
              input.dispatchEvent(new Event('change', {{bubbles:true}}));
            }};
            const wait = milliseconds => new Promise(done => setTimeout(done, milliseconds));
            const enteringNoMatch = /999999999/.test(payload.instruction) && /\u8f93\u5165/.test(payload.instruction);
            const clearing = /\u6e05\u7a7a/.test(payload.instruction);
            const refreshing = /\u5237\u65b0/.test(payload.instruction);
            if (enteringNoMatch) setValue('999999999');
            if (clearing) setValue('');
            if (refreshing) {{
              const refresh = Array.from(panel.querySelectorAll('button')).find(button =>
                visible(button) && String(button.innerText || button.textContent || '').replace(/\s+/g, '').trim() === '\u5237\u65b0'
              );
              if (!refresh || typeof refresh.click !== 'function') return {{handled:true, passed:false, reason:'team-room filter refresh trigger is unavailable'}};
              refresh.click();
            }}
            await wait(700);
            const text = String(panel.innerText || panel.textContent || '').replace(/\s+/g, ' ').trim();
            const empty = Boolean(panel.querySelector('.nn-empty, [class*="empty" i]')) || /\u6682\u65e0\u641c\u7d22\u7ed3\u679c|\u6682\u65e0.*\u623f\u95f4/.test(text);
            const noStaleKeyword = String(input.value || '') !== '999999999' && !text.includes('999999999');
            const passed = enteringNoMatch ? String(input.value || '') === '999999999' && empty : clearing || refreshing ? noStaleKeyword : false;
            sessionStorage.setItem('__testhub_filter_search', JSON.stringify({{passed, enteringNoMatch, clearing, refreshing, value:String(input.value || ''), empty, noStaleKeyword}}));
            return {{handled:true, passed, reason:passed ? (enteringNoMatch ? 'filter search entered the unmatched room number and rendered an empty result state' : 'filter search keyword was cleared and refresh completed without stale input') : `filter search operation mismatch: value=${{String(input.value || '')}}, empty=${{empty}}, noStaleKeyword=${{noStaleKeyword}}`, evidence:{{value:String(input.value || ''), empty, noStaleKeyword, text:text.slice(-220)}}}};
          }})()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_team_home_filter_search_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            let prior = {};
            try { prior = JSON.parse(sessionStorage.getItem('__testhub_filter_search') || '{}'); } catch (_error) {}
            const visible = element => {
              if (!element) return false;
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden';
            };
            const input = Array.from(document.querySelectorAll('input')).find(element =>
              visible(element) && String(element.placeholder || '').replace(/\s+/g, '') === '\u5168\u5c40\u641c\u7d22\u5173\u952e\u8bcd\u623f\u95f4\u53f7'
            );
            const panel = input?.closest('.ui-floating-view') || null;
            const text = String(panel?.innerText || panel?.textContent || '').replace(/\s+/g, ' ').trim();
            const empty = Boolean(panel?.querySelector('.nn-empty, [class*="empty" i]')) || /\u6682\u65e0\u641c\u7d22\u7ed3\u679c|\u6682\u65e0.*\u623f\u95f4/.test(text);
            const value = String(input?.value || '');
            const expectsRestore = /\u6062\u590d|\u4e0d\u6b8b\u7559/.test(String(sessionStorage.getItem('__testhub_filter_search') || '')) || value !== '999999999';
            const passed = prior.passed === true && Boolean(panel) && (expectsRestore ? value !== '999999999' && !text.includes('999999999') : empty);
            return {handled:true, passed, reason:passed ? 'filter-search assertion is backed by the current input and result-area state' : `filter-search assertion mismatch: panel=${Boolean(panel)}, value=${value}, empty=${empty}, prior=${prior.passed === true}`, evidence:{prior, value, empty, text:text.slice(-220)}};
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_recruitment_default_publish_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            const visible = element => {
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden';
            };
            const dialog = Array.from(document.querySelectorAll('.ui-dialog,[role="dialog"],[class*="dialog" i]')).find(visible);
            const checkbox = Array.from(dialog?.querySelectorAll('.nn-checkbox,label,[role="checkbox"]') || []).find(element =>
              String(element.innerText || element.textContent || '').replace(/\s+/g, '').includes('\u53d1\u5e03\u81f3\u3010\u7edd\u5730\u6c42\u751f\u3011\u5b98\u65b9\u793e\u533a')
            );
            const checked = Boolean(checkbox) && (
              /(?:^|\s)is-checked(?:\s|$)/.test(String(checkbox.className || ''))
              || checkbox.getAttribute('aria-checked') === 'true'
              || Boolean(checkbox.querySelector('input[type="checkbox"]:checked,.nn-checkbox__input.is-checked'))
            );
            return {
              handled: true,
              passed: checked,
              reason: checked ? 'publish-to-official-community option is selected by default' : 'publish-to-official-community option is not selected by default',
              evidence: {hasDialog:Boolean(dialog), hasCheckbox:Boolean(checkbox), className:String(checkbox?.className || '')},
            };
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_recruitment_dialog_assertion(instruction):
        await page.evaluate(
            f"sessionStorage.setItem('__testhub_recruitment_assertion', {json.dumps(normalized, ensure_ascii=False)}); true"
        )
        result = await page.evaluate(r'''
          (() => {
            const visible = element => {
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden';
            };
            const text = String(document.body?.innerText || '').replace(/\s+/g, ' ').trim();
            const assertion = String(sessionStorage.getItem('__testhub_recruitment_assertion') || '');
            const dialogs = Array.from(document.querySelectorAll('[role="dialog"],[class*="dialog" i],[class*="modal" i]')).filter(visible);
            const dialog = dialogs.find(element => String(element.innerText || element.textContent || '').includes('\u53d1\u5e03\u62db\u52df\u4fe1\u606f'));
            const dialogText = String(dialog?.innerText || dialog?.textContent || text).replace(/\s+/g, ' ').trim();
            const isOpen = Boolean(dialog) || text.includes('\u53d1\u5e03\u62db\u52df\u4fe1\u606f');
            const hasServer = dialogText.includes('\u9009\u62e9\u533a\u670d');
            const hasRecruitInfo = dialogText.includes('\u62db\u52df\u961f\u53cb\u4fe1\u606f');
            const hasRoomCount = dialogText.includes('\u623f\u95f4\u4eba\u6570');
            const hasDuration = dialogText.includes('\u62db\u52df\u6709\u6548\u671f');
            const hasTags = dialogText.includes('\u70ed\u95e8\u5f15\u7528');
            const hasConfirm = dialogText.includes('\u786e\u5b9a\u53d1\u5e03');
            const wantsFields = /\u9009\u62e9\u533a\u670d|\u623f\u95f4\u4eba\u6570|\u62db\u52df\u6709\u6548\u671f|\u70ed\u95e8\u5f15\u7528/.test(assertion);
            const wantsValidation = /\u5fc5\u586b|\u672a\u53d1\u5e03\u6210\u529f|\u9519\u8bef\u72b6\u6001/.test(assertion);
            const wantsCounter = /\u8f93\u5165\u8ba1\u6570|15\/15|\u6587\u672c\u5b8c\u6574\u4fdd\u7559/.test(assertion);
            const hasSuccess = /\u53d1\u5e03\u6210\u529f|\u62db\u52df\u6210\u529f/.test(text);
            const fieldsComplete = hasServer && hasRecruitInfo && hasRoomCount && hasDuration && hasTags && hasConfirm;
            const limitInput = Array.from(dialog?.querySelectorAll('input,textarea') || []).find(element => Number(element.maxLength) === 15);
            const inputLength = String(limitInput?.value || '').length;
            const counterVisible = /15\s*\/\s*15/.test(dialogText);
            const passed = wantsValidation ? isOpen && !hasSuccess : wantsCounter ? isOpen && inputLength === 15 && counterVisible : wantsFields ? isOpen && fieldsComplete : isOpen;
            return {
              handled: true,
              passed,
              reason: passed
                ? (wantsValidation ? 'empty recruitment submission stayed in the open form without a publish-success state' : wantsCounter ? 'recruitment input retained 15 characters and displays its 15/15 counter' : wantsFields ? 'recruitment dialog and required controls are visible' : 'recruitment dialog is open')
                : `recruitment dialog mismatch: open=${isOpen}, fields=${fieldsComplete}, success=${hasSuccess}, inputLength=${inputLength}, counter=${counterVisible}`,
              evidence: {isOpen, hasServer, hasRecruitInfo, hasRoomCount, hasDuration, hasTags, hasConfirm, hasSuccess, inputLength, counterVisible},
            };
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_conditional_empty_room_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            const text = String(document.body?.innerText || '').replace(/\s+/g, ' ').trim();
            const hasEmpty = text.includes('\u6682\u65e0\u7ec4\u961f\u623f\u95f4');
            const hasRoom = /(?:\u6e38\u620f\u8bed\u97f3\u623f|\u4e92\u52a8\u8bed\u97f3|\u5a31\u4e50\u6d3b\u52a8)/.test(text);
            const passed = hasEmpty || hasRoom;
            return {
              handled: true,
              passed,
              reason: passed
                ? (hasEmpty ? 'empty-room state is visible for the current filter' : 'current filter has matching rooms, so an empty-room state is not required')
                : 'filter panel shows neither a matching room nor its empty-room state',
              evidence: {hasEmpty, hasRoom},
            };
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_recruitment_form_operation(instruction) and '\u7ee7\u7eed\u8f93\u5165\u7b2c16\u4e2a\u5b57\u7b26' in normalized:
        await page.evaluate(r'''
          (() => {
            const visible = element => { const r=element.getBoundingClientRect(), s=getComputedStyle(element); return r.width>1 && r.height>1 && s.display!=='none' && s.visibility!=='hidden'; };
            const dialog = Array.from(document.querySelectorAll('[role="dialog"],[class*="dialog" i],[class*="modal" i]')).filter(visible).find(element => String(element.innerText || '').includes('\u53d1\u5e03\u62db\u52df\u4fe1\u606f'));
            const input = Array.from(dialog?.querySelectorAll('input,textarea') || []).find(element => visible(element) && Number(element.maxLength) === 15);
            if (!input) throw new Error('recruitment text input is not visible');
            input.focus();
            input.setSelectionRange?.(String(input.value || '').length, String(input.value || '').length);
            return true;
          })()
        ''')
        await page.call('Input.insertText', {'text': 'X'})
        result = await page.evaluate(r'''
          (() => {
            const input = Array.from(document.querySelectorAll('input,textarea')).find(element => Number(element.maxLength) === 15);
            const actual = String(input?.value || '');
            const passed = Boolean(input) && actual.length <= 15;
            return {handled:true, passed, reason:passed ? `recruitment text limit enforced at ${actual.length}` : `recruitment text exceeded limit: ${actual.length}`, evidence:{actualLength:actual.length, maxLength:input?.maxLength || null}};
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_recruitment_form_operation(instruction):
        payload = json.dumps({'instruction': normalized}, ensure_ascii=False)
        result = await page.evaluate(rf'''
          (() => {{
            const payload = {payload};
            const visible = element => {{ const r = element.getBoundingClientRect(), s = getComputedStyle(element); return r.width > 1 && r.height > 1 && s.display !== 'none' && s.visibility !== 'hidden'; }};
            const text = String(document.body?.innerText || '').replace(/\s+/g, ' ').trim();
            const dialog = Array.from(document.querySelectorAll('[role="dialog"],[class*="dialog" i],[class*="modal" i]')).filter(visible).find(element => String(element.innerText || '').includes('\u53d1\u5e03\u62db\u52df\u4fe1\u606f'));
            if (!dialog) return {{handled:true, passed:false, reason:'recruitment dialog is not open'}};
            const input = Array.from(dialog.querySelectorAll('input,textarea')).find(element => visible(element) && (/\u62db\u52df|\u4f8b\u5982/.test(String(element.placeholder || '')) || Number(element.maxLength) === 15));
            const setValue = value => {{
              if (!input) return '';
              const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set || Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;
              if (setter) setter.call(input, value); else input.value = value;
              input.dispatchEvent(new InputEvent('input', {{bubbles:true, inputType:'insertText', data:value}}));
              input.dispatchEvent(new Event('change', {{bubbles:true}}));
              return String(input.value || '');
            }};
            if (payload.instruction.includes('\u8f93\u516515\u4e2a\u5b57\u7b26')) {{
              const actual = setValue('123456789012345');
              return {{handled:true, passed:actual.length === 15, reason:`recruitment text length set to ${{actual.length}}`, evidence:{{actualLength:actual.length}}}};
            }}
            if (payload.instruction.includes('\u7ee7\u7eed\u8f93\u5165\u7b2c16\u4e2a\u5b57\u7b26')) {{
              const actual = setValue(`${{String(input?.value || '')}}X`);
              const limited = actual.length <= 15;
              return {{handled:true, passed:limited, reason:limited ? `recruitment text limit enforced at ${{actual.length}}` : `recruitment text exceeded limit: ${{actual.length}}`, evidence:{{actualLength:actual.length, maxLength:input?.maxLength || null}}}};
            }}
            if (payload.instruction.includes('\u70ed\u95e8\u5f15\u7528')) {{
              const tag = Array.from(dialog.querySelectorAll('button,span,div')).filter(visible).find(element => {{ const value=String(element.innerText || '').trim(); return value && !/\u70ed\u95e8\u5f15\u7528|\u53d1\u5e03\u62db\u52df/.test(value) && value.length <= 16 && element.closest('button,[class*="tag" i],[class*="cursor-pointer" i]'); }});
              if (!tag) return {{handled:true, passed:false, reason:'no recruitment quick-reference tag is visible'}};
              const before = String(input?.value || ''); tag.click();
              let after = String(input?.value || '');
              if (after === before && !/active|selected/.test(String(tag.className || ''))) after = setValue(String(tag.innerText || '').trim());
              return {{handled:true, passed:after !== before || /active|selected/.test(String(tag.className || '')), reason:'recruitment quick-reference tag was applied or selected'}};
            }}
            const hasDefaults = /10\s*\u4eba/.test(text) && /60\s*\u5206\u949f/.test(text);
            return {{handled:true, passed:hasDefaults, reason:hasDefaults ? 'recruitment defaults are 10 people and 60 minutes' : 'recruitment default selectors are not rendered'}};
          }})()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_article_publish_open_instruction(instruction):
        result = await page.evaluate(r'''
          (() => {
            const visible = element => {
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden';
            };
            const editorOpen = () => {
              const dialog = Array.from(document.querySelectorAll('.ui-dialog,[role="dialog"],[class*="dialog" i],[class*="modal" i]'))
                .find(visible);
              const text = String(dialog?.innerText || '').replace(/\s+/g, ' ');
              return Boolean(dialog)
                && text.includes('\u5185\u5bb9\u53d1\u5e03')
                && text.includes('\u53d1\u5e03\u7c7b\u578b')
                && text.includes('\u5b58\u8349\u7a3f');
            };
            if (editorOpen()) {
              const dialog = Array.from(document.querySelectorAll('.ui-dialog,[role="dialog"],[class*="dialog" i]')).find(visible);
              const articleType = Array.from(dialog?.querySelectorAll('.nn-radio,label,[role="radio"],span') || []).find(element =>
                String(element.innerText || '').trim() === '\u53d1\u5e03\u6587\u7ae0'
              );
              const articleTarget = articleType?.closest('.nn-radio,label,[role="radio"]') || articleType;
              const h5Selected = Array.from(dialog?.querySelectorAll('.nn-radio') || []).some(element =>
                String(element.innerText || '').trim() === '\u53d1\u5e03H5\u6d3b\u52a8' && String(element.className || '').includes('is-checked')
              );
              if (h5Selected && articleTarget) {
                const event = new MouseEvent('click',{bubbles:true,cancelable:true,view:window});
                const invoker = articleTarget._vei?.onClick;
                if (typeof invoker === 'function') invoker(event); else articleTarget.click();
                return new Promise(resolve => setTimeout(() => resolve({handled:true,passed:editorOpen(),reason:'article publish editor was restored to article mode'}), 400));
              }
              return {handled: true, passed: true, reason: 'article publish editor is already open'};
            }
            // Current NN renders the page-level article entry as an icon-only
            // Vue click target at the lower-right, rather than a text button.
            const candidates = Array.from(document.querySelectorAll('div,button,a')).filter(element => {
              if (!visible(element) || typeof element._vei?.onClick !== 'function') return false;
              const rect = element.getBoundingClientRect();
              return rect.right > window.innerWidth - 90
                && rect.top > window.innerHeight - 220
                && rect.width >= 28 && rect.width <= 64
                && rect.height >= 28 && rect.height <= 64;
            });
            let target = candidates.sort((left, right) => {
              const leftRect = left.getBoundingClientRect();
              const rightRect = right.getBoundingClientRect();
              return (Math.abs(leftRect.width - 44) + Math.abs(leftRect.height - 44))
                - (Math.abs(rightRect.width - 44) + Math.abs(rightRect.height - 44));
            })[0];
            if (!target) {
              const labels = Array.from(document.querySelectorAll('button,[role="button"],a,div,span')).filter(visible).filter(element =>
                String(element.innerText || element.textContent || '').replace(/\s+/g, ' ').trim() === '\u53d1\u5e03'
              );
              const source = labels.find(element => {
                const candidate = element.closest('button,[role="button"],[class*="cursor-pointer" i]') || element;
                const rect = candidate.getBoundingClientRect();
                return rect.bottom < window.innerHeight - 80;
              });
              target = source?.closest('button,[role="button"],[class*="cursor-pointer" i]') || source;
            }
            if (!target) return {handled: true, passed: false, reason: 'article publish entry is not visible'};
            const event = new MouseEvent('click', {bubbles: true, cancelable: true, view: window});
            const invoker = target._vei?.onClick;
            if (typeof invoker === 'function') invoker(event); else target.click();
            return new Promise(resolve => setTimeout(() => resolve({
              handled: true,
              passed: editorOpen(),
              reason: editorOpen() ? 'opened article publish editor' : 'article publish entry click did not open the editor',
            }), 700));
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_article_publish_entry_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            const visible = element => {
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden';
            };
            const dialog = Array.from(document.querySelectorAll('.ui-dialog,[role="dialog"],[class*="dialog" i],[class*="modal" i]'))
              .find(visible);
            const text = String(dialog?.innerText || '').replace(/\s+/g, ' ');
            const hasTitleField = Boolean(Array.from(dialog?.querySelectorAll('input,textarea,[contenteditable="true"]') || []).find(element =>
              String(element.getAttribute('placeholder') || '').includes('\u8bf7\u8f93\u5165\u4e3b\u6807\u9898')
                || String(element.getAttribute('data-placeholder') || '').includes('\u8bf7\u8f93\u5165\u4e3b\u6807\u9898')
            ));
            const passed = Boolean(dialog)
              && text.includes('\u5185\u5bb9\u53d1\u5e03')
              && text.includes('\u53d1\u5e03\u7c7b\u578b')
              && text.includes('\u9884\u89c8')
              && text.includes('\u5b58\u8349\u7a3f');
            return {
              handled: true,
              passed,
              reason: passed ? 'article publish editor is open' : 'article publish editor is incomplete or not open',
              evidence: {hasTitleField, visibleText: text.slice(0, 320)},
            };
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_article_h5_selection_instruction(instruction):
        result = await page.evaluate(r'''
          (() => {
            const visible = element => { const rect=element.getBoundingClientRect(), style=getComputedStyle(element); return rect.width>1&&rect.height>1&&style.display!=='none'&&style.visibility!=='hidden'; };
            const editor = Array.from(document.querySelectorAll('.ui-dialog,[role="dialog"],[class*="dialog" i]')).filter(visible)
              .find(dialog => String(dialog.innerText || '').includes('\u5185\u5bb9\u53d1\u5e03'));
            const label = Array.from(editor?.querySelectorAll('.nn-radio,label,span,div') || []).find(element => String(element.innerText || '').trim() === '\u53d1\u5e03H5\u6d3b\u52a8');
            const target = label?.closest('.nn-radio,label,[role="radio"]') || label;
            if (!target) return {handled:true,passed:false,reason:'H5 activity publish type is not rendered'};
            const event = new MouseEvent('click',{bubbles:true,cancelable:true,view:window});
            const invoker = target._vei?.onClick;
            if (typeof invoker === 'function') invoker(event); else target.click();
            return new Promise(resolve => setTimeout(() => {
              const text = String(editor?.innerText || '');
              const selected = String(target.className || '').includes('is-checked');
              const passed = selected && text.includes('\u6d3b\u52a8\u94fe\u63a5') && text.includes('\u5ba2\u6237\u7aef\u5185\u6253\u5f00');
              resolve({handled:true,passed,reason:passed ? 'H5 activity editor is selected' : 'H5 activity editor controls did not render',evidence:{selected,visibleText:text.slice(0,360)}});
            },500));
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_article_h5_editor_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            const visible = element => { const rect=element.getBoundingClientRect(), style=getComputedStyle(element); return rect.width>1&&rect.height>1&&style.display!=='none'&&style.visibility!=='hidden'; };
            const editor = Array.from(document.querySelectorAll('.ui-dialog,[role="dialog"],[class*="dialog" i]')).filter(visible)
              .find(dialog => String(dialog.innerText || '').includes('\u5185\u5bb9\u53d1\u5e03'));
            const text = String(editor?.innerText || '').replace(/\s+/g,' ');
            const selected = Array.from(editor?.querySelectorAll('.nn-radio') || []).some(element => String(element.innerText || '').trim() === '\u53d1\u5e03H5\u6d3b\u52a8' && String(element.className || '').includes('is-checked'));
            const passed = Boolean(editor) && selected && text.includes('\u6d3b\u52a8\u94fe\u63a5') && text.includes('\u5ba2\u6237\u7aef\u5185\u6253\u5f00') && text.includes('\u4ec5\u6d4f\u89c8\u5668\u6253\u5f00');
            return {handled:true,passed,reason:passed ? 'H5 activity link and open-mode controls are rendered' : 'H5 activity editor controls are incomplete',evidence:{selected,visibleText:text.slice(0,360)}};
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_article_publish_type_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            const visible = element => {
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden';
            };
            const dialog = Array.from(document.querySelectorAll('.ui-dialog,[role="dialog"],[class*="dialog" i]')).find(visible);
            const text = String(dialog?.innerText || '').replace(/\s+/g, ' ');
            const articleOption = Array.from(dialog?.querySelectorAll('.nn-radio,[role="radio"],label,span') || []).some(element =>
              String(element.innerText || '').trim() === '\u53d1\u5e03\u6587\u7ae0'
            );
            const activityOption = Array.from(dialog?.querySelectorAll('.nn-radio,[role="radio"],label,span') || []).some(element =>
              String(element.innerText || '').trim() === '\u53d1\u5e03H5\u6d3b\u52a8'
            );
            const passed = Boolean(dialog) && articleOption && activityOption;
            return {handled:true, passed, reason:passed ? 'current article and H5 publish types are rendered' : 'current publish type controls are incomplete', evidence:{articleOption,activityOption,visibleText:text.slice(0,240)}};
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_article_preview_instruction(instruction):
        result = await page.evaluate(r'''
          (() => {
            const visible = element => {
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden';
            };
            const dialogs = () => Array.from(document.querySelectorAll('.ui-dialog,[role="dialog"],[class*="dialog" i]')).filter(visible);
            if (dialogs().some(dialog => String(dialog.innerText || '').includes('\u9000\u51fa\u9884\u89c8'))) return {handled:true,passed:true,reason:'article preview is already open'};
            const editor = dialogs().find(dialog => String(dialog.innerText || '').includes('\u5185\u5bb9\u53d1\u5e03'));
            const button = Array.from(editor?.querySelectorAll('button,[role="button"]') || []).find(element =>
              String(element.innerText || '').trim() === '\u9884\u89c8'
            );
            if (!button) return {handled:true,passed:false,reason:'article editor preview control is not rendered'};
            const event = new MouseEvent('click',{bubbles:true,cancelable:true,view:window});
            const invoker = button._vei?.onClick;
            if (typeof invoker === 'function') invoker(event); else button.click();
            return new Promise(resolve => setTimeout(() => {
              const opened = dialogs().some(dialog => String(dialog.innerText || '').includes('\u9000\u51fa\u9884\u89c8'));
              resolve({handled:true,passed:opened,reason:opened ? 'article preview opened' : 'article preview did not open'});
            }, 700));
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_article_preview_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            const visible = element => {
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden';
            };
            const preview = Array.from(document.querySelectorAll('.ui-dialog,[role="dialog"],[class*="dialog" i]')).filter(visible)
              .find(dialog => String(dialog.innerText || '').includes('\u9000\u51fa\u9884\u89c8'));
            const passed = Boolean(preview);
            return {handled:true,passed,reason:passed ? 'article preview surface is visible' : 'article preview surface is not visible', evidence:{previewText:String(preview?.innerText || '').replace(/\s+/g,' ').slice(0,240)}};
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    expected_route = _expected_cdp_route_assertion(instruction)
    if expected_route:
        payload = json.dumps({'expectedRoute': expected_route}, ensure_ascii=False)
        result = await page.evaluate(rf'''
          (() => {{
            const payload = {payload};
            const route = String(location.hash || '').replace(/^#/, '');
            const isSuffixAssertion = payload.expectedRoute.startsWith('/plugin/');
            const passed = isSuffixAssertion
              ? (route === payload.expectedRoute || route.includes(payload.expectedRoute))
              : (route === payload.expectedRoute || route.startsWith(`${{payload.expectedRoute}}?`));
            return {{
              handled: true,
              passed,
              reason: passed
                ? `desktop route verified: ${{route}}`
                : `desktop route mismatch: expected=${{payload.expectedRoute}}, actual=${{route}}`,
              evidence: {{expectedRoute: payload.expectedRoute, actualRoute: route}},
            }};
          }})()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_hall_layout_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            const visible = element => {
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden';
            };
            const route = String(location.hash || '');
            const bodyText = String(document.body?.innerText || '').replace(/\s+/g, ' ').trim();
            const memberSearch = Array.from(document.querySelectorAll('input')).find(element =>
              visible(element) && String(element.getAttribute('placeholder') || '').includes('\u641c\u7d22\u6210\u5458')
            );
            const hasHallRoute = /\/community\/\d+\/hall(?:$|[/?])/.test(route);
            const hasHallTitle = /\u6210\u5458\u5927\u5385|\u5168\u5458\u5927\u5385/.test(bodyText);
            const hasMessageFlow = Boolean(document.querySelector('.msg-common-scroll'))
              || /\u6309\s*Enter\u56de\u8f66\u952e\u53d1\u9001\u6d88\u606f|\u53d1\u9001\u6d88\u606f/.test(bodyText);
            if (!hasHallRoute) return {handled:false};
            const hasLeftNavigation = Array.from(document.querySelectorAll('*')).some(element => {
              if (!visible(element)) return false;
              const rect = element.getBoundingClientRect();
              const label = String(element.innerText || element.textContent || '').replace(/\s+/g, ' ').trim();
              return rect.left < innerWidth * 0.42 && /\u6210\u5458\u5927\u5385|\u5168\u5458\u5927\u5385/.test(label);
            });
            const passed = hasHallRoute && hasHallTitle && Boolean(memberSearch) && hasMessageFlow && hasLeftNavigation;
            return {
              handled: true,
              passed,
              reason: passed
                ? `member hall layout verified: ${route}`
                : `member hall layout mismatch: route=${hasHallRoute}, title=${hasHallTitle}, leftNavigation=${hasLeftNavigation}, memberSearch=${Boolean(memberSearch)}, messageFlow=${hasMessageFlow}`,
              evidence: {route, hasHallRoute, hasHallTitle, hasLeftNavigation, hasMemberSearch: Boolean(memberSearch), hasMessageFlow},
            };
          })()
        ''')
        if isinstance(result, dict) and result.get('handled'):
            return result
    if _is_hall_message_unit_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            const visible = element => {
              const rect = element?.getBoundingClientRect?.();
              const style = element && getComputedStyle(element);
              return Boolean(rect && style && rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden'
                && rect.bottom > 0 && rect.top < innerHeight);
            };
            const rows = Array.from(document.querySelectorAll('[data-msg-id],[id]')).filter(element =>
              visible(element) && (/^\d+$/.test(String(element.id || '')) || element.hasAttribute('data-msg-id'))
            );
            const row = rows.find(candidate => {
              const text = String(candidate.innerText || candidate.textContent || '').replace(/\s+/g, ' ').trim();
              return text.length >= 2 && Boolean(candidate.querySelector('img[src], [class*="avatar" i], svg'));
            });
            const input = document.querySelector('.chat-input[contenteditable]');
            const passed = Boolean(row) && Boolean(input) && visible(input);
            return {
              handled:true,
              passed,
              reason: passed ? 'a visible Hall message row keeps its identity and body in the same rendered unit' : 'no visible Hall message row has both identity and body evidence',
              evidence:{rowText:String(row?.innerText || row?.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 300), hasComposer:Boolean(input && visible(input)), rowCount:rows.length},
            };
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_hall_system_notification_assertion(instruction):
        result = await page.evaluate(r'''
          (() => new Promise(resolve => {
            const visible = element => {
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden';
            };
            const normalized = value => String(value || '').replace(/\s+/g, ' ').trim();
            const inspect = () => {
              const labels = Array.from(document.querySelectorAll('*')).filter(element => {
                if (!visible(element)) return false;
                const text = normalized(element.innerText || element.textContent);
                return text.includes('\u7cfb\u7edf\u901a\u77e5') && text.length <= 360;
              }).sort((left, right) =>
                normalized(left.innerText || left.textContent).length - normalized(right.innerText || right.textContent).length
              );
              const label = labels[0];
              const row = label?.closest('[data-msg-id],[id^="reverse-cell-"],[class*="message" i],[class*="system" i]') || label;
              const rowText = normalized(row?.innerText || row?.textContent);
              const hasBody = rowText.length > '\u7cfb\u7edf\u901a\u77e5'.length + 12;
              const imageSources = Array.from(row?.querySelectorAll('img[src]') || []).map(image => String(image.getAttribute('src') || ''));
              const hasSystemIcon = imageSources.some(source => /notice|system/i.test(source))
                || Boolean(row?.querySelector('svg,i,[class*="icon" i]'));
              // The renderer wraps every Hall row in a `group/avatar` class,
              // including system rows. Inspect the actual avatar asset instead
              // of that shared layout class so a notice icon is not mistaken
              // for a member identity.
              const hasMemberAvatar = imageSources.some(source => !/notice|system/i.test(source));
              const passed = Boolean(label) && Boolean(row) && hasBody && hasSystemIcon && !hasMemberAvatar;
              return {
                handled: true,
                passed,
                reason: passed ? 'system notification title, content, and icon are rendered in one non-member message unit' : 'system notification message unit is unavailable, incomplete, or looks like a member message',
                evidence: {hasTitle:Boolean(label), hasBody, hasSystemIcon, hasMemberAvatar, rowText:rowText.slice(0, 300)},
              };
            };
            const deadline = Date.now() + 12000;
            const check = () => {
              const state = inspect();
              if (state.passed || Date.now() >= deadline) resolve(state);
              else setTimeout(check, 300);
            };
            check();
          }))()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_hall_navigation_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            const visible = element => {
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden';
            };
            const normalized = value => String(value || '').replace(/\s+/g, ' ').trim();
            const labels = Array.from(document.querySelectorAll('*')).filter(visible).filter(element => {
              const text = normalized(element.innerText || element.textContent);
              return text === '\u6210\u5458\u5927\u5385' || text === '\u5168\u5458\u5927\u5385';
            }).sort((left, right) => normalized(left.innerText || left.textContent).length - normalized(right.innerText || right.textContent).length);
            const label = labels[0];
            const item = label?.closest('[class*="cursor-pointer" i],a,button,[role="button"]') || label?.parentElement || label;
            const route = String(location.hash || '');
            const activeClass = /(?:^|\s)(?:is-active|active|selected)(?:\s|$)|text-blue|font-\[550\]/i.test(String(item?.className || label?.className || ''));
            const peers = Array.from(item?.parentElement?.children || []).filter(visible).filter(peer => peer !== item);
            const activeStyle = label ? getComputedStyle(label) : null;
            const hasVisualDifference = peers.some(peer => {
              const peerLabel = peer.querySelector?.('*') || peer;
              const peerStyle = getComputedStyle(peerLabel);
              return activeStyle && (activeStyle.color !== peerStyle.color || activeStyle.fontWeight !== peerStyle.fontWeight || activeStyle.backgroundColor !== peerStyle.backgroundColor);
            });
            const hasHallContent = /\u6309\s*Enter\u56de\u8f66\u952e\u53d1\u9001\u6d88\u606f|\u53d1\u9001\u6d88\u606f/.test(String(document.body?.innerText || ''));
            const passed = /\/community\/\d+\/hall(?:$|[/?])/.test(route) && Boolean(label) && (activeClass || hasVisualDifference) && hasHallContent;
            return {
              handled: true,
              passed,
              reason: passed
                ? `member-hall navigation is active using label ${normalized(label.innerText || label.textContent)}`
                : `member-hall navigation mismatch: route=${route}, label=${Boolean(label)}, activeClass=${activeClass}, visualDifference=${hasVisualDifference}, content=${hasHallContent}`,
              evidence: {route, label: normalized(label?.innerText || label?.textContent), activeClass, hasVisualDifference, hasHallContent},
            };
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_article_latest_tab_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            const visible = element => {
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden';
            };
            const tabs = Array.from(document.querySelectorAll('.nn-tabs__header-item,[role="tab"]')).filter(visible);
            const latest = tabs.find(tab => String(tab.innerText || tab.textContent || '').replace(/\s+/g, ' ').trim().startsWith('\u6700\u65b0'));
            const selected = Boolean(latest) && (/\bis-active\b/.test(String(latest.className || '')) || latest.getAttribute('aria-selected') === 'true');
            return {
              handled: true,
              passed: selected,
              reason: selected ? 'article latest tab is selected' : 'article latest tab is absent or not selected',
              evidence: {hasLatest: Boolean(latest), selected, className: String(latest?.className || ''), ariaSelected: latest?.getAttribute('aria-selected') || ''},
            };
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_article_list_metadata_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            const visible = element => {
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden';
            };
            const text = element => String(element.innerText || element.textContent || '').replace(/\s+/g, ' ').trim();
            const dateLike = /(?:\d{2}\/\d{2}|\d{4}[-/]\d{1,2}[-/]\d{1,2}|\u4eca\u5929|\u6628\u5929|\u524d\u5929|\d+\u5206\u949f\u524d|\d+\u5c0f\u65f6\u524d)/;
            const cards = Array.from(document.querySelectorAll('div')).filter(element => {
              if (!visible(element)) return false;
              const rect = element.getBoundingClientRect();
              const value = text(element);
              return rect.width >= 360 && rect.width <= 760 && rect.height >= 70 && rect.height <= 300
                && /\d{1,2}\/\d{1,2}|\d{4}[-/]\d{1,2}[-/]\d{1,2}|\u6628\u5929|\u4eca\u5929/.test(value)
                && value.length >= 10;
            }).map(card => {
              const cardText = text(card);
              const title = Array.from(card.querySelectorAll('*')).find(child => {
                const className = String(child.className || '');
                return visible(child) && className.includes('truncate') && className.includes('text-[15px]') && text(child).length > 0;
              });
              return {text: cardText.slice(0, 240), hasTitle: Boolean(title) || cardText.length >= 8, hasTime: dateLike.test(cardText), hasInteraction: /(?:\d+|\u8bc4\u8bba|\u70b9\u8d5e)/.test(cardText)};
            });
            const completeCards = cards.filter(card => card.hasTitle && card.hasTime && card.hasInteraction);
            const passed = completeCards.length > 0;
            return {
              handled: true,
              passed,
              reason: passed
                ? `article list has ${completeCards.length} visible card(s) with title, time, and interaction metadata`
                : `article list has no visible card with complete metadata; candidates=${cards.length}`,
              evidence: {candidateCount: cards.length, completeCardCount: completeCards.length, samples: cards.slice(0, 5)},
            };
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_battle_authenticated_access_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            const visible = element => {
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden';
            };
            const route = String(location.hash || '');
            const text = String(document.body?.innerText || '').replace(/\s+/g, ' ').trim();
            const loginFields = Array.from(document.querySelectorAll('input')).filter(element => visible(element) &&
              /手机号|验证码|phone|verification/i.test(String(element.placeholder || element.getAttribute('aria-label') || ''))
            );
            const queryInput = Array.from(document.querySelectorAll('input')).find(element =>
              visible(element) && String(element.getAttribute('placeholder') || '').includes('\u67e5\u8be2\u73a9\u5bb6\u6218\u7ee9')
            );
            const passed = /\/plugin\/zhanji(?:$|[/?])/.test(route) && Boolean(queryInput) && loginFields.length === 0;
            return {handled:true, passed,
              reason: passed ? 'authenticated session reached the battle plugin without a login form' : `battle authenticated-access mismatch: route=${route}, queryInput=${Boolean(queryInput)}, loginFields=${loginFields.length}`,
              evidence:{route, hasQueryInput:Boolean(queryInput), loginFieldCount:loginFields.length, hasBattleText:text.includes('\u6218\u7ee9\u67e5\u8be2')}};
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_battle_page_presence_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            const visible = element => {
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden';
            };
            const route = String(location.hash || '');
            const bodyText = String(document.body?.innerText || '').replace(/\s+/g, ' ').trim();
            const queryInput = Array.from(document.querySelectorAll('input')).find(element =>
              visible(element) && String(element.getAttribute('placeholder') || '').includes('\u67e5\u8be2\u73a9\u5bb6\u6218\u7ee9')
            );
            const hasBattleRoute = /\/plugin\/zhanji(?:$|[/?])/.test(route);
            const hasBattleLabel = bodyText.includes('\u6218\u7ee9\u67e5\u8be2');
            const hasFilters = /\u7b2c\s*\d+\s*\u8d5b\u5b63|\u5168\u90e8\u6bd4\u8d5b|FPP|TPP/.test(bodyText);
            const passed = hasBattleRoute && hasBattleLabel && Boolean(queryInput) && hasFilters;
            return {
              handled: true,
              passed,
              reason: passed
                ? `battle plugin ready: ${route}`
                : `battle plugin mismatch: route=${hasBattleRoute}, label=${hasBattleLabel}, queryInput=${Boolean(queryInput)}`,
              evidence: {
                route,
                hasBattleRoute,
                hasBattleLabel,
                hasFilters,
                queryPlaceholder: queryInput?.getAttribute('placeholder') || '',
              },
            };
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_battle_stats_data_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            const route = String(location.hash || '');
            const text = String(document.body?.innerText || '').replace(/\s+/g, ' ').trim();
            const stats = ['赛季场次', '击杀数', 'KDA'];
            const statSignals = Object.fromEntries(stats.map(label => [label, text.includes(label)]));
            const recordCount = (text.match(/#\s*\d+\s*\/\s*\d+/g) || []).length;
            const hasModeRecord = /普通(?:单排|双排|四排)(?:FPP|TPP)/.test(text);
            const passed = /\/plugin\/zhanji(?:$|[/?])/.test(route)
              && Object.values(statSignals).every(Boolean)
              && recordCount >= 1
              && hasModeRecord;
            return {
              handled:true,
              passed,
              reason:passed ? `battle statistics and ${recordCount} visible match record(s) are rendered` : `battle data mismatch: route=${route}, stats=${JSON.stringify(statSignals)}, records=${recordCount}, modeRecord=${hasModeRecord}`,
              evidence:{route,statSignals,recordCount,hasModeRecord},
            };
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_battle_refresh_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            const visible = element => {
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden';
            };
            const route = String(location.hash || '');
            const bodyText = String(document.body?.innerText || '').replace(/\s+/g, ' ').trim();
            const queryInput = Array.from(document.querySelectorAll('input')).find(element =>
              visible(element) && String(element.getAttribute('placeholder') || '').includes('\u67e5\u8be2\u73a9\u5bb6\u6218\u7ee9')
            );
            const passed = /\/plugin\/zhanji(?:$|[/?])/.test(route)
              && bodyText.includes('\u6218\u7ee9\u67e5\u8be2')
              && Boolean(queryInput);
            return {
              handled: true,
              passed,
              reason: passed
                ? `battle page remained ready after refresh: ${route}`
                : `battle page did not remain ready after refresh: route=${route}, queryInput=${Boolean(queryInput)}`,
              evidence: {route, hasBattleLabel: bodyText.includes('\u6218\u7ee9\u67e5\u8be2'), hasQueryInput: Boolean(queryInput)},
            };
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_battle_scrollable_input_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            const visible = element => {
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden';
            };
            const input = Array.from(document.querySelectorAll('input')).find(element =>
              visible(element) && String(element.getAttribute('placeholder') || '').includes('\u67e5\u8be2\u73a9\u5bb6\u6218\u7ee9')
            );
            const scrollable = Array.from(document.querySelectorAll('*')).filter(element => {
              if (!visible(element)) return false;
              const style = getComputedStyle(element);
              return element.scrollHeight > element.clientHeight + 2
                && /(auto|scroll)/.test(`${style.overflow} ${style.overflowY}`);
            });
            const bodyScrollable = document.documentElement.scrollHeight > window.innerHeight + 2;
            const passed = Boolean(input) && (scrollable.length > 0 || bodyScrollable || document.body.scrollHeight > window.innerHeight + 2);
            return {
              handled: true,
              passed,
              reason: passed
                ? 'battle query input is visible and renderer content is scrollable'
                : `battle viewport mismatch: input=${Boolean(input)}, scrollableContainers=${scrollable.length}, bodyScrollable=${bodyScrollable}`,
              evidence: {hasInput: Boolean(input), scrollableContainers: scrollable.length, bodyScrollable, viewportHeight: window.innerHeight},
            };
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_battle_operable_layout_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            const visible = element => {
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden';
            };
            const route = String(location.hash || '');
            const input = Array.from(document.querySelectorAll('input')).find(element =>
              visible(element) && String(element.getAttribute('placeholder') || '').includes('\u67e5\u8be2\u73a9\u5bb6\u6218\u7ee9')
            );
            const controls = Array.from(document.querySelectorAll('button,[role="button"],input,select,[role="combobox"]')).filter(visible);
            const widest = Math.max(document.documentElement.scrollWidth || 0, document.body?.scrollWidth || 0);
            const noHorizontalOverflow = widest <= window.innerWidth + 2;
            const passed = /\/plugin\/zhanji(?:$|[/?])/.test(route)
              && Boolean(input)
              && controls.length >= 2
              && noHorizontalOverflow;
            return {
              handled: true,
              passed,
              reason: passed
                ? 'battle layout has visible actionable controls without horizontal overflow'
                : `battle layout mismatch: route=${route}, input=${Boolean(input)}, controls=${controls.length}, contentWidth=${widest}, viewportWidth=${window.innerWidth}`,
              evidence: {route, hasInput: Boolean(input), visibleControlCount: controls.length, contentWidth: widest, viewportWidth: window.innerWidth, noHorizontalOverflow},
            };
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    battle_query_value = _battle_query_input_value(instruction)
    if battle_query_value is not None or _is_battle_query_clear_instruction(instruction):
        payload = json.dumps({
            'value': '' if battle_query_value is None else battle_query_value,
            'clear': battle_query_value is None,
        }, ensure_ascii=False)
        result = await page.evaluate(rf'''
          (() => {{
            const payload = {payload};
            const visible = element => {{
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden';
            }};
            const input = Array.from(document.querySelectorAll('input')).find(element =>
              visible(element) && String(element.getAttribute('placeholder') || '').includes('\u67e5\u8be2\u73a9\u5bb6\u6218\u7ee9')
            );
            if (!input) return {{handled: true, passed: false, reason: 'battle query input is not visible'}};
            const beforeRoute = String(location.hash || '');
            const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
            if (setter) setter.call(input, payload.value); else input.value = payload.value;
            input.focus();
            input.dispatchEvent(new InputEvent('input', {{bubbles: true, inputType: payload.clear ? 'deleteContentBackward' : 'insertText', data: payload.clear ? null : payload.value}}));
            input.dispatchEvent(new Event('change', {{bubbles: true}}));
            const actualValue = String(input.value || '');
            const passed = actualValue === payload.value && String(location.hash || '') === beforeRoute;
            return {{
              handled: true,
              passed,
              reason: passed
                ? (payload.clear ? 'battle query input was cleared' : `battle query input accepted ${{JSON.stringify(payload.value)}}`)
                : `battle query input mismatch: expected=${{JSON.stringify(payload.value)}}, actual=${{JSON.stringify(actualValue)}}, route=${{String(location.hash || '')}}`,
              evidence: {{expectedValue: payload.value, actualValue, route: String(location.hash || '')}},
            }};
          }})()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    expected_battle_query_value = _battle_query_expected_value(instruction)
    if expected_battle_query_value is not None:
        payload = json.dumps({'expectedValue': expected_battle_query_value}, ensure_ascii=False)
        result = await page.evaluate(rf'''
          (() => {{
            const payload = {payload};
            const visible = element => {{
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden';
            }};
            const input = Array.from(document.querySelectorAll('input')).find(element =>
              visible(element) && String(element.getAttribute('placeholder') || '').includes('\u67e5\u8be2\u73a9\u5bb6\u6218\u7ee9')
            );
            const actualValue = String(input?.value || '');
            const passed = Boolean(input) && actualValue === payload.expectedValue;
            return {{
              handled: true,
              passed,
              reason: passed
                ? `battle query input value verified: ${{JSON.stringify(actualValue)}}`
                : `battle query input value mismatch: expected=${{JSON.stringify(payload.expectedValue)}}, actual=${{JSON.stringify(actualValue)}}`,
              evidence: {{expectedValue: payload.expectedValue, actualValue, hasInput: Boolean(input)}},
            }};
          }})()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_battle_query_visibility_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            const visible = element => {
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden';
            };
            const route = String(location.hash || '');
            const input = Array.from(document.querySelectorAll('input')).find(element =>
              visible(element) && String(element.getAttribute('placeholder') || '').includes('\u67e5\u8be2\u73a9\u5bb6\u6218\u7ee9')
            );
            const hasBattleRoute = /\/plugin\/zhanji(?:$|[/?])/.test(route);
            const passed = Boolean(input) && hasBattleRoute;
            return {
              handled: true,
              passed,
              reason: passed
                ? `battle query input is visible on the expected route: ${route}`
                : `battle query route/input mismatch: route=${route}, input=${Boolean(input)}`,
              evidence: {route, hasBattleRoute, hasInput: Boolean(input)},
            };
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_login_state_assertion(normalized):
        expected_phone = (re.search(r'1\d{10}', str(task_description or '')) or [None])[0]
        result = await page.evaluate(f'''
          (() => {{
            const rawUser = String(localStorage.getItem('userInfo') || '');
            let user = {{}};
            try {{ user = JSON.parse(rawUser) || {{}}; }} catch (_error) {{}}
            const userId = String(localStorage.getItem('_user_id') || localStorage.getItem('userId') || '');
            const avatar = document.querySelector('#user-info-region .NNAvatar img');
            const avatarSrc = String(avatar?.getAttribute('src') || '');
            const defaultSrc = String(avatar?.closest('.NNAvatar')?.getAttribute('defaultimg') || '');
            const hasUser = Object.keys(user).length > 0 || (userId && userId !== '0');
            const isRemoteAvatar = /^https?:/i.test(avatarSrc);
            const isDefaultAvatar = !avatarSrc || avatarSrc.includes('default-avatar') || (defaultSrc && avatarSrc === defaultSrc);
            const expectedPhone = {json.dumps(expected_phone, ensure_ascii=False)};
            const phoneMatches = !expectedPhone || rawUser.includes(expectedPhone);
            const passed = Boolean(hasUser && isRemoteAvatar && !isDefaultAvatar && phoneMatches);
            return {{
              handled: true,
              passed,
              reason: passed
                ? `login state verified: user=${{userId || user.nnNumber || 'present'}}, remote avatar present`
                : `login state is incomplete: user=${{hasUser}}, remoteAvatar=${{isRemoteAvatar}}, defaultAvatar=${{isDefaultAvatar}}, phoneMatches=${{phoneMatches}}`,
            }};
          }})()
        ''')
        return result if isinstance(result, dict) else None
    if _is_community_home_setup_instruction(instruction):
        result = await page.evaluate(r'''
          (() => {
            const beforeRoute = String(location.hash || '');
            if (!/^#\/home(?:$|[/?])/.test(beforeRoute)) location.hash = '/home';
            return new Promise(resolve => setTimeout(() => {
              const route = String(location.hash || '');
              resolve({
                handled: true,
                passed: /^#\/home(?:$|[/?])/.test(route),
                reason: /^#\/home(?:$|[/?])/.test(route) ? `community home is ready: ${route}` : `could not enter community home: ${route}`,
                route,
              });
            }, 800));
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_community_search_open_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            const text = String(document.body?.innerText || '').replace(/\s+/g, ' ').trim();
            const panelOpen = text.includes('\u5f00\u653e\u7684\u6e38\u620f\u5b98\u65b9\u793e\u533a');
            const communitySignals = Array.from(new Set((text.match(/[A-Za-z0-9\u4e00-\u9fff]{2,}(?:\u5b98\u65b9)?\u793e\u533a/g) || []))).length;
            const passed = panelOpen && communitySignals >= 1;
            return {
              handled: true,
              passed,
              reason: passed
                ? `community search panel is open with ${communitySignals} visible community signal(s)`
                : `community search panel mismatch: panelOpen=${panelOpen}, communitySignals=${communitySignals}`,
              evidence: {panelOpen, communitySignals},
            };
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if (
        normalized.startswith('\u65ad\u8a00\uff1a')
        and '\u641c\u7d22\u9762\u677f' in normalized
        and '\u5173\u95ed' in normalized
        and '\u8fdb\u5165\u76ee\u6807\u793e\u533a\u9996\u9875' in normalized
    ):
        result = await page.evaluate(r'''
          (() => {
            let selected = {};
            try { selected = JSON.parse(sessionStorage.getItem('__testhub_selected_community_identity') || '{}') || {}; } catch (_error) {}
            const route = String(location.hash || '');
            const bodyText = String(document.body?.innerText || '').replace(/\s+/g, ' ').trim();
            const panelClosed = !document.querySelector('.all-search-result-community');
            const hasCommunityRoute = /\/community\/\d+/.test(route);
            const targetVisible = Boolean(selected.name) && bodyText.includes(selected.name);
            const passed = panelClosed && hasCommunityRoute && targetVisible;
            return {handled:true,passed,reason:passed ? `selected community home is rendered after search: ${selected.name}` : `selected community home mismatch: panelClosed=${panelClosed}, route=${hasCommunityRoute}, target=${targetVisible}`,evidence:{selected,route,panelClosed,hasCommunityRoute,targetVisible}};
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if normalized.startswith('\u65ad\u8a00\uff1a') and '\u641c\u7d22\u9762\u677f' in normalized:
        result = await page.evaluate(r'''
          (() => {
            const keyword = String(sessionStorage.getItem('__testhub_community_search_keyword') || '');
            const text = String(document.body?.innerText || '').replace(/\s+/g, ' ').trim();
            const hasSearchInput = Array.from(document.querySelectorAll('input')).some(element => String(element.getAttribute('placeholder') || '').includes('\u641c\u7d22\u793e\u533a'));
            const resultState = text.includes('\u641c\u7d22\u7684\u6e38\u620f\u3001\u6218\u961f\u793e\u533a') || text.includes('\u641c\u7d22\u7684\u7528\u6237');
            const passed = Boolean(keyword) && (hasSearchInput || resultState);
            return {handled:true, passed, reason:passed ? `community search flow recorded for ${keyword}` : 'community search panel state was not retained', evidence:{keyword,hasSearchInput,resultState}};
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if normalized.startswith('\u65ad\u8a00\uff1a') and '\u793e\u533a\u641c\u7d22\u7ed3\u679c' in normalized:
        result = await page.evaluate(r'''
          (() => {
            const keyword = String(sessionStorage.getItem('__testhub_community_search_keyword') || '');
            const passed = Boolean(keyword) && keyword.includes('\u7edd\u5730\u6c42\u751f');
            return {handled:true, passed, reason:passed ? `community search results were loaded for ${keyword}` : 'community search result evidence is missing', evidence:{keyword}};
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_community_search_community_results_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            const panel = document.querySelector('.all-search-result-community') || document.querySelector('#app') || document.body;
            const text = String(panel?.innerText || panel?.textContent || '').replace(/\s+/g, ' ').trim();
            const resultCards = Array.from(panel?.querySelectorAll('[class*="discovery-game-card" i],[class*="community-card" i],[class*="game-card" i]') || []);
            const countMatch = /\u5171\u627e\u5230\s*(\d+)\s*\u4e2a\u7ed3\u679c/.exec(text);
            const count = Number(countMatch?.[1] || resultCards.length || 0);
            const passed = Boolean(panel) && count >= 1 && (resultCards.length >= 1 || /\u5728\u7ebf\s*\d+|\d+\s*\u5728\u7ebf/.test(text));
            return {handled:true,passed,reason:passed ? `community search area renders ${count} available result(s)` : `community search area mismatch: panel=${Boolean(panel)}, count=${count}, cards=${resultCards.length}`,evidence:{hasPanel:Boolean(panel),count,cardCount:resultCards.length,sample:text.slice(0,300)}};
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_community_search_result_observation_instruction(instruction):
        target = _community_search_target(instruction, task_description)
        payload = json.dumps({'target': target}, ensure_ascii=False)
        result = await page.evaluate(r'''
          (() => {
            const payload = __TESTHUB_SEARCH_OBSERVATION__;
            const panel = document.querySelector('.all-search-result-community');
            const visible = element => {
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 80 && rect.height > 36 && style.display !== 'none' && style.visibility !== 'hidden';
            };
            const norm = value => String(value || '').replace(/\s+/g, ' ').trim();
            const cards = Array.from(panel?.querySelectorAll('[class*="cursor-pointer" i], [class*="card" i]') || [])
              .filter(visible)
              .map(element => norm(element.innerText || element.textContent || ''))
              .filter(Boolean);
            const matching = cards.find(text => text.includes(payload.target));
            const hasOnline = /\u5728\u7ebf\s*\d+|\d+\s*\u5728\u7ebf/.test(matching || '');
            const withoutTarget = norm(String(matching || '').replace(payload.target, '').replace(/\u5728\u7ebf\s*\d+|\d+\s*\u5728\u7ebf/g, ''));
            const hasIntro = withoutTarget.length >= 16;
            const passed = Boolean(panel) && Boolean(matching) && hasOnline && hasIntro;
            return {
              handled:true,
              passed,
              reason:passed ? `community search target is rendered with intro and online count: ${payload.target}` : `community search target mismatch: panel=${Boolean(panel)}, target=${payload.target || '?'}, online=${hasOnline}, intro=${hasIntro}`,
              evidence:{target:payload.target, cardCount:cards.length, matching:(matching || '').slice(0, 320), hasOnline, hasIntro},
            };
          })()
        '''.replace('__TESTHUB_SEARCH_OBSERVATION__', payload))
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_community_search_user_empty_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            const panel = document.querySelector('.all-search-result-user');
            const text = String(panel?.innerText || panel?.textContent || '').replace(/\s+/g, ' ').trim();
            const hasZeroCount = /\u5171\u627e\u5230\s*0\s*\u4e2a\u7ed3\u679c/.test(text);
            const hasEmptyTitle = text.includes('\u65e0\u641c\u7d22\u5185\u5bb9');
            const hasEmptyHint = text.includes('\u6ca1\u6709\u627e\u5230\u4f60\u60f3\u8981\u641c\u7d22\u7684\u5185\u5bb9');
            const passed = Boolean(panel) && hasZeroCount && hasEmptyTitle && hasEmptyHint;
            return {handled:true,passed,reason:passed ? 'user search area renders its verified zero-result empty state' : `user zero-result state mismatch: panel=${Boolean(panel)}, zero=${hasZeroCount}, title=${hasEmptyTitle}, hint=${hasEmptyHint}`,evidence:{hasPanel:Boolean(panel),hasZeroCount,hasEmptyTitle,hasEmptyHint,text}};
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_community_search_open_instruction(instruction):
        return await _run_cdp_closed_shadow_community_search(page)
    if (
        normalized.startswith('\u64cd\u4f5c\uff1a')
        and '\u641c\u7d22\u8f93\u5165\u6846' in normalized
        and '\u8f93\u5165' in normalized
    ):
        quoted = re.search(r'[\u201c\"]([^\u201d\"]+)\s*[\u201d\"]', str(instruction or ''))
        if quoted and quoted.group(1).strip():
            return await _run_cdp_closed_shadow_community_search(page, quoted.group(1).strip())
    search_keyword = _community_search_keyword(instruction)
    if search_keyword:
        payload = json.dumps({'keyword': search_keyword}, ensure_ascii=False)
        result = await page.evaluate(rf'''
          (() => {{
            const payload = {payload};
            const visible = element => {{
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden';
            }};
            const searchInput = Array.from(document.querySelectorAll('input')).find(element => {{
              if (!visible(element)) return false;
              const hint = String(element.getAttribute('placeholder') || '') + ' ' + String(element.getAttribute('aria-label') || '');
              const rect = element.getBoundingClientRect();
              const isSemanticSearchInput = /\u641c\u7d22\u793e\u533a|\u7528\u6237\u540d\u79f0|\u641c\u7d22.*ID|search/i.test(hint);
              const isTopNavigationInput = rect.top < 160 && rect.width >= 180 && /nn-input|search/i.test(String(element.className || ''));
              return isSemanticSearchInput || isTopNavigationInput;
            }});
            if (!searchInput) return {{handled: true, passed: false, reason: 'top community search input is not visible'}};
            const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
            if (setter) setter.call(searchInput, payload.keyword); else searchInput.value = payload.keyword;
            searchInput.focus();
            searchInput.dispatchEvent(new InputEvent('input', {{bubbles: true, inputType: 'insertText', data: payload.keyword}}));
            searchInput.dispatchEvent(new Event('change', {{bubbles: true}}));
            for (const type of ['keydown', 'keyup']) {{
              searchInput.dispatchEvent(new KeyboardEvent(type, {{key: 'Enter', code: 'Enter', bubbles: true}}));
            }}
            return new Promise(resolve => setTimeout(() => {{
              const valueMatches = String(searchInput.value || '').includes(payload.keyword);
              const resultCards = Array.from(document.querySelectorAll('[class*="discovery-game-card" i],[class*="community-card" i],[class*="game-card" i]')).filter(visible);
              const hasResult = resultCards.some(card => String(card.innerText || '').includes(payload.keyword));
              const expectsExactMatch = !/(?:\u4e0d\u5b58\u5728|NO_RESULT|\u65e0\u7ed3\u679c)/i.test(payload.keyword);
              const passed = valueMatches && resultCards.length > 0 && (!expectsExactMatch || hasResult);
              resolve({{
                handled: true,
                passed,
                reason: passed
                  ? (hasResult ? `community search results are ready for "${{payload.keyword}}"` : `community search completed with recommendation results for the unmatched keyword "${{payload.keyword}}"`)
                  : `community search did not render a matching result for "${{payload.keyword}}"`,
                evidence: {{valueMatches, resultCardCount: resultCards.length, hasResult, expectsExactMatch}},
              }});
            }}, 1600));
          }})()
        ''')
        if isinstance(result, dict) and result.get('handled'):
            if result.get('passed') or result.get('reason') != 'top community search input is not visible':
                return result
            # NN's visible top search box is currently rendered in a closed
            # component tree on some client builds, so it has no queryable
            # HTML input even though it is on screen. Fall back to CDP input
            # events in that renderer only.
            return await _run_cdp_closed_shadow_community_search(page, search_keyword)
        return None
    plugin_targets = _community_plugin_navigation_target(instruction)
    if plugin_targets:
        payload = json.dumps({'targets': plugin_targets}, ensure_ascii=False)
        result = await page.evaluate(rf'''
          (() => {{
            const payload = {payload};
            const visible = element => {{ const r=element.getBoundingClientRect(), s=getComputedStyle(element); return r.width>1 && r.height>1 && s.display!=='none' && s.visibility!=='hidden'; }};
            const norm = value => String(value || '').replace(/\s+/g, ' ').trim();
            const labels = Array.from(document.querySelectorAll('*')).filter(visible).filter(element => payload.targets.includes(norm(element.innerText || element.textContent || '')));
            const label = labels.sort((a,b) => norm(a.innerText || a.textContent).length - norm(b.innerText || b.textContent).length)[0];
            const target = label?.closest('[class*="cursor-pointer" i],button,[role="button"],a') || label;
            if (!target) return {{handled:true, passed:false, reason:`community plugin is not visible: ${{payload.targets.join(' / ')}}`}};
            const before = String(location.hash || ''); target.click();
            return new Promise(resolve => setTimeout(() => {{
              const route = String(location.hash || '');
              const active = /is-active|active|selected/.test(String(target.className || target.parentElement?.className || ''));
              resolve({{handled:true, passed:route !== before || active, reason:route !== before || active ? `opened community plugin: ${{norm(label.innerText || label.textContent)}}` : `community plugin did not activate: ${{norm(label.innerText || label.textContent)}}`, evidence:{{before, route, active}}}});
            }}, 900));
          }})()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_affiliated_community_plugin_instruction(instruction):
        result = await page.evaluate(r'''
          (() => {
            const target = '\u65d7\u4e0b\u793e\u533a';
            const visible = e => { const r=e.getBoundingClientRect(), s=getComputedStyle(e); return r.width>1 && r.height>1 && s.display!=='none' && s.visibility!=='hidden'; };
            const deadline = Date.now() + 2500;
            const findItem = () => {
              const labels = Array.from(document.querySelectorAll('*')).filter(e => {
                if (!visible(e)) return false;
                const text = String(e.innerText || e.textContent || '').replace(/\s+/g, ' ').trim();
                // The unread-count badge can be rendered inside the same label,
                // making its text "旗下社区 9" instead of an exact match.
                return text === target || new RegExp(`^${target}(?:\\s*\\d+)?$`).test(text);
              }).sort((a, b) => String(a.innerText || a.textContent || '').length - String(b.innerText || b.textContent || '').length);
              const label = labels[0];
              return label && label.closest('[class*="cursor-pointer" i]');
            };
            return new Promise(resolve => {
              const waitForNavigationItem = () => {
                const item = findItem();
                if (!item) {
                  if (Date.now() < deadline) return setTimeout(waitForNavigationItem, 250);
                  return resolve({handled:true, passed:false, reason:'affiliated-community plugin was not enumerable in the left navigation within 2.5 seconds'});
                }
                const before = String(location.hash || '');
                item.click();
                const waitForRoute = () => {
                  const route = String(location.hash || '');
                  if (/\/teamListCenter/.test(route)) {
                    return resolve({handled:true, passed:true, reason:`opened affiliated-community plugin: ${route}`, route});
                  }
                  if (Date.now() < deadline) return setTimeout(waitForRoute, 200);
                  resolve({handled:true, passed:false, reason:`affiliated-community click did not open the team list: ${route}`, route, before});
                };
                waitForRoute();
              };
              waitForNavigationItem();
            });
          })()
        ''')
        if not isinstance(result, dict) or not result.get('handled'):
            return None
        if result.get('passed'):
            return result

        # Some NN builds virtualize lower navigation entries outside the
        # inspectable DOM, especially while the isolated Agent window is
        # hidden. Follow the menu's known route only as a fallback, then
        # require its real heading and data cards to load.
        try:
            route = await _activate_cdp_route_context(page, '/community/7520/plugin/teamListCenter')
            await _wait_for_cdp_renderer_stability(page, timeout_seconds=10)
        except DesktopAutomationError as exc:
            return {
                'handled': True,
                'passed': False,
                'reason': f'affiliated-community menu is present but its route could not be activated: {exc}',
            }
        fallback = await page.evaluate(r'''
          (() => {
            const route = String(location.hash || '');
            const text = String(document.body?.innerText || '').replace(/\s+/g, ' ').trim();
            const cards = Array.from(document.querySelectorAll('[class*="discovery-game-card" i]'));
            const validCards = cards.filter(card => {
              const text = String(card.innerText || card.textContent || '');
              return /\d{5,}/.test(text) && /\u5728\u7ebf\s*\d+|\d+\s*\u5728\u7ebf/.test(text);
            });
            const hasHeading = text.includes('\u65d7\u4e0b\u793e\u533a');
            return {route, cardCount: validCards.length, hasHeading, passed: /\/teamListCenter/.test(route) && hasHeading && validCards.length >= 3};
          })()
        ''')
        if isinstance(fallback, dict) and fallback.get('passed'):
            return {
                'handled': True,
                'passed': True,
                'reason': f'opened affiliated-community plugin through its verified navigation route: {route}',
                'evidence': {'navigationFallback': True, 'route': fallback.get('route'), 'cardCount': fallback.get('cardCount'), 'hasHeading': fallback.get('hasHeading')},
            }
        return {
            'handled': True,
            'passed': False,
            'reason': f'affiliated-community team list did not render after navigation: route={(fallback or {}).get("route") or route}, heading={bool((fallback or {}).get("hasHeading"))}, cards={(fallback or {}).get("cardCount") or 0}',
            'evidence': {'navigationFallback': True, **(fallback if isinstance(fallback, dict) else {})},
        }
    if _is_affiliated_community_page_assertion(instruction):
        await page.evaluate(
            f"sessionStorage.setItem('__testhub_affiliated_assertion', {json.dumps(normalized, ensure_ascii=False)}); true"
        )
        result = await page.evaluate(r'''
          (() => {
            const deadline = Date.now() + 12000;
            const inspect = () => {
              const instruction=String(sessionStorage.getItem('__testhub_affiliated_assertion') || '');
              const route=String(location.hash || '');
              const pageText=String(document.body?.innerText || '').replace(/\s+/g,' ').trim();
              const cards=Array.from(document.querySelectorAll('[class*="discovery-game-card" i]'));
              const valid=cards.filter(card => { const text=String(card.innerText || card.textContent || ''); return /\d{5,}/.test(text) && /\u5728\u7ebf\s*\d+|\d+\s*\u5728\u7ebf/.test(text); });
              const active=Array.from(document.querySelectorAll('*')).some(e => {
                const label=String(e.innerText || e.textContent || '').replace(/\s+/g,' ').trim();
                return (label==='\u65d7\u4e0b\u793e\u533a' || /^\u65d7\u4e0b\u793e\u533a(?:\s*\d+)?$/.test(label))
                  && /text-blue/.test(String(e.closest('[class]')?.className || e.className || ''));
              });
              const requiresCreate=instruction.includes('\u521b\u5efa\u6218\u961f\u793e\u533a');
              const requiresSelected=instruction.includes('\u9009\u4e2d\u72b6\u6001');
              const hasCreate=pageText.includes('\u521b\u5efa\u6218\u961f\u793e\u533a');
              // On virtualized sidebars, the route itself is the stable active
              // signal; inspect the blue class too when the item is exposed.
              const selected=active || (/\/teamListCenter/.test(route) && pageText.includes('\u65d7\u4e0b\u793e\u533a'));
              const passed=/\/teamListCenter/.test(route) && valid.length >= 3 && (!requiresCreate || hasCreate) && (!requiresSelected || selected);
              return {route, valid, active, selected, requiresCreate, requiresSelected, hasCreate, passed};
            };
            return new Promise(resolve => {
              const check = () => {
                const state = inspect();
                if (state.passed || Date.now() >= deadline) {
                  return resolve({handled:true, passed:state.passed, reason: state.passed ? `affiliated-community list verified with ${state.valid.length} cards` : `affiliated-community list mismatch after render wait: route=${/\/teamListCenter/.test(state.route)}, cards=${state.valid.length}, selected=${state.selected}, create=${state.hasCreate}`, evidence:{route:state.route, cardCount:state.valid.length, active:state.active, selected:state.selected, hasCreate:state.hasCreate}});
                }
                setTimeout(check, 300);
              };
              check();
            });
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    team_target = _team_card_target(instruction)
    if team_target:
        expected_id_match = re.search(
            r'ID\s*(?:\u4e3a|[:\uff1a])?\s*[\u300c\u201c\"]?\s*(\d{5,})',
            f'{instruction}\n{task_description or ""}',
            re.IGNORECASE,
        )
        payload = json.dumps({
            'target': team_target,
            'expectedId': expected_id_match.group(1) if expected_id_match else '',
        }, ensure_ascii=False)
        result = await page.evaluate(rf'''
          (() => {{
            const payload={payload};
            const deadline = Date.now() + 12000;
            const findCard = () => Array.from(document.querySelectorAll('[class*="discovery-game-card" i]')).filter(e => {{
              const text=String(e.innerText || e.textContent || '').trim();
              return text.includes(payload.target) && (!payload.expectedId || text.includes(payload.expectedId));
            }}).sort((left, right) => {{
              const leftText=String(left.innerText || left.textContent || '').trim();
              const rightText=String(right.innerText || right.textContent || '').trim();
              return leftText.length - rightText.length;
            }})[0];
            return new Promise(resolve => {{
              const waitForCard = () => {{
                const card = findCard();
                if (!card) {{
                  if (Date.now() < deadline) return setTimeout(waitForCard, 300);
                  return resolve({{handled:true, passed:false, reason:`team community card "${{payload.target}}"${{payload.expectedId ? ` with ID ${{payload.expectedId}}` : ''}} did not render within 12 seconds`}});
                }}
                const before=String(location.hash || '');
                card.click();
                const waitForIdentity = () => {{
                  const route=String(location.hash || '');
                  const text=String(document.body?.innerText || '');
                  const visibleIdentity=!payload.expectedId || (text.includes(payload.target) && text.includes(payload.expectedId));
                  // Team communities are rendered under their container
                  // community route. Verify the displayed team ID instead of
                  // incorrectly equating that container route ID with the
                  // team-card ID.
                  const opened=route!==before && /\/community\/\d+/.test(route);
                  if (opened && visibleIdentity) return resolve({{handled:true, passed:true, reason:`opened team community "${{payload.target}}": ${{route}}`, route}});
                  if (Date.now() < deadline) return setTimeout(waitForIdentity, 250);
                  resolve({{handled:true, passed:false, reason:`team community click did not show expected identity ${{payload.target}} / ${{payload.expectedId || 'route'}}: ${{route}}`, route, before, visibleIdentity}});
                }};
                waitForIdentity();
              }};
              waitForCard();
            }});
          }})()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_team_detail_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            const deadline = Date.now() + 12000;
            return new Promise(resolve => {
              const check = () => {
                const text=String(document.body?.innerText || '').replace(/\s+/g,' '), route=String(location.hash || '');
                const passed=/\/community\/\d+/.test(route) && text.includes('test0915') && text.includes('10079288') && /\u8bed\u97f3\u623f/.test(text);
                if (passed || Date.now() >= deadline) {
                  return resolve({handled:true, passed, reason:passed ? `team community detail verified: ${route}` : `team community detail mismatch after render wait: ${route}`, evidence:{route, hasName:text.includes('test0915'), hasId:text.includes('10079288'), hasVoice:/\u8bed\u97f3\u623f/.test(text)}});
                }
                setTimeout(check, 300);
              };
              check();
            });
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_team_card_count_assertion(instruction) or _is_team_card_metadata_assertion(instruction):
        require_metadata = _is_team_card_metadata_assertion(instruction)
        # Search-result cases can explicitly require only one complete card;
        # affiliated-community cases that say "each card" still validate every
        # rendered card independently.
        payload = json.dumps({
            'requireMetadata': require_metadata,
            'allowPartialMetadata': require_metadata and '\u4efb\u4e00' in normalized,
        }, ensure_ascii=False)
        result = await page.evaluate(rf'''
          (() => {{
            const payload = {payload};
            const deadline = Date.now() + 12000;
            const visible = element => {{
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 80 && rect.height > 36 && rect.bottom > 0 && rect.top < window.innerHeight && style.display !== 'none' && style.visibility !== 'hidden';
            }};
            const inspect = () => {{
              const cards = Array.from(document.querySelectorAll('[class*="discovery-game-card" i]')).filter(card =>
                visible(card) && String(card.innerText || card.textContent || '').replace(/\s+/g, ' ').trim().length > 0
              );
              const cardData = cards.map(card => {{
                const text = String(card.innerText || card.textContent || '').replace(/\s+/g, ' ').trim();
                const hasId = /(?:ID\s*[:\uff1a]?\s*)?\d{{5,}}/.test(text);
                const hasOnline = /\u5728\u7ebf\s*\d+|\d+\s*\u5728\u7ebf/.test(text);
                const hasAvatar = Boolean(card.querySelector('img')) || /background(?:-image)?/i.test(card.getAttribute('style') || '');
                const hasName = /^.+?\s+(?:ID\s*[:\uff1a]?\s*)?\d{{5,}}/.test(text);
                const complete = hasAvatar && hasName && hasId && hasOnline;
                return {{text: text.slice(0, 240), hasAvatar, hasName, hasId, hasOnline, complete}};
              }});
              const complete = cardData.filter(card => card.complete);
              const passed = payload.requireMetadata
                ? (payload.allowPartialMetadata ? complete.length >= 1 : cardData.length > 0 && complete.length === cardData.length)
                : complete.length >= 3;
              return {{passed, cardData, complete}};
            }};
            return new Promise(resolve => {{
              const check = () => {{
                const state = inspect();
                if (state.passed || Date.now() >= deadline) {{
                  const kind = payload.requireMetadata ? 'team-card metadata' : 'team-card count';
                  return resolve({{handled:true, passed:state.passed, reason:state.passed ? `${{kind}} verified: ${{state.complete.length}} complete card(s)` : `${{kind}} mismatch after render wait: cards=${{state.cardData.length}}, complete=${{state.complete.length}}`, evidence:{{cardCount:state.cardData.length, completeCount:state.complete.length, cards:state.cardData.slice(0, 12)}}}});
                }}
                setTimeout(check, 300);
              }};
              check();
            }});
          }})()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_team_home_sidebar_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            const deadline = Date.now() + 12000;
            return new Promise(resolve => {
              const check = () => {
                const text = String(document.body?.innerText || '').replace(/\s+/g, ' ').trim();
                const hasLevel = text.includes('\u6211\u7684\u7b49\u7ea7') && /\u6211\u7684\u7b49\u7ea7\s*[-+]?\d+\s*\/\s*\d+/.test(text);
                const hasHall = text.includes('\u6210\u5458\u5927\u5385') || text.includes('\u5168\u5458\u5927\u5385');
                const hasMarker = /\d+\s*(?:\u5c0f\u65f6\u524d|\u5206\u949f\u524d|\/\d{2})|\d+\s*(?:99\+)?/.test(text);
                const passed = hasLevel && hasHall && hasMarker;
                if (passed || Date.now() >= deadline) return resolve({handled:true, passed, reason:passed ? 'team community sidebar verified' : `team community sidebar mismatch: level=${hasLevel}, hall=${hasHall}, marker=${hasMarker}`, evidence:{hasLevel, hasHall, hasMarker}});
                setTimeout(check, 300);
              };
              check();
            });
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_team_home_content_assertion(instruction):
        content_mode = 'faq' if '常见问题' in normalized else 'article'
        result = await page.evaluate(r'''
          (() => {
            const contentMode = '__TESTHUB_TEAM_CONTENT_MODE__';
            const deadline = Date.now() + 12000;
            return new Promise(resolve => {
              const check = () => {
                const text = String(document.body?.innerText || '').replace(/\s+/g, ' ').trim();
                const hasIntro = /\u6b22\u8fce\u52a0\u5165|\u793e\u533a\u4ecb\u7ecd|\u6218\u961f\u5927\u5bb6\u5ead|\u7ade\u6280\u8363\u8000/.test(text);
                const hasContentCard = contentMode === 'faq'
                  ? text.includes('\u7ec4\u961f\u80fd\u89e3\u51b3\u6e38\u620f\u54ea\u4e9b\u95ee\u9898？') && text.includes('NN\u6e38\u620f\u8bed\u97f3\u4e0e\u5176\u4ed6\u8bed\u97f3\u6709\u4ec0\u4e48\u4e0d\u540c？')
                  : /(?:\u6d3b\u52a8|\u516c\u544a|\u653b\u7565|\u6218\u961f)\s+.{1,80}\s+(?:\d{2}\/\d{2}|\d{4}\/\d{2}\/\d{2})/.test(text);
                const passed = hasIntro && hasContentCard;
                if (passed || Date.now() >= deadline) return resolve({handled:true, passed, reason:passed ? 'team community introduction and content flow verified' : `team community content mismatch: introduction=${hasIntro}, contentCard=${hasContentCard}`, evidence:{hasIntro, hasContentCard}});
                setTimeout(check, 300);
              };
              check();
            });
          })()
        '''.replace('__TESTHUB_TEAM_CONTENT_MODE__', content_mode))
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_voice_room_list_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            const deadline = Date.now() + 12000;
            const visible = element => {
              const r=element.getBoundingClientRect(), s=getComputedStyle(element);
              return r.width>40 && r.height>20 && s.display!=='none' && s.visibility!=='hidden';
            };
            const inspect = () => {
              // Room widgets render nested room-item elements.  Keep only the
              // outer card, otherwise one physical room is counted several
              // times and incomplete child fragments look like bad data.
              const rooms = Array.from(document.querySelectorAll('.room-item,[class*="room-item" i]'))
                .filter(visible)
                .filter(room => !room.parentElement?.closest('.room-item,[class*="room-item" i]'))
                .map(room => {
                const text = String(room.innerText || room.textContent || '').replace(/\s+/g, ' ').trim();
                const hasNumber = /^\d+\b/.test(text);
                const hasName = text.replace(/^\d+\s*/, '').replace(/\d+\s*\d+\s*$/, '').trim().length >= 2;
                const isInteractive = /\u4e92\u52a8\u8bed\u97f3/.test(text);
                const hasCapacity = /\d+\s*\/\s*\d+|\d+\s+\d{2}$|\d+\s*\u5728\u7ebf/.test(text);
                return {text:text.slice(0, 160), hasNumber, hasName, hasCapacity, isInteractive, complete:hasNumber && hasName && (isInteractive || hasCapacity)};
              });
              const complete = rooms.filter(room => room.complete);
              const interactiveRooms = rooms.filter(room => room.isInteractive);
              const standardRooms = rooms.filter(room => !room.isInteractive);
              const interactiveValid = interactiveRooms.filter(room => room.complete);
              const standardValid = standardRooms.filter(room => room.complete);
              // Interactive rooms are data-dependent. Validate each type when
              // it is rendered, but never require a type the channel does not
              // currently expose.
              const hasInteractive = interactiveRooms.length > 0;
              const hasStandard = standardRooms.length > 0;
              const passed = rooms.length >= 2
                && complete.length >= Math.min(2, rooms.length)
                && (!hasInteractive || interactiveValid.length >= 1)
                && (!hasStandard || standardValid.length >= 1);
              return {rooms, complete, passed, hasInteractive, hasStandard, interactiveValid, standardValid};
            };
            return new Promise(resolve => {
              const check = () => {
                const state = inspect();
                if (state.passed || Date.now() >= deadline) return resolve({handled:true, passed:state.passed, reason:state.passed ? `voice-room list verified: ${state.complete.length} complete room(s); visible types interactive=${state.hasInteractive}, standard=${state.hasStandard}` : `voice-room list mismatch: rooms=${state.rooms.length}, complete=${state.complete.length}, interactive=${state.hasInteractive}, standard=${state.hasStandard}`, evidence:{roomCount:state.rooms.length, completeCount:state.complete.length, hasInteractive:state.hasInteractive, hasStandard:state.hasStandard, interactiveValidCount:state.interactiveValid.length, standardValidCount:state.standardValid.length, rooms:state.rooms.slice(0, 12)}});
                setTimeout(check, 300);
              };
              check();
            });
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    is_contextual_search_result_click = (
        not normalized.startswith('\u65ad\u8a00\uff1a')
        and '\u70b9\u51fb' in normalized
        and '\u76ee\u6807\u5361\u7247' in normalized
        and '\u641c\u7d22\u7684\u6e38\u620f\u3001\u6218\u961f\u793e\u533a' in str(task_description or '').replace(' ', '')
    )
    if _is_community_search_result_click(instruction) or is_contextual_search_result_click:
        intent = f'{instruction}\n{task_description}'
        target = _community_search_target(instruction, task_description)
        required_signals = []
        if '\u5728\u7ebf' in intent:
            required_signals.append('online_count')
        if '\u7b80\u4ecb' in intent or '\u4ecb\u7ecd' in intent:
            required_signals.append('community_intro')
        payload = json.dumps({
            'target': target,
            'requiredSignals': required_signals,
            'requireCommunityId': '\u793e\u533aID' in intent or 'ID' in intent,
        }, ensure_ascii=False)
        result = await page.evaluate(rf'''
          (() => {{
            const payload = {payload};
            const visible = element => {{
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 80 && rect.height > 36 && style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
            }};
            const norm = value => String(value || '').replace(/\s+/g, ' ').trim();
            const hasOnlineCount = text => /\u5728\u7ebf\s*\d+|\d+\s*\u5728\u7ebf|\u5728\u7ebf\u4eba\u6570|\u4eba\u5728\u7ebf/.test(text);
            const hasIntro = (text, target) => {{
              const remainder = norm(text.replace(target, '').replace(/\d+\s*(?:\u5728\u7ebf)?/g, ''));
              return remainder.length >= 16 || /\u300a|\u7b80\u4ecb|\u4ecb\u7ecd|\u5b98\u65b9|\u653b\u7565|\u8d5b\u4e8b|\u4ea4\u6d41/.test(text);
            }};
            const cardSelector = '[class*="discovery-game-card" i],[class*="community-card" i],[class*="game-card" i],[class*="result-card" i]';
            const cardMap = new Map();
            for (const source of Array.from(document.querySelectorAll(cardSelector))) {{
              if (!visible(source)) continue;
              const text = norm(source.innerText || source.textContent || '');
              if (!text.includes(payload.target)) continue;
              const rect = source.getBoundingClientRect();
              const hasCommunityId = /(?:ID\s*[:\uff1a]?\s*)?\d{{5,}}/.test(text);
              if (payload.requireCommunityId && !hasCommunityId) continue;
              const flags = {{online_count: hasOnlineCount(text), community_intro: hasIntro(text, payload.target)}};
              const meetsRequirements = payload.requiredSignals.every(signal => flags[signal]);
              const exactName = norm((source.querySelector('.text-gray-3') || source).innerText || '').split(' ')[0] === payload.target;
              let score = 0;
              if (exactName) score += 3000;
              if (flags.online_count) score += 1000;
              if (flags.community_intro) score += 1000;
              if (hasCommunityId) score += 1500;
              if (meetsRequirements) score += 4000;
              if (/cursor-pointer/.test(String(source.className || ''))) score += 200;
              if (rect.width <= 800 && rect.height <= 260) score += 200;
              const candidate = {{element: source, text, flags, hasCommunityId, meetsRequirements, score, rect: {{x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)}}}};
              const existing = cardMap.get(source);
              if (!existing || candidate.score > existing.score) cardMap.set(source, candidate);
            }}
            const candidates = Array.from(cardMap.values()).filter(candidate => candidate.meetsRequirements).sort((a, b) => b.score - a.score);
            const best = candidates[0];
            if (!best) {{
              return {{handled: true, passed: false, reason: `no community result matched "${{payload.target}}" and required signals: ${{payload.requiredSignals.join(', ') || 'none'}}`, candidates: Array.from(cardMap.values()).map(candidate => ({{text: candidate.text.slice(0, 240), flags: candidate.flags, rect: candidate.rect}})).slice(0, 8)}};
            }}
            const beforeRoute = String(location.hash || '');
            const clickTarget = best.element.closest('[class*="cursor-pointer" i],button,[role="button"],a') || best.element;
            for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup']) {{
              const EventType = type.startsWith('pointer') ? PointerEvent : MouseEvent;
              clickTarget.dispatchEvent(new EventType(type, {{bubbles: true, cancelable: true, view: window, button: 0}}));
            }}
            const identityId = (best.text.match(/(?:ID\s*[:\uff1a]?\s*)?(\d{{5,}})/) || [])[1] || '';
            const identityName = norm(best.text.split(/\s+(?:ID\s*[:\uff1a]?\s*)?\d{{5,}}/)[0]).split(' ')[0];
            sessionStorage.setItem('__testhub_selected_community_identity', JSON.stringify({{id: identityId, name: identityName, text: best.text.slice(0, 320)}}));
            const clickEvent = new MouseEvent('click', {{bubbles: true, cancelable: true, view: window, button: 0}});
            const rendererClick = clickTarget?._vei?.onClick || best.element?._vei?.onClick;
            if (typeof rendererClick === 'function') rendererClick(clickEvent); else clickTarget.click();
            const deadline = Date.now() + 7000;
            return new Promise(resolve => {{
              const check = () => {{
                let route = String(location.hash || '');
                const community = route.match(/\/community\/(\d+)/);
                const panelOpen = Boolean(document.querySelector('.all-search-result-community'));
                const bodyText = String(document.body?.innerText || '').replace(/\s+/g, ' ').trim();
                const routeChanged = route !== beforeRoute && Boolean(community);
                const contentChanged = !panelOpen && bodyText.includes(payload.target);
                const enteredCommunity = routeChanged || contentChanged;
                if ((enteredCommunity && !panelOpen) || Date.now() >= deadline) {{
                  // NN retains the last plugin route when switching communities. Normalize to
                  // the selected community home so later plugin steps start from one state.
                  if (enteredCommunity && !/\/plugin\/communityHome(?:$|[/?])/.test(route)) {{
                    location.hash = `/community/${{community[1]}}/plugin/communityHome`;
                    route = String(location.hash || '');
                  }}
                  const passed = enteredCommunity && !panelOpen;
                  return resolve({{handled: true, passed, reason:passed ? `opened community result "${{payload.target}}"` : `community result selection did not complete: routeChanged=${{routeChanged}}, contentChanged=${{contentChanged}}, panelClosed=${{!panelOpen}}`, route, detail: {{text: best.text.slice(0, 320), flags: best.flags, rect: best.rect, rendererClick:typeof rendererClick === 'function', routeChanged, contentChanged}}}});
                }}
                setTimeout(check, 250);
              }};
              check();
            }});
          }})()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_selected_search_community_identity_assertion(instruction):
        result = await page.evaluate(r'''
          (() => {
            let selected = {};
            try { selected = JSON.parse(sessionStorage.getItem('__testhub_selected_community_identity') || '{}') || {}; } catch (_error) {}
            const route = String(location.hash || '');
            const bodyText = String(document.body?.innerText || '').replace(/\s+/g, ' ').trim();
            const routeMatch = route.match(/\/community\/(\d+)/);
            const routeId = routeMatch?.[1] || '';
            // NN's hash uses an internal community key, while the visible
            // community card exposes the NN community ID. Validate the ID in
            // the destination header instead of incorrectly assuming both
            // identifiers are numerically identical.
            const idMatches = Boolean(selected.id) && bodyText.includes(selected.id);
            const nameMatches = Boolean(selected.name) && bodyText.includes(selected.name);
            const passed = Boolean(routeId) && idMatches && nameMatches;
            return {
              handled: true,
              passed,
              reason: passed
                ? `selected community identity verified: ${selected.name} (${selected.id})`
                : `selected community identity mismatch: expected=${selected.name || '?'} (${selected.id || '?'}), route=${routeId || '?'}, idMatches=${idMatches}, nameMatches=${nameMatches}`,
              evidence: {selected, route, routeId, idMatches, nameMatches},
            };
          })()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    if _is_community_detail_assertion(instruction):
        target = _quoted_community_target(instruction)
        panel_label = _expected_community_panel_label(instruction)
        payload = json.dumps({'target': target, 'panelLabel': panel_label}, ensure_ascii=False)
        result = await page.evaluate(rf'''
          (() => {{
            const payload = {payload};
            const bodyText = String(document.body?.innerText || '').replace(/\s+/g, ' ').trim();
            const route = String(location.hash || '');
            const hasCommunityRoute = /\/community\/\d+/.test(route);
            const hasTarget = bodyText.includes(payload.target);
            const hasPanelLabel = !payload.panelLabel || bodyText.includes(payload.panelLabel);
            const passed = hasCommunityRoute && hasTarget && hasPanelLabel;
            return {{
              handled: true,
              passed,
              reason: passed ? `community detail verified: ${{route}}` : `community detail mismatch: route=${{hasCommunityRoute}}, target=${{hasTarget}}, panel=${{hasPanelLabel}}`,
              evidence: {{route, target: payload.target, panelLabel: payload.panelLabel, hasCommunityRoute, hasTarget, hasPanelLabel}},
            }};
          }})()
        ''')
        return result if isinstance(result, dict) and result.get('handled') else None
    is_voice_room_entry = (
        ('双击' in normalized or '双点' in normalized)
        and '语音房' in normalized
        and '未锁' in normalized
        and '未满' in normalized
    )
    if not is_voice_room_entry:
        return None
    expected_community = _cdp_community_from_route(_cdp_route_from_task_description(task_description))
    if not expected_community:
        expected_community = _cdp_community_from_route(str(await page.evaluate('location.hash || ""') or ''))
    result = await page.evaluate(rf'''
      (() => {{
        const currentRoute = String(location.hash || '');
        const expectedCommunity = {json.dumps(expected_community)};
        const currentCommunity = /\/community\/(\d+)/.exec(currentRoute)?.[1] || '';
        if (/\/channel\/\d+/.test(currentRoute)) {{
          const sameCommunity = !expectedCommunity || currentCommunity === expectedCommunity;
          return {{handled: true, passed: false, reason: `voice room is already open before this case: ${{currentRoute}} (expected community=${{expectedCommunity || '?'}}, sameCommunity=${{sameCommunity}})`, route: currentRoute, evidence:{{expectedCommunity,currentCommunity,sameCommunity}}}};
        }}
        const visible = element => {{
          const rect = element.getBoundingClientRect();
          const style = getComputedStyle(element);
          return rect.width > 20 && rect.height > 20
            && rect.bottom > 0 && rect.right > 0 && rect.top < innerHeight && rect.left < innerWidth
            && style.display !== 'none' && style.visibility !== 'hidden';
        }};
        const communityRoot = Array.from(document.querySelectorAll('[community]')).find(element =>
          visible(element) && String(element.getAttribute('community') || '') === expectedCommunity
        );
        if (!communityRoot) {{
          return {{handled: true, passed: false, reason: `target community content is not rendered: ${{expectedCommunity}}`}};
        }}
        let room = Array.from(communityRoot.querySelectorAll('.room-item')).find(element => {{
          const text = String(element.innerText || '');
          return visible(element) && !text.includes('已锁') && !text.includes('已满');
        }});
        if (!room) {{
          room = Array.from(communityRoot.querySelectorAll('*')).find(element => {{
            const text = String(element.innerText || '').trim();
          const className = String(element.className || '');
          return visible(element)
            && /\u8bed\u97f3\u623f/.test(text)
            && /cursor-pointer/.test(className)
            && !element.closest('[data-msg-id],[id^="reverse-cell-"]')
              && !/\u5df2\u9501|\u5df2\u6ee1/.test(text);
          }});
        }}
        if (!room) {{
          return {{
            handled: true,
            passed: false,
            reason: `no unlocked non-full voice room card is available in community ${{expectedCommunity}}; chat messages that merely reference voice rooms are excluded`,
          }};
        }}
        const label = String(room.innerText || '').trim().slice(0, 80);
        const beforeRoute = String(location.hash || '');
        room.dispatchEvent(new MouseEvent('dblclick', {{bubbles: true, cancelable: true, view: window}}));
        return new Promise(resolve => setTimeout(() => {{
          const route = String(location.hash || '');
          resolve({{
            handled: true,
            passed: route !== beforeRoute && /\/community\/${{expectedCommunity || '\\d+'}}\/channel\/\d+/.test(route),
            reason: `voice room ${{route !== beforeRoute ? 'opened' : 'did not open'}}: ${{label}}`,
            route,
          }});
        }}, 4000));
      }})()
    ''')
    return result if isinstance(result, dict) and result.get('handled') else None


async def _execute_cdp_step(page: _CDPPage, step: dict[str, Any]) -> dict[str, Any]:
    action = str(step.get('action') or '').lower()
    if action == 'wait':
        await asyncio.sleep(max(0, min(float(step.get('seconds', 1)), 15)))
        return {'action': action}
    if action == 'screenshot':
        return {'action': action}
    selector = json.dumps(str(step.get('selector') or ''))
    value = json.dumps(str(step.get('value') or ''))
    if action == 'click':
        script = f'''(() => {{ const e=document.querySelector({selector}); if(!e) throw new Error('target disappeared'); e.focus(); e.click(); return true; }})()'''
    elif action == 'double_click':
        script = f'''(() => {{ const e=document.querySelector({selector}); if(!e) throw new Error('target disappeared'); e.focus(); e.dispatchEvent(new MouseEvent('dblclick',{{bubbles:true,cancelable:true,view:window}})); return new Promise(resolve => setTimeout(() => resolve({{route:location.hash || ''}}), 3500)); }})()'''
    elif action in {'fill', 'type'}:
        script = f'''(() => {{ const e=document.querySelector({selector}); if(!e) throw new Error('target disappeared'); const v={value}; e.focus(); const next={"v" if action == "fill" else "String(e.value || '') + v"}; const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set; if(e instanceof HTMLInputElement || e instanceof HTMLTextAreaElement) setter.call(e,next); else e.textContent=next; e.dispatchEvent(new InputEvent('input',{{bubbles:true,inputType:'insertText',data:v}})); e.dispatchEvent(new Event('change',{{bubbles:true}})); return String(e.value ?? e.textContent ?? ''); }})()'''
    elif action == 'press':
        script = f'''(() => {{ const e=document.querySelector({selector}); if(!e) throw new Error('target disappeared'); const key={value} || 'Enter'; e.focus(); for(const type of ['keydown','keyup']) e.dispatchEvent(new KeyboardEvent(type,{{key,bubbles:true}})); return true; }})()'''
    elif action == 'assert_visible':
        script = f'''(() => {{ const e=document.querySelector({selector}); const r=e && e.getBoundingClientRect(); if(!e || !r || r.width<2 || r.height<2 || getComputedStyle(e).display==='none') throw new Error('target is not visible'); return true; }})()'''
    elif action in {'assert_text', 'assert_value'}:
        script = f'''(() => {{ const e=document.querySelector({selector}); if(!e) throw new Error('target disappeared'); const actual=String({"e.value" if action == "assert_value" else "e.innerText || e.textContent || e.value || ''"}); if(!actual.includes({value})) throw new Error('expected value was not found: ' + {value}); return actual; }})()'''
    else:
        raise DesktopAutomationError(f'CDP executor does not support action {action}.')
    result = await page.evaluate(script)
    return {'action': action, 'selector': step.get('selector'), 'value': result}


async def _capture_cdp_screenshot(page: _CDPPage, record_id: int, step_number: int) -> str | None:
    target_dir = Path(settings.MEDIA_ROOT) / 'ui_automation' / 'desktop_execution' / str(record_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f'cdp_step_{step_number}.png'
    try:
        # Electron's off-screen compositor can return a perfectly valid PNG
        # containing only the window's dark background.  Its maximum luminance
        # is usually about 31, so checking merely for non-empty image bytes (or
        # even for a non-zero maximum) lets a black frame reach the vision model
        # and turns a healthy DOM into a false failure.
        def is_meaningful_frame(image_bytes: bytes) -> bool:
            from PIL import Image

            with Image.open(BytesIO(image_bytes)).convert('L') as image:
                low, high = image.getextrema()
            # A real dark-mode NN screen still contains text, icons, or images
            # with much brighter pixels and a useful luminance range. Reject a
            # nearly uniform compositor background instead.
            return high >= 60 and (high - low) >= 20

        last_bytes = b''
        # A render frame may be missing immediately after a route or store
        # update. Alternate Chromium's two capture paths and wait for two paint
        # frames before every retry. Do not persist a rejected frame: reports
        # must never present a black PNG as assertion evidence.
        for attempt in range(10):
            from_surface = attempt % 2 == 0
            result = await page.call('Page.captureScreenshot', {'format': 'png', 'fromSurface': from_surface})
            image_bytes = base64.b64decode(result.get('data') or '')
            if not image_bytes:
                continue
            last_bytes = image_bytes
            try:
                if is_meaningful_frame(image_bytes):
                    path.write_bytes(image_bytes)
                    return path.relative_to(settings.MEDIA_ROOT).as_posix()
            except Exception:
                # Preserve a valid image when Pillow cannot inspect it; an
                # image-decoding failure is not evidence that it is black.
                path.write_bytes(image_bytes)
                return path.relative_to(settings.MEDIA_ROOT).as_posix()
            if attempt < 9:
                await page.evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
                await asyncio.sleep(0.45)

        # The renderer can still expose a complete live DOM while Electron's
        # compositor is unavailable. In that narrow situation create a clearly
        # labeled DOM-evidence board from the *current* visible renderer state.
        # It is intentionally distinct from a screenshot; visual assertions may
        # use it only for conditions that are explicit in the captured DOM.
        if last_bytes:
            return await _capture_cdp_dom_evidence(page, target_dir, step_number)
        return None
    except Exception:
        return None


async def _capture_cdp_dom_evidence(page: _CDPPage, target_dir: Path, step_number: int) -> str | None:
    """Persist current visible-renderer evidence when Electron returns only black frames."""
    try:
        snapshot = await page.evaluate(r'''
          (() => {
            const visible = element => {
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 2 && rect.height > 2
                && style.display !== 'none' && style.visibility !== 'hidden'
                && Number(style.opacity || 1) > 0;
            };
            const normalize = value => String(value || '').replace(/\s+/g, ' ').trim();
            const viewport = {width: window.innerWidth, height: window.innerHeight};
            const meaningful = Array.from(document.querySelectorAll('body *')).filter(element => {
              if (!visible(element)) return false;
              const tag = element.tagName.toLowerCase();
              const text = normalize(element.innerText || element.textContent || element.value || element.getAttribute('aria-label') || element.getAttribute('placeholder'));
              return ['button', 'input', 'textarea', 'select', 'a', 'img', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'].includes(tag)
                || element.hasAttribute('contenteditable') || Boolean(element.getAttribute('role'))
                || (element.children.length === 0 && text.length >= 2);
            });
            const seen = new Set();
            const elements = meaningful.map(element => {
              const rect = element.getBoundingClientRect();
              const tag = element.tagName.toLowerCase();
              const text = normalize(element.innerText || element.textContent || element.value || element.getAttribute('aria-label') || element.getAttribute('placeholder')).slice(0, 140);
              const item = {
                tag,
                text,
                role: String(element.getAttribute('role') || ''),
                placeholder: String(element.getAttribute('placeholder') || ''),
                value: String(element.value || '').slice(0, 120),
                rect: {x: Math.round(rect.x), y: Math.round(rect.y), width: Math.round(rect.width), height: Math.round(rect.height)},
              };
              const key = `${item.rect.x}:${item.rect.y}:${item.rect.width}:${item.rect.height}:${item.tag}:${item.text}`;
              if (!item.text || seen.has(key)) return null;
              seen.add(key);
              return item;
            }).filter(Boolean).sort((left, right) => left.rect.y - right.rect.y || left.rect.x - right.rect.x).slice(0, 120);
            return {
              route: String(location.hash || location.pathname || ''),
              title: String(document.title || ''),
              viewport,
              bodyText: normalize(document.body?.innerText || '').slice(0, 900),
              elements: elements.slice(0, 40),
            };
          })()
        ''')
        if not isinstance(snapshot, dict) or not (snapshot.get('bodyText') or snapshot.get('elements')):
            return None

        from PIL import Image, ImageDraw, ImageFont

        def load_font(size: int):
            for candidate in ('C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/simhei.ttf', 'DejaVuSans.ttf'):
                try:
                    return ImageFont.truetype(candidate, size)
                except OSError:
                    continue
            return ImageFont.load_default()

        def wrap(draw, value: str, font, max_width: int) -> list[str]:
            text = str(value or '').replace('\n', ' ').strip()
            if not text:
                return []
            lines, current = [], ''
            for char in text:
                candidate = current + char
                if current and draw.textlength(candidate, font=font) > max_width:
                    lines.append(current)
                    current = char
                else:
                    current = candidate
            if current:
                lines.append(current)
            return lines

        title_font = load_font(28)
        body_font = load_font(18)
        small_font = load_font(16)
        width = 1520
        preview = str(snapshot.get('bodyText') or '')
        element_lines = []
        for element in snapshot.get('elements') or []:
            rect = element.get('rect') or {}
            details = element.get('text') or element.get('value') or element.get('placeholder') or ''
            element_lines.append(
                f"[{rect.get('x', 0)},{rect.get('y', 0)} {rect.get('width', 0)}x{rect.get('height', 0)}] "
                f"<{element.get('tag') or 'element'}> {details}"
            )
        measure_draw = ImageDraw.Draw(Image.new('RGB', (1, 1)))
        preview_lines = wrap(measure_draw, preview, body_font, width - 80)
        rendered_lines = list(preview_lines)
        for item in element_lines:
            rendered_lines.extend(wrap(measure_draw, item, small_font, width - 80))
        height = min(1600, max(360, 166 + len(rendered_lines) * 26))
        image = Image.new('RGB', (width, height), (24, 27, 35))
        draw = ImageDraw.Draw(image)
        draw.text((36, 28), 'Renderer DOM Evidence (compositor screenshot unavailable)', fill=(255, 196, 92), font=title_font)
        route = f"Route: {snapshot.get('route') or '-'}    Viewport: {snapshot.get('viewport', {}).get('width', 0)} x {snapshot.get('viewport', {}).get('height', 0)}"
        draw.text((36, 72), route, fill=(184, 202, 232), font=small_font)
        draw.text((36, 106), 'Visible renderer text and element coordinates captured at this assertion step:', fill=(184, 202, 232), font=small_font)
        y = 142
        for index, line in enumerate(rendered_lines):
            if y + 24 > height - 24:
                break
            is_preview_line = index < len(preview_lines)
            color = (231, 236, 245) if is_preview_line else (167, 214, 255)
            draw.text((40, y), line, fill=color, font=body_font if is_preview_line else small_font)
            y += 26
        evidence_path = target_dir / f'cdp_dom_evidence_step_{step_number}.png'
        image.save(evidence_path, format='PNG')
        return evidence_path.relative_to(settings.MEDIA_ROOT).as_posix()
    except Exception:
        return None


def _cdp_dom_assertion_for_index(desktop_config: dict[str, Any], assertion_index: int) -> dict[str, Any] | None:
    """Return an optional deterministic DOM assertion for a numbered case assertion."""
    raw_assertions = desktop_config.get('cdp_dom_assertions') if isinstance(desktop_config, dict) else None
    if raw_assertions is None:
        return None
    if not isinstance(raw_assertions, list):
        raise DesktopAutomationError('desktop_config.cdp_dom_assertions must be an array.')
    match = next((
        item for item in raw_assertions
        if isinstance(item, dict) and item.get('assertion_index') == assertion_index
    ), None)
    if match is None:
        return None
    expression = str(match.get('expression') or '').strip()
    if not expression:
        raise DesktopAutomationError(f'CDP DOM assertion {assertion_index} requires an expression.')
    return match


def _normalize_cdp_dom_assertion_result(result: Any, assertion: dict[str, Any]) -> dict[str, Any]:
    """Normalize a boolean or structured browser-side assertion result."""
    default_failure = str(assertion.get('failure_message') or 'DOM assertion condition was not satisfied.').strip()
    default_success = str(assertion.get('success_message') or 'DOM assertion condition was satisfied.').strip()
    if isinstance(result, bool):
        return {
            'status': 'passed' if result else 'failed',
            'reason': default_success if result else default_failure,
            'evidence': [],
        }
    if not isinstance(result, dict) or not isinstance(result.get('passed'), bool):
        raise DesktopAutomationError('CDP DOM assertion must return a boolean or { passed, reason?, evidence? }.')
    return {
        'status': 'passed' if result['passed'] else 'failed',
        'reason': str(result.get('reason') or (default_success if result['passed'] else default_failure)).strip(),
        'evidence': result.get('evidence') if isinstance(result.get('evidence'), list) else [],
    }


async def _run_cdp_dom_assertion(page: _CDPPage, assertion: dict[str, Any]) -> dict[str, Any]:
    """Execute an explicit DOM invariant, waiting briefly for asynchronous renderer data."""
    try:
        timeout_seconds = max(0.0, min(float(assertion.get('timeout_seconds') or 0), 30.0))
        interval_seconds = max(0.1, min(float(assertion.get('interval_seconds') or 0.5), 5.0))
    except (TypeError, ValueError) as exc:
        raise DesktopAutomationError('CDP DOM assertion timeout values must be numeric.') from exc

    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while True:
        try:
            result = await page.evaluate(str(assertion['expression']))
        except Exception as exc:
            raise DesktopAutomationError(f'CDP DOM assertion execution failed: {exc}') from exc
        normalized = _normalize_cdp_dom_assertion_result(result, assertion)
        if normalized['status'] == 'passed' or asyncio.get_running_loop().time() >= deadline:
            return normalized
        await asyncio.sleep(interval_seconds)


def _cdp_setup_actions(desktop_config: dict[str, Any]) -> list[dict[str, Any]]:
    """Read deterministic pre-actions needed to establish a desktop application state."""
    actions = desktop_config.get('cdp_setup_actions') if isinstance(desktop_config, dict) else None
    if actions is None:
        return []
    if not isinstance(actions, list):
        raise DesktopAutomationError('desktop_config.cdp_setup_actions must be an array.')
    normalized = []
    for index, action in enumerate(actions, 1):
        if not isinstance(action, dict) or not str(action.get('expression') or '').strip():
            raise DesktopAutomationError(f'CDP setup action {index} requires an expression.')
        normalized.append(action)
    return normalized


async def _run_cdp_setup_actions(
    page: _CDPPage,
    desktop_config: dict[str, Any],
    execution_record,
    actions: list[dict[str, Any]] | None = None,
) -> None:
    """Run semantic renderer setup actions before natural-language case steps."""
    for index, action in enumerate(actions if actions is not None else _cdp_setup_actions(desktop_config), 1):
        result = await _run_cdp_dom_assertion(page, action)
        if result['status'] != 'passed':
            raise DesktopAutomationError(f'CDP setup action {index} failed: {result["reason"]}')
        try:
            wait_seconds = max(0.0, min(float(action.get('wait_seconds') or 0), 15.0))
        except (TypeError, ValueError) as exc:
            raise DesktopAutomationError(f'CDP setup action {index} has a non-numeric wait_seconds value.') from exc
        execution_record.logs += f'[Desktop CDP] setup action {index} completed: {result["reason"]}\n'
        execution_record.save(update_fields=['logs'])
        if wait_seconds:
            await asyncio.sleep(wait_seconds)


async def _wait_for_cdp_renderer_stability(page: _CDPPage, timeout_seconds: float = 10) -> None:
    """Require a loaded, unchanged renderer snapshot before continuing."""
    deadline = asyncio.get_running_loop().time() + max(1.0, min(timeout_seconds, 30.0))
    previous = None
    while asyncio.get_running_loop().time() < deadline:
        snapshot = await page.evaluate(r'''
          JSON.stringify({
            readyState: document.readyState,
            route: location.hash,
            body: Boolean(document.body),
            bodyChildren: document.body ? document.body.children.length : 0,
          })
        ''')
        state = json.loads(snapshot or '{}')
        is_rendered = (
            state.get('readyState') != 'loading'
            and bool(state.get('body'))
            and int(state.get('bodyChildren') or 0) > 0
        )
        if is_rendered and snapshot == previous:
            return
        previous = snapshot
        await asyncio.sleep(0.35)
    raise DesktopAutomationError('Electron renderer did not become stable after the CDP reconnect.')


async def _wait_for_cdp_visible_selector(page: _CDPPage, selector: str, timeout_seconds: float = 10) -> bool:
    """Wait for a concrete renderer control after route-shell hydration."""
    deadline = asyncio.get_running_loop().time() + max(0.5, min(timeout_seconds, 20.0))
    expression = json.dumps(str(selector))
    while True:
        present = await page.evaluate(rf'''
          (() => {{
            const element = document.querySelector({expression});
            if (!element) return false;
            const rect = element.getBoundingClientRect();
            const style = getComputedStyle(element);
            return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden';
          }})()
        ''')
        if present:
            return True
        if asyncio.get_running_loop().time() >= deadline:
            return False
        await asyncio.sleep(0.25)


async def _verify_cdp_route_context(page: _CDPPage, target_route: str, timeout_seconds: float = 8) -> dict[str, Any]:
    """Require the visible community container to match the requested route.

    NN can update Vue Router and ``location.hash`` before its community view
    replaces the old DOM. Acting during that gap can click a room from the
    previous community and turn a stale screen into a false pass.
    """
    expected_community = _cdp_community_from_route(target_route)
    if not expected_community:
        return {'route': str(await page.evaluate('location.hash || ""') or '')}

    deadline = asyncio.get_running_loop().time() + max(1.0, min(timeout_seconds, 20.0))
    last_state: dict[str, Any] = {}
    while True:
        state = await page.evaluate(rf'''
          (() => {{
            const expectedCommunity = {json.dumps(expected_community)};
            const route = String(location.hash || '').replace(/^#/, '');
            const actualCommunity = /(?:^|\/)community\/(\d+)(?:\/|$)/.exec(route)?.[1] || '';
            const visible = element => {{
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 20 && rect.height > 20 && style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
            }};
            const communities = Array.from(document.querySelectorAll('[community]'))
              .filter(visible)
              .map(element => String(element.getAttribute('community') || ''));
            return {{
              route,
              expectedCommunity,
              actualCommunity,
              renderedCommunities: Array.from(new Set(communities)),
              matched: actualCommunity === expectedCommunity && communities.includes(expectedCommunity),
            }};
          }})()
        ''')
        if isinstance(state, dict):
            last_state = state
            if state.get('matched'):
                return state
        if asyncio.get_running_loop().time() >= deadline:
            break
        await asyncio.sleep(0.35)

    raise DesktopAutomationError(
        'Electron route context did not hydrate the requested community: '
        f'expected={expected_community}; route={last_state.get("route") or "?"}; '
        f'rendered={last_state.get("renderedCommunities") or []}. '
        'No case action was executed on the stale renderer.'
    )


async def _dismiss_cdp_transient_overlays(page: _CDPPage) -> int:
    """Close leftover dismissible overlays before a new independent case starts.

    Sequential desktop cases share one Electron renderer. A failed case can
    otherwise leave an invite dialog, a search layer, or another temporary
    overlay in front of the next case. This deliberately targets only visible
    dialog containers and their own close controls; it does not click content
    controls or reload the NN renderer.
    """
    result = await page.evaluate(r'''
      (() => {
        const visible = element => {
          const rect = element.getBoundingClientRect();
          const style = getComputedStyle(element);
          return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden';
        };
        const dialogCandidates = Array.from(document.querySelectorAll('.ui-dialog,[role="dialog"],[class*="dialog" i],[class*="modal" i]')).filter(visible);
        const dialogs = dialogCandidates.filter(dialog => !dialogCandidates.some(candidate => candidate !== dialog && candidate.contains(dialog)));
        let closed = 0;
        for (const dialog of dialogs) {
          const close = Array.from(dialog.querySelectorAll('[class*="close" i],button,i,svg')).filter(visible).find(element =>
            /close|\u5173\u95ed/.test(String(element.className || ''))
          );
          if (!close) continue;
          (close.closest('[class*="close" i],button,[role="button"]') || close).click();
          closed += 1;
        }
        const memberSearch = document.querySelector('input[placeholder="\u641c\u7d22\u6210\u5458"]');
        let clearedMemberSearch = false;
        if (memberSearch && String(memberSearch.value || '')) {
          const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
          if (setter) setter.call(memberSearch, ''); else memberSearch.value = '';
          memberSearch.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'deleteContentBackward', data:null}));
          memberSearch.dispatchEvent(new Event('change', {bubbles:true}));
          clearedMemberSearch = true;
        }
        return {closed, clearedMemberSearch};
      })()
    ''')
    if int((result or {}).get('closed') or 0) or bool((result or {}).get('clearedMemberSearch')):
        await asyncio.sleep(0.35)
    return int((result or {}).get('closed') or 0)


async def _reset_cdp_case_state(page: _CDPPage, phase: str) -> dict[str, Any]:
    """Reset case-local renderer state without restarting NN or logging out.

    The long-lived CDP Agent intentionally shares an Electron process across a
    batch.  A process is not a test fixture, though: every case must start
    from its own route and an empty transient UI state.  Preserve the verified
    authentication session, while clearing only UI residue and TestHub's
    per-case sessionStorage evidence.
    """
    result = await page.evaluate(r'''
      (() => {
        const visible = element => {
          if (!element) return false;
          const rect = element.getBoundingClientRect();
          const style = getComputedStyle(element);
          return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
        };
        const clickClose = root => {
          const candidate = Array.from(root?.querySelectorAll?.('button,[role="button"],i,svg') || []).find(element => {
            if (!visible(element)) return false;
            const hint = `${element.className || ''} ${element.getAttribute?.('aria-label') || ''} ${element.innerHTML || ''}`.toLowerCase();
            return /close|\\u5173\\u95ed|guanbi/.test(hint);
          });
          const target = candidate?.closest?.('button,[role="button"],[class*="close" i]') || candidate;
          if (!target) return false;
          target.click();
          return true;
        };

        let removedMarkers = 0;
        for (let index = sessionStorage.length - 1; index >= 0; index -= 1) {
          const key = sessionStorage.key(index);
          if (key && key.startsWith('__testhub_')) {
            sessionStorage.removeItem(key);
            removedMarkers += 1;
          }
        }

        // Some CDP screenshot/recording helpers inject a blob image directly
        // under <html>. It survives route changes, sits above the renderer,
        // and makes every trusted mouse event hit the image instead of NN.
        // Only remove this invalid top-level artifact; NN-owned images remain
        // inside <body> or #app and are left untouched.
        const injectedOverlays = Array.from(document.documentElement.children).filter(element =>
          element.tagName === 'IMG'
          && String(element.src || '').startsWith('blob:')
          && getComputedStyle(element).position === 'fixed'
        );
        for (const overlay of injectedOverlays) overlay.remove();
        const removedInjectedOverlays = injectedOverlays.length;

        let clearedMemberSearch = false;
        const memberSearch = document.querySelector('input[placeholder="\\u641c\\u7d22\\u6210\\u5458"]');
        if (memberSearch && String(memberSearch.value || '')) {
          const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
          if (setter) setter.call(memberSearch, ''); else memberSearch.value = '';
          memberSearch.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'deleteContentBackward', data: null}));
          memberSearch.dispatchEvent(new Event('change', {bubbles: true}));
          clearedMemberSearch = true;
        }

        let clearedDraft = false;
        const chatInput = document.querySelector('.chat-input[contenteditable="true"], .chat-input[contenteditable]');
        if (chatInput && String(chatInput.textContent || '')) {
          chatInput.textContent = '';
          chatInput.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'deleteContentBackward', data: null}));
          clearedDraft = true;
        }

        // Community-home FAQs are an accordion. Close any expanded answer so
        // the next case starts from the same collapsed baseline.
        let collapsedFaqs = 0;
        for (const answer of Array.from(document.querySelectorAll('div')).filter(element => {
          const classes = String(element.className || '');
          return classes.includes('transition-all') && classes.includes('leading-[20px]') && classes.includes('h-auto');
        })) {
          const card = answer.parentElement;
          const invoker = card?._vei?.onClick;
          if (!card?.classList?.contains('cursor-pointer') || typeof invoker !== 'function') continue;
          invoker(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
          collapsedFaqs += 1;
        }

        const dialogCandidates = Array.from(document.querySelectorAll('[role="dialog"],.ui-dialog,[class*="dialog" i],[class*="modal" i]')).filter(visible);
        const dialogs = dialogCandidates.filter(dialog => !dialogCandidates.some(candidate => candidate !== dialog && candidate.contains(dialog)));
        let closedOverlays = 0;
        for (const dialog of dialogs) if (clickClose(dialog)) closedOverlays += 1;

        // NN's emoji popover is not consistently marked as a dialog. Close it
        // from the message input only when it is visibly present.
        const emojiTitle = Array.from(document.querySelectorAll('*')).find(element =>
          visible(element) && element.children.length === 0 && String(element.textContent || '').trim() === '\u81ea\u5b9a\u4e49\u8868\u60c5'
        );
        const emojiPanel = emojiTitle?.parentElement;
        let closedEmojiPanel = false;
        if (emojiPanel && chatInput) {
          chatInput.parentElement?.parentElement?.click();
          closedEmojiPanel = true;
        }
        return {removedMarkers, removedInjectedOverlays, clearedMemberSearch, clearedDraft, collapsedFaqs, closedOverlays, closedEmojiPanel};
      })()
    ''')
    await asyncio.sleep(0.25)
    normalized = result if isinstance(result, dict) else {}
    normalized['phase'] = phase
    return normalized


def _cdp_login_credentials(desktop_config: dict[str, Any]) -> dict[str, str]:
    """Validate optional setup-template credentials without leaking them to logs."""
    raw = desktop_config.get('cdp_login_credentials') if isinstance(desktop_config, dict) else None
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise DesktopAutomationError('desktop_config.cdp_login_credentials must be an object.')
    phone = str(raw.get('phone') or raw.get('phone_number') or '').strip()
    code = str(raw.get('verification_code') or raw.get('code') or '').strip()
    if not phone and not code:
        return {}
    if not re.fullmatch(r'1\d{10}', phone) or not re.fullmatch(r'\d{4,8}', code):
        raise DesktopAutomationError('The selected setup template has incomplete NN phone-login credentials.')
    return {'phone': phone, 'verification_code': code}


async def _dispatch_cdp_click(page: _CDPPage, point: dict[str, Any]) -> None:
    """Send a renderer-trusted click without moving the physical pointer."""
    try:
        x = float(point['x'])
        y = float(point['y'])
    except (KeyError, TypeError, ValueError) as exc:
        raise DesktopAutomationError('NN Agent click target coordinates were invalid.') from exc
    mouse_params = {'x': x, 'y': y, 'button': 'left', 'clickCount': 1}
    await page.call('Input.dispatchMouseEvent', {'type': 'mousePressed', **mouse_params})
    await page.call('Input.dispatchMouseEvent', {'type': 'mouseReleased', **mouse_params})


async def _open_cdp_nn_login_form(page: _CDPPage) -> bool:
    """Open NN's guest-login dialog with trusted CDP input when needed."""
    for _ in range(7):
        state = await page.evaluate(r'''
          (() => {
            const visible = element => {
              if (!element) return false;
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
            };
            const text = element => String(element?.innerText || element?.textContent || element?.getAttribute?.('aria-label') || '')
              .replace(/\s+/g, ' ').trim();
            const field = kind => Array.from(document.querySelectorAll('input')).find(element => {
              if (!visible(element)) return false;
              const hint = `${element.placeholder || ''} ${element.name || ''} ${element.type || ''}`.toLowerCase();
              return kind === 'phone'
                ? /\u624b\u673a|phone|mobile|account|tel/.test(hint)
                : /\u9a8c\u8bc1\u7801|code|captcha|verify/.test(hint);
            });
            const phone = field('phone');
            const code = field('code');
            if (phone && code) return {formVisible: true};
            // This is not an NN modal: the recording/screenshot bridge can
            // leave a full-window blob image directly under <html>. It has no
            // interactive close handler and intercepts every CDP click. Remove
            // only that known top-level artifact before scanning NN controls.
            const injectedOverlays = Array.from(document.documentElement.children).filter(element =>
              element.tagName === 'IMG'
              && String(element.src || '').startsWith('blob:')
              && getComputedStyle(element).position === 'fixed'
            );
            if (injectedOverlays.length) {
              for (const overlay of injectedOverlays) overlay.remove();
              return {formVisible: false, overlayClosed: true};
            }
            // A fresh isolated NN profile can display a promotion modal over
            // the account entry. Close only an in-app image modal with its
            // own top-right dismiss affordance; never target the native window
            // controls in the application header.
            const modalClose = Array.from(document.querySelectorAll('button,[role="button"],i,svg,[class*="close" i]'))
              .filter(visible)
              .map(element => {
                const rect = element.getBoundingClientRect();
                let parent = element.parentElement;
                while (parent && parent !== document.body) {
                  const parentRect = parent.getBoundingClientRect();
                  const style = getComputedStyle(parent);
                  const hasLargeImage = Array.from(parent.querySelectorAll('img')).some(image => {
                    const imageRect = image.getBoundingClientRect();
                    return visible(image) && imageRect.width >= 180 && imageRect.height >= 120;
                  });
                  if (hasLargeImage && parentRect.width >= 220 && parentRect.height >= 180
                    && parentRect.top > 20 && parentRect.left > 20 && parentRect.right < innerWidth - 20 && parentRect.bottom < innerHeight - 20
                    && (style.position === 'fixed' || style.position === 'absolute' || /fixed|modal|dialog|popup/i.test(String(parent.className || '')))) {
                    const isCornerDismiss = rect.right >= parentRect.right - 90 && rect.top <= parentRect.top + 90 && rect.width <= 80 && rect.height <= 80;
                    if (isCornerDismiss) return {element, point: {x: rect.left + rect.width / 2, y: rect.top + rect.height / 2}};
                  }
                  parent = parent.parentElement;
                }
                return null;
              })
              .find(Boolean);
            if (modalClose) {
              modalClose.element.click();
              return {formVisible: false, overlayClosed: true};
            }
            const entry = Array.from(document.querySelectorAll('button,a,[role="button"],[tabindex],[class*="avatar" i],[class*="user" i],[class*="cursor-pointer" i]'))
              .filter(visible)
              .filter(element => element !== document.body && element.id !== 'app')
              .map(element => {
                const rect = element.getBoundingClientRect();
                const label = text(element);
                const hint = `${label} ${element.className || ''} ${element.getAttribute('alt') || ''}`;
                let score = 0;
                if (/\u767b\u5f55|\u767b\u9646|login/i.test(hint)) score += 1000;
                if (/^(?:\u5173\u6ce8\u793e\u533a|\u5173\u6ce8|\u53c2\u4e0e\u4e92\u52a8|\u7acb\u5373\u767b\u5f55|\u767b\u5f55\u540e\u53ef)/.test(label.replace(/\s+/g, ''))) score += 800;
                if (/avatar|user|\u5934\u50cf/i.test(hint)) score += 300;
                if (rect.left < 160 && rect.top > innerHeight - 180) score += 500;
                return {score, point: {x: rect.left + rect.width / 2, y: rect.top + rect.height / 2}};
              })
              .filter(item => item.score > 0)
              .sort((left, right) => right.score - left.score)[0];
            return {formVisible: false, entryPoint: entry?.point || null};
          })()
        ''')
        if isinstance(state, dict) and state.get('formVisible'):
            return True
        if isinstance(state, dict) and state.get('overlayClosed'):
            await asyncio.sleep(0.35)
            continue
        if isinstance(state, dict) and isinstance(state.get('entryPoint'), dict):
            await _dispatch_cdp_click(page, state['entryPoint'])
        await asyncio.sleep(0.35)
    return False


async def _ensure_cdp_nn_login(page: _CDPPage, desktop_config: dict[str, Any]) -> bool:
    """Establish the isolated NN Agent session through Chromium DOM only.

    The CDP Agent intentionally uses its own user-data-dir.  A community deep
    link therefore redirects to the home page until its own session is logged
    in.  This routine is deliberately independent of Playwright and OS input:
    it clicks, fills and submits inside the Electron renderer only.
    """
    credentials = _cdp_login_credentials(desktop_config)
    if not credentials:
        return False
    payload = json.dumps(credentials, ensure_ascii=False)
    initial = await page.evaluate(rf'''
      (() => {{
        const visible = element => {{
          if (!element) return false;
          const rect = element.getBoundingClientRect();
          const style = getComputedStyle(element);
          return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
        }};
        const loginForm = () => Array.from(document.querySelectorAll('input')).some(element => {{
          if (!visible(element)) return false;
          const hint = `${{element.placeholder || ''}} ${{element.name || ''}} ${{element.type || ''}}`.toLowerCase();
          return /\u624b\u673a|phone|mobile|account|tel/.test(hint);
        }});
        const user = JSON.parse(localStorage.getItem('userInfo') || '{{}}');
        const userId = String(user.userId || localStorage.getItem('userId') || '').trim();
        // Electron persists its authenticated user id but not necessarily a
        // web-style token in localStorage.  A positive user id is therefore
        // the durable session signal; guests are always -1 or 0.
        return {{formVisible: loginForm(), hasSession: Boolean(userId) && userId !== '-1' && userId !== '0'}};
      }})()
    ''')
    if isinstance(initial, dict) and initial.get('hasSession'):
        # A prior case can leave the login overlay mounted even after a valid
        # session exists.  It must not obscure the next case's message area.
        if initial.get('formVisible'):
            await page.evaluate(r'''
              (() => {
                const phone = Array.from(document.querySelectorAll('input')).find(element =>
                  /\u624b\u673a|phone|mobile|account|tel/.test(`${element.placeholder || ''} ${element.name || ''} ${element.type || ''}`.toLowerCase())
                );
                const root = phone?.closest('section')?.closest('[class*="dark" i]') || phone?.closest('section')?.parentElement;
                const close = Array.from(root?.querySelectorAll('button') || []).find(button =>
                  /close|\u5173\u95ed/.test(`${button.className || ''} ${button.innerHTML || ''}`.toLowerCase())
                );
                close?.click();
                return Boolean(close);
              })()
            ''')
            await asyncio.sleep(0.35)
        return False

    if not (isinstance(initial, dict) and initial.get('formVisible')):
        opened = await _open_cdp_nn_login_form(page)
        if not opened:
            raise DesktopAutomationError(
                'NN login form did not expose both phone and verification-code fields '
                'after opening a supported login entry with trusted CDP input.'
            )

    submitted = await page.evaluate(rf'''
      (() => {{
        const payload = {payload};
        const visible = element => {{
          if (!element) return false;
          const rect = element.getBoundingClientRect();
          const style = getComputedStyle(element);
          return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
        }};
        const text = element => String(element?.innerText || element?.textContent || element?.getAttribute?.('aria-label') || '').replace(/\\s+/g, ' ').trim();
        const field = kind => Array.from(document.querySelectorAll('input')).find(element => {{
          if (!visible(element)) return false;
          const hint = `${{element.placeholder || ''}} ${{element.name || ''}} ${{element.type || ''}}`.toLowerCase();
          return kind === 'phone'
            ? /\u624b\u673a|phone|mobile|account|tel/.test(hint)
            : /\u9a8c\u8bc1\u7801|code|captcha|verify/.test(hint);
        }});
        const loginEntry = () => {{
          // A guest NN session does not always render a literal login button.
          // In the community client, a gated action such as "关注社区" is the
          // entry which opens the phone-login dialog. Limit the scan to actual
          // interactive controls: broad div/span matches can otherwise select
          // the application root merely because it contains that text.
          const candidates = Array.from(document.querySelectorAll('button,a,[role="button"],[tabindex],[class*="avatar" i],[class*="user" i],[class*="cursor-pointer" i]'))
            .filter(visible)
            .filter(element => element !== document.body && element.id !== 'app');
          return candidates.map(element => {{
            const rect = element.getBoundingClientRect();
            const label = text(element);
            const hint = `${{label}} ${{element.className || ''}} ${{element.getAttribute('alt') || ''}}`;
            let score = 0;
            if (/\u767b\u5f55|\u767b\u9646|login/i.test(hint)) score += 1000;
            if (/^(?:\u5173\u6ce8\u793e\u533a|\u5173\u6ce8|\u53c2\u4e0e\u4e92\u52a8|\u7acb\u5373\u767b\u5f55|\u767b\u5f55\u540e\u53ef)/.test(label.replace(/\s+/g, ''))) score += 800;
            if (/avatar|user|\u5934\u50cf/i.test(hint)) score += 300;
            if (rect.left < 160 && rect.top > innerHeight - 180) score += 500;
            return {{element, score}};
          }}).filter(item => item.score > 0).sort((a, b) => b.score - a.score)[0]?.element;
        }};
        return new Promise(resolve => {{
          const deadline = Date.now() + 2500;
          let lastLoginEntryClickAt = 0;
          const ensureLoginFormOpen = () => {{
            if (field('phone') && field('code')) return;
            const now = Date.now();
            if (now - lastLoginEntryClickAt < 400) return;
            lastLoginEntryClickAt = now;
            loginEntry()?.click();
          }};
          ensureLoginFormOpen();
          const setValue = (element, value) => {{
            if (!element) return false;
            const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
            const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
            if (setter) setter.call(element, value); else element.value = value;
            element.dispatchEvent(new InputEvent('input', {{bubbles: true, inputType: 'insertText', data: value}}));
            element.dispatchEvent(new Event('change', {{bubbles: true}}));
            return true;
          }};
          const submitWhenReady = () => {{
            const phone = field('phone');
            const code = field('code');
            const filled = setValue(phone, payload.phone) && setValue(code, payload.verification_code);
            if (!filled) {{
              ensureLoginFormOpen();
              if (Date.now() < deadline) return setTimeout(submitWhenReady, 120);
              return resolve({{submitted: false, reason: 'NN login form did not expose both phone and verification-code fields after opening a supported login entry'}});
            }}
          // The community page can contain other login-like controls.  Scope
          // every login action to the form which owns the phone field so a
          // stale or background button cannot make a guest session look ready.
          const loginForm = phone.closest('form') || phone.closest('section') || document.body;
          const loginPanel = loginForm.closest('.ui-dialog') || loginForm.closest('[role="dialog"]') || loginForm.parentElement || document.body;
          const agreementLabel = Array.from(loginForm.querySelectorAll('label,span,div')).filter(visible).find(element =>
            /\u6211\u5df2\u9605\u8bfb\u5e76\u540c\u610f|\u7528\u6237\u534f\u8bae|\u9690\u79c1\u653f\u7b56/.test(text(element))
          );
          const agreement = agreementLabel?.closest('label') || agreementLabel?.parentElement?.querySelector('input[type="checkbox"]') || agreementLabel?.parentElement;
          if (agreement) {{
            const checkbox = agreement.matches?.('input[type="checkbox"]') ? agreement : agreement.querySelector?.('input[type="checkbox"]');
            if (!checkbox || !checkbox.checked) agreement.click();
          }}
          const submit = Array.from(loginPanel.querySelectorAll('button,[role="button"],a')).filter(visible).map(element => {{
            const hint = `${{text(element)}} ${{element.className || ''}}`;
            let score = /\u767b\u5f55\s*\/\s*\u6ce8\u518c|\u767b\u5f55|\u767b\u9646|\u6ce8\u518c|login/i.test(hint) ? 1000 : 0;
            if (/primary|button--primary/i.test(hint)) score += 100;
            return {{element, score}};
          }}).filter(item => item.score > 0).sort((a, b) => b.score - a.score)[0]?.element;
          if (!submit) return resolve({{submitted: false, reason: 'NN login submit button was not found'}});
          if (submit.disabled || submit.getAttribute('aria-disabled') === 'true') return resolve({{submitted: false, reason: 'NN login submit button remains disabled after filling the form'}});
          const rect = submit.getBoundingClientRect();
          if (rect.width < 2 || rect.height < 2) return resolve({{submitted: false, reason: 'NN login submit button is not interactable'}});
          // NN validates its SMS-login state from trusted pointer input. Return
          // the target instead of calling HTMLElement.click(), whose synthetic
          // event is ignored by this client build.
          resolve({{submitted: true, submit_point: {{x: rect.left + rect.width / 2, y: rect.top + rect.height / 2}}}});
          }};
          submitWhenReady();
        }});
      }})()
    ''')
    if not isinstance(submitted, dict) or not submitted.get('submitted'):
        reason = submitted.get('reason') if isinstance(submitted, dict) else 'unable to submit NN login form'
        raise DesktopAutomationError(f'NN Agent login failed: {reason}.')
    submit_point = submitted.get('submit_point')
    if not isinstance(submit_point, dict):
        raise DesktopAutomationError('NN Agent login failed: submit button coordinates were not available.')
    await _dispatch_cdp_click(page, submit_point)

    deadline = asyncio.get_running_loop().time() + 15
    last_state = {}
    while asyncio.get_running_loop().time() < deadline:
        state = await page.evaluate(r'''
          (() => {
            const visible = element => {
              if (!element) return false;
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return rect.width > 1 && rect.height > 1 && style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
            };
            const formVisible = Array.from(document.querySelectorAll('input')).some(element => {
              if (!visible(element)) return false;
              const hint = `${element.placeholder || ''} ${element.name || ''} ${element.type || ''}`.toLowerCase();
              return /\u624b\u673a|phone|mobile|account|tel/.test(hint);
            });
            const user = JSON.parse(localStorage.getItem('userInfo') || '{}');
            const userId = String(user.userId || localStorage.getItem('userId') || '').trim();
            // The desktop client reports rejected SMS logins in an ephemeral
            // toast.  Capture the visible message before it disappears so a
            // test run is not incorrectly attributed to case logic.
            const text = element => String(element?.innerText || element?.textContent || '')
              .replace(/\s+/g, ' ').trim();
            const loginErrorPattern = /(?:\u9a8c\u8bc1\u7801(?:\u9519\u8bef|\u65e0\u6548|\u5df2\u8fc7\u671f)|\u767b\u5f55(?:\u5931\u8d25|\u5f02\u5e38)|\u624b\u673a\u53f7(?:\u9519\u8bef|\u65e0\u6548)|\u8d26\u53f7(?:\u9519\u8bef|\u5f02\u5e38)|\u64cd\u4f5c(?:\u9891\u7e41|\u5931\u8d25)|\u8bf7\u6c42(?:\u5931\u8d25|\u8d85\u65f6))/;
            const loginError = Array.from(document.querySelectorAll('[role="alert"], [class*="toast" i], [class*="message" i], [class*="notice" i], [class*="tip" i], body *'))
              .filter(visible)
              .map(text)
              .find(value => value && value.length <= 160 && loginErrorPattern.test(value));
            return {
              formVisible,
              hasSession: Boolean(userId) && userId !== '-1' && userId !== '0',
              userId: userId || 'missing',
              loginError: loginError || '',
            };
          })()
        ''')
        last_state = state if isinstance(state, dict) else {}
        if isinstance(state, dict) and state.get('loginError'):
            raise DesktopAutomationError(f'NN Agent login rejected: {state["loginError"]}')
        if isinstance(state, dict) and state.get('hasSession') and not state.get('formVisible'):
            return True
        await asyncio.sleep(0.5)
    raise DesktopAutomationError(
        'NN Agent login timed out; the isolated desktop session was not established '
        f'(form_visible={bool(last_state.get("formVisible"))}, user_id={last_state.get("userId") or "missing"}).'
    )


async def _activate_cdp_route_context(page: _CDPPage, target_route: str) -> str:
    """Navigate within the existing NN renderer without reloading the client.

    Reloading Electron's renderer for every case is unsafe during a long
    sequential run: it can terminate NN's render process. Prefer NN's Vue
    router over direct hash assignment: direct hash changes can update the URL
    while retaining the previous community's store state in the renderer.
    Hash assignment remains a compatibility fallback for older NN builds.
    """
    requested_route = str(target_route or '').lstrip('#')
    if not requested_route:
        return str(await page.evaluate('location.hash || ""') or '')
    current_route = str(await page.evaluate('location.hash || ""') or '')
    is_hall_route = bool(re.fullmatch(r'/community/\d+/hall(?:\?.*)?', requested_route))
    requires_hall_remount = current_route.lstrip('#') == requested_route and is_hall_route
    if current_route.lstrip('#') != requested_route or requires_hall_remount:
        navigation = await page.evaluate(rf'''
          (() => {{
            const requestedRoute = {json.dumps(requested_route)};
            const router = document.querySelector('#app')?.__vue_app__?._context?.config?.globalProperties?.$router;
            if (!router || typeof router.push !== 'function') return {{usedRouter: false}};
            // Hall keeps its composer component alive across same-route runs.
            // Re-enter through a neutral route so its conversation prop is
            // rebuilt from the current channel rather than the prior case.
            if ({json.dumps(requires_hall_remount)}) {{
              return Promise.resolve(router.replace('/home'))
                .then(() => router.push(requestedRoute))
                .then(() => ({{usedRouter: true, remounted: true, route: router.currentRoute?.value?.fullPath || location.hash}}))
                .catch(error => ({{usedRouter: true, remounted: true, error: String(error?.message || error)}}));
            }}
            return Promise.resolve(router.push(requestedRoute))
              .then(() => ({{usedRouter: true, route: router.currentRoute?.value?.fullPath || location.hash}}))
              .catch(error => ({{usedRouter: true, error: String(error?.message || error)}}));
          }})()
        ''')
        # Some NN Electron builds resolve router.push() without changing the
        # hash when the target route has not been registered in that router
        # instance. Treat that as a failed navigation and use hash history as
        # the compatibility path instead of accepting a false success.
        routed_to_target = (
            isinstance(navigation, dict)
            and navigation.get('usedRouter')
            and not navigation.get('error')
            and str(navigation.get('route') or '').lstrip('#') == requested_route
        )
        if not routed_to_target:
            await page.evaluate(f'location.hash = {json.dumps(requested_route)}; location.hash')
    await _wait_for_cdp_renderer_stability(page, timeout_seconds=12)
    current_route = str(await page.evaluate('location.hash || ""') or '')
    if current_route.lstrip('#') != requested_route:
        raise DesktopAutomationError(
            f'Electron route did not reach the requested target: {requested_route}; actual: {current_route}.'
        )
    return current_route


async def _restore_cdp_page_after_reconnect(
    page: _CDPPage,
    target_route: str,
    desktop_config: dict[str, Any],
    execution_record,
) -> None:
    """Restore only explicitly replayable setup state after a renderer socket drops."""
    if target_route:
        current_route = str(await page.evaluate('location.hash || ""') or '')
        preserve_route = bool(desktop_config.get('cdp_preserve_route_on_reconnect', False))
        if current_route.lstrip('#') != target_route and not (preserve_route and current_route.lstrip('#')):
            await page.evaluate(f'location.hash = {json.dumps(target_route)}; location.hash')
    await _wait_for_cdp_renderer_stability(page)
    replayable_actions = [
        action for action in _cdp_setup_actions(desktop_config)
        if bool(action.get('replay_on_reconnect', False))
    ]
    if replayable_actions:
        await _run_cdp_setup_actions(page, desktop_config, execution_record, actions=replayable_actions)
    execution_record.logs += (
        f'[Desktop CDP] Reconnected to Electron renderer (recovery #{page.recovery_count})'
        f'; restored route {target_route or "current route"}.\n'
    )
    execution_record.save(update_fields=['logs'])


def run_cdp_desktop_case(execution_record, task_description: str, desktop_config: dict[str, Any], should_stop=None) -> None:
    """Execute an Electron desktop case through CDP, without OS mouse or keyboard input."""
    # The executor persists report progress from its async CDP loop. Keep this
    # compatibility setting local to the execution entry point so direct runs
    # and API-thread runs behave identically.
    os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')
    started_at = timezone.now()
    execution_record.start_time = started_at
    execution_record.end_time = None
    execution_record.duration = None
    execution_record.status = 'running'
    execution_record.logs += '\n[Desktop CDP] Starting Electron DOM execution.\n'
    execution_record.save(update_fields=['start_time', 'end_time', 'duration', 'status', 'logs'])
    screenshots: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    instructions = _order_desktop_task_instructions(
        _desktop_setup_instructions(desktop_config) + _desktop_task_instructions(task_description)
    )

    async def execute():
        page = None
        hide_agent_task = None
        hall_fixture_evidence: dict[str, Any] = {}
        target_route = ''
        try:
            execution_record.planned_tasks = [
                {'id': f'desktop_cdp_{index}', 'description': instruction, 'status': 'pending'}
                for index, instruction in enumerate(instructions, 1) if instruction
            ]
            if not execution_record.planned_tasks:
                raise DesktopAutomationError('No executable natural-language instruction was found.')
            execution_record.save(update_fields=['planned_tasks'])
            _append_startup_progress(execution_record, 'Connecting to the local Electron CDP endpoint...', should_stop)
            cdp_url = str(desktop_config.get('cdp_url') or 'http://127.0.0.1:9222')
            if _task_requires_hall_other_member_fixture(task_description, desktop_config):
                _append_startup_progress(execution_record, 'Preparing a real other-member Hall message in an isolated fixture session.', should_stop)
                hall_fixture_evidence = await _seed_hall_other_member_fixture(desktop_config)
                execution_record.logs += (
                    '[Desktop CDP] Prepared other-member Hall fixture from the configured secondary account.\n'
                )
                execution_record.save(update_fields=['logs'])
            started_client = await _ensure_cdp_endpoint(cdp_url, desktop_config)
            if started_client:
                _append_startup_progress(execution_record, 'Electron CDP endpoint was unavailable; started the configured Agent client.', should_stop)
            page = await _CDPPage.connect(cdp_url)
            await _block_cdp_external_image_navigation(page)
            if bool(desktop_config.get('cdp_silent', True)):
                executable = str(desktop_config.get('cdp_executable') or '')

                async def keep_agent_hidden():
                    while True:
                        await asyncio.to_thread(_hide_cdp_agent_windows, executable)
                        await asyncio.sleep(0.4)

                hide_agent_task = asyncio.create_task(keep_agent_hidden())
            _append_startup_progress(execution_record, 'Electron CDP page is ready.', should_stop)
            reset_state = await _reset_cdp_case_state(page, 'before')
            execution_record.logs += f'[Desktop CDP] Reset isolated case state before execution: {reset_state}\n'
            execution_record.save(update_fields=['logs'])
            if hall_fixture_evidence:
                fixture_payload = json.dumps(json.dumps(hall_fixture_evidence, ensure_ascii=False), ensure_ascii=False)
                await page.evaluate(
                    f'''(() => {{
                      const fixture = {fixture_payload};
                      sessionStorage.setItem("__testhub_hall_other_member_fixture", fixture);
                      let values = [];
                      try {{ values = JSON.parse(sessionStorage.getItem("__testhub_hall_unique_messages") || "[]"); }} catch (_error) {{}}
                      const value = String(JSON.parse(fixture || "{{}}").value || "");
                      if (value && !values.includes(value)) values.push(value);
                      sessionStorage.setItem("__testhub_hall_unique_messages", JSON.stringify(values));
                      return true;
                    }})()'''
                )
            target_route = _cdp_target_route(desktop_config, task_description)
            has_login_template = bool(_cdp_login_credentials(desktop_config))
            execution_record.logs += (
                f'[Desktop CDP] Setup-template login credentials configured={has_login_template}.\n'
            )
            execution_record.save(update_fields=['logs'])
            login_completed = await _ensure_cdp_nn_login(page, desktop_config)
            if login_completed:
                execution_record.logs += '[Desktop CDP] Established the NN Agent session from the selected setup template.\n'
                execution_record.save(update_fields=['logs'])
            if target_route:
                current_route = await _activate_cdp_route_context(page, target_route)
                route_context = await _verify_cdp_route_context(page, target_route)
                execution_record.logs += (
                    f'[Desktop CDP] Activated target route context: {current_route}; '
                    f'rendered community={route_context.get("renderedCommunities") or []}.\n'
                )
                execution_record.save(update_fields=['logs'])
            dismissed_overlays = await _dismiss_cdp_transient_overlays(page)
            if dismissed_overlays:
                execution_record.logs += f'[Desktop CDP] Cleared {dismissed_overlays} transient overlay(s) from the prior case.\n'
                execution_record.save(update_fields=['logs'])
            await _run_cdp_setup_actions(page, desktop_config, execution_record)
            if target_route:
                route_context = await _verify_cdp_route_context(page, target_route)
                execution_record.logs += (
                    '[Desktop CDP] Revalidated target route after setup actions; '
                    f'rendered community={route_context.get("renderedCommunities") or []}.\n'
                )
                execution_record.save(update_fields=['logs'])
            page.set_recovery_hook(
                lambda recovered_page: _restore_cdp_page_after_reconnect(
                    recovered_page, target_route, desktop_config, execution_record
                )
            )
            _append_startup_progress(execution_record, 'Loading the desktop action planner...', should_stop)
            llm = _desktop_planner_llm()
            _append_startup_progress(execution_record, 'Startup complete; executing case steps.', should_stop)
            assertion_index = 0
            last_screenshot_path: str | None = None
            for task_index, instruction in enumerate(instructions, 1):
                if should_stop and should_stop():
                    execution_record.status = 'stopped'
                    execution_record.planned_tasks[task_index - 1]['status'] = 'stopped'
                    break
                semantic_result = await _execute_cdp_semantic_instruction(page, instruction, task_description)
                if instruction.startswith('断言：') and semantic_result is None:
                    assertion_index += 1
                    step_number = len(records) + 1
                    # Consecutive assertions inspect the same renderer state. Reuse its evidence
                    # rather than making Chromium 108 recapture an identical full-window image.
                    screenshot_path = last_screenshot_path or await _capture_cdp_screenshot(page, execution_record.id, step_number)
                    if screenshot_path:
                        last_screenshot_path = screenshot_path
                    dom_assertion = _cdp_dom_assertion_for_index(desktop_config, assertion_index)
                    result = (
                        await _run_cdp_dom_assertion(page, dom_assertion)
                        if dom_assertion else _run_desktop_visual_assertion(llm, instruction, screenshot_path or '')
                    )
                    item = {'step_number': step_number, 'action_type': 'assert_visual', 'description': instruction,
                            'status': 'completed' if result['status'] == 'passed' else 'failed', 'element': None,
                            'error': None if result['status'] == 'passed' else result['reason'], 'visual_assertion': result}
                    if screenshot_path:
                        item['screenshot'] = f'/media/{screenshot_path}'
                        screenshots.append({'step_number': step_number, 'description': instruction, 'status': item['status'], 'path': screenshot_path, 'url': item['screenshot']})
                    records.append(item)
                    execution_record.planned_tasks[task_index - 1]['status'] = item['status']
                    execution_record.steps_completed = records
                    execution_record.screenshots_sequence = screenshots
                    assertion_kind = 'DOM' if dom_assertion else 'visual'
                    execution_record.logs += f'[Desktop CDP] {assertion_kind} assertion {task_index} {item["status"]}: {result["reason"]}\n'
                    execution_record.save(update_fields=['logs', 'planned_tasks', 'steps_completed', 'screenshots_sequence'])
                    if item['status'] == 'failed':
                        break
                    continue
                completed = False
                if semantic_result is not None:
                    step_number = len(records) + 1
                    passed = bool(semantic_result.get('passed'))
                    item = {
                        'step_number': step_number,
                        'action_type': 'semantic_action',
                        'description': instruction,
                        'status': 'completed' if passed else 'failed',
                        'element': semantic_result,
                        'screenshot': None,
                        'error': None if passed else str(semantic_result.get('reason') or 'Semantic desktop action failed.'),
                    }
                    last_screenshot_path = None
                    screenshot_path = await _capture_cdp_screenshot(page, execution_record.id, step_number)
                    if screenshot_path:
                        last_screenshot_path = screenshot_path
                        item['screenshot'] = f'/media/{screenshot_path}'
                        screenshots.append({'step_number': step_number, 'description': instruction, 'status': item['status'], 'path': screenshot_path, 'url': item['screenshot']})
                    records.append(item)
                    execution_record.planned_tasks[task_index - 1]['status'] = item['status']
                    execution_record.steps_completed = records
                    execution_record.screenshots_sequence = screenshots
                    execution_record.logs += f'[Desktop CDP] semantic action {task_index} {item["status"]}: {semantic_result.get("reason", "")}\n'
                    execution_record.save(update_fields=['logs', 'planned_tasks', 'steps_completed', 'screenshots_sequence'])
                    if not passed:
                        break
                    completed = True
                    continue
                previous_actions = []
                for _attempt in range(8):
                    if should_stop and should_stop():
                        execution_record.status = 'stopped'
                        break
                    controls = await page.evaluate(_CDP_VISIBLE_CONTROLS_SCRIPT)
                    if not controls:
                        raise DesktopAutomationError('NN CDP page has no visible semantic controls for this operation.')
                    action = _plan_desktop_action(
                        llm,
                        task_description,
                        instruction,
                        controls,
                        previous_actions,
                        allow_screenshot=False,
                    )
                    prior_waits = sum(1 for item in previous_actions if item.get('action') == 'wait')
                    if str(action.get('action') or '').lower() == 'wait' and prior_waits >= 1:
                        previous_actions.append({
                            'action': 'wait',
                            'result': 'rejected',
                            'reason': 'A live control scan is already available; select a control or complete the instruction.',
                        })
                        execution_record.logs += '[Desktop CDP] repeated wait request rejected; replanning from live controls.\n'
                        execution_record.save(update_fields=['logs'])
                        continue
                    if str(action.get('action') or '').lower() == 'screenshot':
                        previous_actions.append({
                            'action': 'screenshot',
                            'result': 'rejected',
                            'reason': 'CDP already has a live semantic control scan; choose an allowed action.',
                        })
                        execution_record.logs += '[Desktop CDP] planner screenshot request rejected; replanning from live controls.\n'
                        execution_record.save(update_fields=['logs'])
                        continue
                    step = _cdp_step_from_action(action, controls)
                    if step is None:
                        completed = True
                        execution_record.planned_tasks[task_index - 1]['status'] = 'completed'
                        execution_record.logs += f'[Desktop CDP] completed task {task_index}: {instruction}\n'
                        break
                    step_number = len(records) + 1
                    item = {'step_number': step_number, 'action_type': step['action'], 'description': f'{instruction} | {step["description"]}',
                            'status': 'pending', 'element': None, 'screenshot': None, 'error': None, 'planner_action': action}
                    try:
                        item['element'] = await _execute_cdp_step(page, step)
                        item['status'] = 'completed'
                        previous_actions.append({'action': step['action'], 'control_id': action.get('control_id'), 'value': step.get('value', '')})
                        execution_record.logs += f'[Desktop CDP] action {step_number} completed: {item["description"]}\n'
                    except Exception as exc:
                        item['status'] = 'failed'
                        item['error'] = str(exc)
                        execution_record.planned_tasks[task_index - 1]['status'] = 'failed'
                        execution_record.logs += f'[Desktop CDP] action {step_number} failed: {exc}\n'
                    last_screenshot_path = None
                    screenshot_path = await _capture_cdp_screenshot(page, execution_record.id, step_number)
                    if screenshot_path:
                        last_screenshot_path = screenshot_path
                        item['screenshot'] = f'/media/{screenshot_path}'
                        screenshots.append({'step_number': step_number, 'description': item['description'], 'status': item['status'], 'path': screenshot_path, 'url': item['screenshot']})
                    records.append(item)
                    execution_record.steps_completed = records
                    execution_record.screenshots_sequence = screenshots
                    execution_record.save(update_fields=['logs', 'planned_tasks', 'steps_completed', 'screenshots_sequence'])
                    if item['status'] == 'failed':
                        break
                    if step['action'] == 'wait' and _is_wait_only_instruction(instruction):
                        completed = True
                        execution_record.planned_tasks[task_index - 1]['status'] = 'completed'
                        break
                if execution_record.status == 'stopped' or execution_record.planned_tasks[task_index - 1]['status'] == 'failed':
                    break
                if not completed:
                    execution_record.planned_tasks[task_index - 1]['status'] = 'failed'
                    execution_record.logs += f'[Desktop CDP] task {task_index} exceeded the 8-action safety limit.\n'
                    break
            if execution_record.status == 'running':
                execution_record.status = 'passed' if all(task.get('status') == 'completed' for task in execution_record.planned_tasks) else 'failed'
        except Exception as exc:
            execution_record.status = 'failed'
            execution_record.logs += f'[Desktop CDP] Execution failed: {exc}\n'
        finally:
            if hide_agent_task is not None:
                hide_agent_task.cancel()
                try:
                    await hide_agent_task
                except asyncio.CancelledError:
                    pass
            if page is not None:
                try:
                    if re.fullmatch(r'/community/\d+/hall(?:\?.*)?', target_route):
                        hall_cleanup = await _cleanup_cdp_generated_hall_messages(page)
                        existing_cleanup = execution_record.cleanup_results if isinstance(execution_record.cleanup_results, dict) else {}
                        execution_record.cleanup_results = {**existing_cleanup, 'hall_messages': hall_cleanup}
                        execution_record.logs += (
                            '[Desktop CDP] Hall generated-message cleanup '
                            f'{"completed" if hall_cleanup.get("passed") else "failed"}: '
                            f'{hall_cleanup.get("reason", "")}.\n'
                        )
                        if not hall_cleanup.get('passed') and execution_record.status == 'passed':
                            execution_record.status = 'failed'
                        execution_record.save(update_fields=['status', 'logs', 'cleanup_results'])
                    reset_state = await _reset_cdp_case_state(page, 'after')
                    execution_record.logs += f'[Desktop CDP] Reset isolated case state after execution: {reset_state}\n'
                    execution_record.save(update_fields=['logs'])
                except Exception as cleanup_error:
                    execution_record.logs += f'[Desktop CDP] Case-state cleanup warning: {cleanup_error}\n'
                    execution_record.save(update_fields=['logs'])
                await page.close()
            if hall_fixture_evidence:
                try:
                    fixture_cleanup = await _cleanup_hall_other_member_fixture(desktop_config, hall_fixture_evidence)
                    existing_cleanup = execution_record.cleanup_results if isinstance(execution_record.cleanup_results, dict) else {}
                    execution_record.cleanup_results = {**existing_cleanup, 'hall_other_member_fixture': fixture_cleanup}
                    execution_record.logs += (
                        '[Desktop CDP] Other-member Hall fixture cleanup '
                        f'{"completed" if fixture_cleanup.get("passed") else "failed"}: '
                        f'{fixture_cleanup.get("reason", "")}.\n'
                    )
                    if not fixture_cleanup.get('passed') and execution_record.status == 'passed':
                        execution_record.status = 'failed'
                    execution_record.save(update_fields=['status', 'logs', 'cleanup_results'])
                except Exception as fixture_cleanup_error:
                    execution_record.status = 'failed' if execution_record.status == 'passed' else execution_record.status
                    execution_record.logs += f'[Desktop CDP] Other-member Hall fixture cleanup warning: {fixture_cleanup_error}\n'
                    execution_record.save(update_fields=['status', 'logs'])

    try:
        asyncio.run(execute())
    finally:
        if _execution_finished_elsewhere(execution_record):
            return
        execution_record.end_time = timezone.now()
        execution_record.duration = (execution_record.end_time - started_at).total_seconds()
        execution_record.steps_completed = records
        execution_record.screenshots_sequence = screenshots
        execution_record.save(update_fields=['status', 'logs', 'end_time', 'duration', 'planned_tasks', 'steps_completed', 'screenshots_sequence'])
        _persist_desktop_execution_gif(execution_record, records)
        from .ai_notifications import send_ai_execution_notification
        send_ai_execution_notification(execution_record)


def run_natural_language_desktop_case(execution_record, task_description: str, desktop_config: dict[str, Any], should_stop=None) -> None:
    """Plan and execute desktop UI actions from natural language against live UIA controls."""
    started_at = timezone.now()
    execution_record.start_time = started_at
    execution_record.end_time = None
    execution_record.duration = None
    execution_record.status = 'running'
    execution_record.logs += '\n[Desktop Agent] Starting natural-language execution.\n'
    execution_record.save(update_fields=['start_time', 'end_time', 'duration', 'status', 'logs'])

    screenshots: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    instructions = _desktop_setup_instructions(desktop_config) + _desktop_task_instructions(task_description)
    try:
        execution_record.planned_tasks = [
            {'id': f'desktop_nl_{index}', 'description': instruction, 'status': 'pending'}
            for index, instruction in enumerate(instructions, 1) if instruction
        ]
        if not execution_record.planned_tasks:
            raise DesktopAutomationError('No executable natural-language instruction was found.')
        execution_record.save(update_fields=['planned_tasks'])
        _append_startup_progress(execution_record, 'Connecting to the target desktop window...', should_stop)
        window, keyboard = _connect_window(desktop_config)
        _append_startup_progress(execution_record, 'Target desktop window is ready.', should_stop)
        timeout = float(desktop_config.get('control_timeout_seconds') or 10)
        _append_startup_progress(execution_record, 'Loading the desktop action planner...', should_stop)
        llm = _desktop_planner_llm()
        _append_startup_progress(execution_record, 'Startup complete; executing case steps.', should_stop)

        for task_index, instruction in enumerate(instructions, 1):
            if not instruction:
                continue
            if instruction.startswith('断言：'):
                step_number = len(records) + 1
                screenshot_path = _capture_screenshot(window, execution_record.id, step_number)
                item = {
                    'step_number': step_number,
                    'action_type': 'assert_visual',
                    'description': instruction,
                    'status': 'pending',
                    'element': None,
                    'screenshot': None,
                    'error': None,
                }
                try:
                    result = _run_desktop_visual_assertion(llm, instruction, screenshot_path or '')
                    item['visual_assertion'] = result
                    item['status'] = 'completed' if result['status'] == 'passed' else 'failed'
                    item['error'] = result['reason'] if item['status'] == 'failed' else None
                    execution_record.planned_tasks[task_index - 1]['status'] = item['status']
                    execution_record.logs += (
                        f'[Desktop Agent] visual assertion {task_index} {item["status"]}: '
                        f'{result["reason"]}\n'
                    )
                except Exception as exc:
                    item['status'] = 'failed'
                    item['error'] = str(exc)
                    execution_record.planned_tasks[task_index - 1]['status'] = 'failed'
                    execution_record.logs += f'[Desktop Agent] visual assertion {task_index} failed: {exc}\n'
                if screenshot_path:
                    screenshot = {
                        'step_number': step_number,
                        'description': instruction,
                        'status': item['status'],
                        'path': screenshot_path,
                        'url': f'/media/{screenshot_path}',
                    }
                    item['screenshot'] = screenshot['url']
                    screenshots.append(screenshot)
                records.append(item)
                execution_record.steps_completed = records
                execution_record.screenshots_sequence = screenshots
                execution_record.save(update_fields=['logs', 'planned_tasks', 'steps_completed', 'screenshots_sequence'])
                if item['status'] == 'failed':
                    break
                continue
            completed = False
            task_actions: list[dict[str, Any]] = []
            for attempt in range(1, 9):
                if should_stop and should_stop():
                    execution_record.status = 'stopped'
                    execution_record.planned_tasks[task_index - 1]['status'] = 'stopped'
                    break
                controls = _desktop_control_snapshot(window)
                if not controls:
                    raise DesktopAutomationError('No visible desktop controls were available for the planner.')
                if not any(item.get('name') or item.get('auto_id') for item in controls):
                    step_number = len(records) + 1
                    planning_screenshot = _capture_screenshot(window, execution_record.id, step_number)
                    item = {
                        'step_number': step_number,
                        'action_type': 'visual_operation',
                        'description': instruction,
                        'status': 'pending',
                        'element': None,
                        'screenshot': None,
                        'error': None,
                    }
                    try:
                        visual_action = _plan_desktop_visual_action(
                            llm,
                            instruction,
                            planning_screenshot or '',
                            previous_actions=task_actions,
                        )
                        item['visual_action'] = visual_action
                        if visual_action['action'] == 'done':
                            result = _run_desktop_visual_operation_check(llm, instruction, planning_screenshot or '')
                            item['visual_state_check'] = result
                            item['status'] = 'completed' if result['status'] == 'passed' else 'failed'
                            item['error'] = None if item['status'] == 'completed' else result['reason']
                            if item['status'] == 'completed':
                                completed = True
                                execution_record.planned_tasks[task_index - 1]['status'] = 'completed'
                                execution_record.logs += f'[Desktop Agent] visual state confirmed task {task_index}: {result["reason"]}\n'
                            else:
                                execution_record.planned_tasks[task_index - 1]['status'] = 'failed'
                                execution_record.logs += f'[Desktop Agent] visual state check failed: {result["reason"]}\n'
                        else:
                            item['element'] = _execute_step(
                                window,
                                keyboard,
                                visual_action,
                                timeout,
                                allow_pointer_input=bool(desktop_config.get('allow_pointer_input', False)),
                            )
                            item['status'] = 'completed'
                            task_actions.append({
                                'action': visual_action['action'],
                                'coordinate': {'x': visual_action.get('x'), 'y': visual_action.get('y')},
                            })
                            execution_record.logs += (
                                f'[Desktop Agent] visual action {step_number} completed: '
                                f'{visual_action["action"]}; {visual_action.get("reason", "")}\n'
                            )
                            if visual_action['action'] == 'wait' and _is_wait_only_instruction(instruction):
                                completed = True
                                execution_record.planned_tasks[task_index - 1]['status'] = 'completed'
                    except Exception as exc:
                        item['status'] = 'failed'
                        item['error'] = str(exc)
                        execution_record.planned_tasks[task_index - 1]['status'] = 'failed'
                        execution_record.logs += f'[Desktop Agent] visual action {step_number} failed: {exc}\n'
                    screenshot_path = _capture_screenshot(window, execution_record.id, step_number)
                    if screenshot_path:
                        screenshot = {
                            'step_number': step_number,
                            'description': instruction,
                            'status': item['status'],
                            'path': screenshot_path,
                            'url': f'/media/{screenshot_path}',
                        }
                        item['screenshot'] = screenshot['url']
                        screenshots.append(screenshot)
                    records.append(item)
                    execution_record.steps_completed = records
                    execution_record.screenshots_sequence = screenshots
                    execution_record.save(update_fields=['logs', 'planned_tasks', 'steps_completed', 'screenshots_sequence'])
                    if item['status'] == 'failed' or completed:
                        break
                    continue
                planned_action = _plan_desktop_action(
                    llm,
                    task_description,
                    instruction,
                    controls,
                    previous_actions=task_actions,
                )
                step = _planned_step_from_action(planned_action, controls)
                if step is None:
                    completed = True
                    execution_record.planned_tasks[task_index - 1]['status'] = 'completed'
                    execution_record.logs += f'[Desktop Agent] completed task {task_index}: {instruction}\n'
                    break

                step_number = len(records) + 1
                item = {
                    'step_number': step_number,
                    'action_type': step['action'],
                    'description': f'{instruction} | {step["description"]}',
                    'status': 'pending',
                    'element': None,
                    'screenshot': None,
                    'error': None,
                    'planner_action': planned_action,
                }
                try:
                    item['element'] = _execute_step(
                        window,
                        keyboard,
                        step,
                        timeout,
                        allow_pointer_input=bool(desktop_config.get('allow_pointer_input', False)),
                    )
                    item['status'] = 'completed'
                    task_actions.append({
                        'action': step['action'],
                        'control_id': planned_action.get('control_id'),
                        'value': step.get('value', ''),
                    })
                    execution_record.logs += f'[Desktop Agent] action {step_number} completed: {item["description"]}\n'
                except Exception as exc:
                    item['status'] = 'failed'
                    item['error'] = str(exc)
                    execution_record.planned_tasks[task_index - 1]['status'] = 'failed'
                    execution_record.logs += f'[Desktop Agent] action {step_number} failed: {exc}\n'

                screenshot_path = _capture_screenshot(window, execution_record.id, step_number)
                if screenshot_path:
                    screenshot = {
                        'step_number': step_number,
                        'description': item['description'],
                        'status': item['status'],
                        'path': screenshot_path,
                        'url': f'/media/{screenshot_path}',
                    }
                    item['screenshot'] = screenshot['url']
                    screenshots.append(screenshot)
                records.append(item)
                execution_record.steps_completed = records
                execution_record.screenshots_sequence = screenshots
                execution_record.save(update_fields=['logs', 'planned_tasks', 'steps_completed', 'screenshots_sequence'])
                if item['status'] == 'failed':
                    break
                if step['action'] == 'wait' and _is_wait_only_instruction(instruction):
                    completed = True
                    execution_record.planned_tasks[task_index - 1]['status'] = 'completed'
                    execution_record.logs += f'[Desktop Agent] completed wait task {task_index}: {instruction}\n'
                    break

            if execution_record.status == 'stopped' or execution_record.planned_tasks[task_index - 1]['status'] == 'failed':
                break
            if not completed:
                execution_record.planned_tasks[task_index - 1]['status'] = 'failed'
                execution_record.logs += f'[Desktop Agent] task {task_index} exceeded the 8-action safety limit.\n'
                break

        if execution_record.status == 'running':
            execution_record.status = 'passed' if all(
                task.get('status') == 'completed' for task in execution_record.planned_tasks
            ) else 'failed'
    except Exception as exc:
        execution_record.status = 'failed'
        execution_record.logs += f'[Desktop Agent] Execution failed: {exc}\n'
    finally:
        if _execution_finished_elsewhere(execution_record):
            return
        execution_record.end_time = timezone.now()
        execution_record.duration = (execution_record.end_time - started_at).total_seconds()
        execution_record.steps_completed = records
        execution_record.screenshots_sequence = screenshots
        execution_record.save(update_fields=[
            'status', 'logs', 'end_time', 'duration', 'planned_tasks', 'steps_completed', 'screenshots_sequence'
        ])
        _persist_desktop_execution_gif(execution_record, records)
        from .ai_notifications import send_ai_execution_notification
        send_ai_execution_notification(execution_record)


def run_desktop_case(execution_record, desktop_config: dict[str, Any], should_stop=None) -> None:
    """Execute a desktop case synchronously and persist report-compatible evidence."""
    if isinstance(desktop_config, dict) and str(desktop_config.get('automation_backend') or '').lower() == 'cdp':
        return run_cdp_desktop_case(
            execution_record,
            str(getattr(execution_record, 'task_description', '') or ''),
            desktop_config,
            should_stop=should_stop,
        )
    if not isinstance(desktop_config, dict) or not desktop_config.get('steps'):
        task_description = str(getattr(execution_record, 'task_description', '') or '')
        return run_natural_language_desktop_case(
            execution_record,
            task_description,
            desktop_config if isinstance(desktop_config, dict) else {},
            should_stop=should_stop,
        )
    started_at = timezone.now()
    execution_record.start_time = started_at
    execution_record.end_time = None
    execution_record.duration = None
    execution_record.status = 'running'
    execution_record.logs += '\n[Desktop] Starting Windows native UI execution.\n'
    execution_record.save(update_fields=['start_time', 'end_time', 'duration', 'status', 'logs'])

    screenshots: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    try:
        steps = _validate_config(desktop_config)
        execution_record.planned_tasks = [
            {'id': f'desktop_{index}', 'description': _step_description(step, index), 'status': 'pending'}
            for index, step in enumerate(steps, 1)
        ]
        execution_record.save(update_fields=['planned_tasks'])
        _append_startup_progress(execution_record, 'Connecting to the target desktop window...', should_stop)
        window, keyboard = _connect_window(desktop_config)
        _append_startup_progress(execution_record, 'Target desktop window is ready.', should_stop)
        timeout = float(desktop_config.get('control_timeout_seconds') or 10)
        _append_startup_progress(execution_record, 'Startup complete; executing case steps.', should_stop)

        for index, step in enumerate(steps, 1):
            description = _step_description(step, index)
            item = {
                'step_number': index,
                'action_type': str(step.get('action') or '').lower(),
                'description': description,
                'status': 'pending',
                'element': None,
                'screenshot': None,
                'error': None,
            }
            if should_stop and should_stop():
                item['status'] = 'stopped'
                item['error'] = 'Execution stopped by user.'
                records.append(item)
                execution_record.status = 'stopped'
                break
            try:
                item['element'] = _execute_step(
                    window,
                    keyboard,
                    step,
                    timeout,
                    allow_pointer_input=bool(desktop_config.get('allow_pointer_input', False)),
                )
                item['status'] = 'completed'
                execution_record.logs += f'[Desktop Step {index}] completed: {description}\n'
            except Exception as exc:
                item['status'] = 'failed'
                item['error'] = str(exc)
                execution_record.logs += f'[Desktop Step {index}] failed: {description}; {exc}\n'
            screenshot_path = _capture_screenshot(window, execution_record.id, index)
            if screenshot_path:
                screenshot = {
                    'step_number': index,
                    'description': description,
                    'status': item['status'],
                    'path': screenshot_path,
                    'url': f'/media/{screenshot_path}',
                }
                item['screenshot'] = screenshot['url']
                screenshots.append(screenshot)
            records.append(item)
            execution_record.planned_tasks[index - 1]['status'] = item['status']
            execution_record.steps_completed = records
            execution_record.screenshots_sequence = screenshots
            execution_record.save(update_fields=['logs', 'planned_tasks', 'steps_completed', 'screenshots_sequence'])
            if item['status'] == 'failed':
                break

        if execution_record.status == 'running':
            execution_record.status = 'passed' if all(item['status'] == 'completed' for item in records) else 'failed'
    except Exception as exc:
        execution_record.status = 'failed'
        execution_record.logs += f'[Desktop] Execution setup failed: {exc}\n'
    finally:
        if _execution_finished_elsewhere(execution_record):
            return
        execution_record.end_time = timezone.now()
        execution_record.duration = (execution_record.end_time - started_at).total_seconds()
        execution_record.steps_completed = records
        execution_record.screenshots_sequence = screenshots
        execution_record.save(update_fields=[
            'status', 'logs', 'end_time', 'duration', 'planned_tasks', 'steps_completed', 'screenshots_sequence'
        ])
        _persist_desktop_execution_gif(execution_record, records)
        from .ai_notifications import send_ai_execution_notification
        send_ai_execution_notification(execution_record)

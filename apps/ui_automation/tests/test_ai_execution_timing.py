import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from apps.ui_automation.views import _helpers


class _ExecutionRecord:
    def __init__(self):
        self.start_time = 'batch-created-time'
        self.end_time = 'stale-end-time'
        self.duration = 123.45
        self.status = 'pending'
        self.saved_fields = None

    def save(self, *, update_fields):
        self.saved_fields = update_fields


def test_execution_start_time_is_reset_when_the_individual_job_starts(monkeypatch):
    record = _ExecutionRecord()
    actual_started_at = datetime(2026, 7, 22, 17, 10, tzinfo=timezone.utc)

    monkeypatch.setattr(_helpers.timezone, 'now', lambda: actual_started_at)
    monkeypatch.setattr(_helpers, 'close_old_connections', lambda: None)

    _helpers._mark_execution_started(record)

    assert record.start_time == actual_started_at
    assert record.end_time is None
    assert record.duration is None
    assert record.status == 'running'
    assert record.saved_fields == ['start_time', 'end_time', 'duration', 'status']


def test_page_ready_wait_retries_a_slow_page_until_it_is_usable(monkeypatch):
    results = iter([
        {'healthy': False, 'reason': '#app 存在但未挂载内容', 'evidence': {'appMounted': False}},
        {'healthy': True, 'reason': '', 'evidence': {'appMounted': True}},
        {'healthy': True, 'reason': '', 'evidence': {'appMounted': True}},
        {'healthy': True, 'reason': '', 'evidence': {'appMounted': True}},
    ])

    async def fake_health(_page):
        return next(results)

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(_helpers, '_evaluate_page_health', fake_health)
    monkeypatch.setattr(_helpers.asyncio, 'sleep', no_sleep)

    result = asyncio.run(_helpers._wait_for_page_ready(object(), timeout_seconds=5))

    assert result['healthy'] is True
    assert result['ready_state'] == 'ready'


def test_page_ready_wait_accepts_a_rendered_login_redirect(monkeypatch):
    async def fake_health(_page):
        return {
            'healthy': False,
            'reason': '页面仍处于登录页/登录弹窗状态',
            'evidence': {'loginPage': True, 'appMounted': True, 'visibleInteractiveCount': 2},
        }

    monkeypatch.setattr(_helpers, '_evaluate_page_health', fake_health)

    result = asyncio.run(_helpers._wait_for_page_ready(object(), timeout_seconds=5))

    assert result['healthy'] is True
    assert result['ready_state'] == 'login_redirect'


def test_failed_step_blocks_remaining_steps_without_running_them():
    steps = [
        {'action_type': 'click', 'description': '点击登录'},
        {'action_type': 'type', 'description': '输入手机号', 'input_value': '17600000000'},
        {'action_type': 'assert', 'description': '断言登录成功'},
    ]
    recorded = [{
        'step_number': 1,
        'action_type': 'click',
        'description': '点击登录',
        'status': 'failed',
        'error': '未找到登录按钮',
    }]
    planned = [
        {'id': 'task_1', 'status': 'failed'},
        {'id': 'task_2', 'status': 'pending'},
        {'id': 'task_3', 'status': 'pending'},
    ]

    count = _helpers.append_blocked_remaining_steps(
        steps,
        failed_index=0,
        recorded_steps=recorded,
        planned_tasks=planned,
        reason='阻塞于第 1 步：未找到登录按钮',
    )

    assert count == 2
    assert [item['status'] for item in recorded] == ['failed', 'skipped', 'skipped']
    assert [item['blocked_by_step'] for item in recorded[1:]] == [1, 1]
    assert all(item['status'] == 'skipped' for item in planned[1:])

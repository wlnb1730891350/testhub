from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import uuid

from apps.ui_automation.views.ai import (
    _build_ai_batch_report,
    _build_ai_execution_report_items,
    _extract_failure_reason,
)


def test_batch_report_uses_batch_window_and_individual_case_durations():
    batch_id = uuid.uuid4()
    batch_started_at = datetime(2026, 7, 22, 17, 0, tzinfo=timezone.utc)
    records = [
        SimpleNamespace(
            id=1,
            case_name='passed case',
            status='passed',
            batch_started_at=batch_started_at,
            batch_run_mode='sequential',
            start_time=batch_started_at + timedelta(seconds=5),
            end_time=batch_started_at + timedelta(seconds=20),
            duration=12.5,
            logs='',
            steps_completed=[],
        ),
        SimpleNamespace(
            id=2,
            case_name='failed case',
            status='failed',
            batch_started_at=batch_started_at,
            batch_run_mode='sequential',
            start_time=batch_started_at + timedelta(seconds=45),
            end_time=batch_started_at + timedelta(seconds=75),
            duration=25.0,
            logs='执行出错: target did not become visible',
            steps_completed=[],
        ),
    ]

    report = _build_ai_batch_report(batch_id, records)

    assert report['summary'] == {
        'total': 2,
        'passed': 1,
        'failed': 1,
        'running': 0,
        'pending': 0,
        'completion_rate': 50.0,
    }
    assert report['batch']['duration'] == 75.0
    assert [case['duration'] for case in report['cases']] == [12.5, 25.0]
    assert report['cases'][1]['failure_reason'] == '执行出错: target did not become visible'


def test_failure_reason_uses_failed_task_not_recording_completion_log():
    record = SimpleNamespace(
        steps_completed=[],
        planned_tasks=[
            {'status': 'failed', 'display_description': '点击同一文章卡片的标题区域。'},
        ],
        logs='[System] GIF录制已生成\n========== 录制完成 ==========',
    )

    assert _extract_failure_reason(record) == '失败步骤：点击同一文章卡片的标题区域。'


def test_report_list_groups_batch_records_into_one_summary_row():
    batch_id = uuid.uuid4()
    started_at = datetime(2026, 7, 23, 8, 0, tzinfo=timezone.utc)
    records = [
        SimpleNamespace(
            id=1, batch_id=batch_id, batch_started_at=started_at, case_name='first', status='passed',
            duration=10, start_time=started_at, end_time=started_at + timedelta(seconds=10),
            project=SimpleNamespace(name='社区'), executed_by=SimpleNamespace(username='tester'), gif_path='',
        ),
        SimpleNamespace(
            id=2, batch_id=batch_id, batch_started_at=started_at, case_name='second', status='failed',
            duration=20, start_time=started_at + timedelta(seconds=10), end_time=started_at + timedelta(seconds=30),
            project=SimpleNamespace(name='社区'), executed_by=SimpleNamespace(username='tester'), gif_path='',
        ),
        SimpleNamespace(
            id=3, batch_id=None, batch_started_at=None, case_name='single', status='passed',
            duration=5, start_time=started_at + timedelta(hours=1), end_time=started_at + timedelta(hours=1, seconds=5),
            project=SimpleNamespace(name='社区'), executed_by=SimpleNamespace(username='tester'), gif_path='',
        ),
    ]

    items = _build_ai_execution_report_items(records)

    assert len(items) == 2
    batch = next(item for item in items if item['item_type'] == 'batch')
    assert batch['case_count'] == 2
    assert batch['status'] == 'failed'
    assert batch['summary']['passed'] == 1
    assert batch['summary']['failed'] == 1

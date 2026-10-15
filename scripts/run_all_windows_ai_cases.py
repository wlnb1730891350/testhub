"""Run every AI case in Windows mode against the shared NN CDP session.

The NN client is stateful, so this runner deliberately executes one case at a
time. It records each result in the normal AI execution-report table and emits
compact JSONL progress for monitoring.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

import django


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')
django.setup()

from django.utils import timezone

from apps.ui_automation.desktop_engine import run_desktop_case
from apps.ui_automation.models import AICase, AIExecutionRecord
from apps.ui_automation.views.ai import _desktop_execution_config
import apps.ui_automation.ai_notifications as ai_notifications


# This runner owns exactly ONE batch summary, which is sent explicitly at the
# end of main(). Every batch member is pre-created up front, so the shared
# per-case notifier would normally find 166 still-pending records and stay
# quiet; disabling it here keeps the summary single-sourced and immune to
# future ordering changes (a batch that happened to reach its last case first
# could otherwise burn the per-batch cache lock with a partial report). The
# explicit batch call below is unaffected.
ai_notifications.send_ai_execution_notification = lambda _record: []


def emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def main() -> int:
    # A full sequential regression writes its own database reports and emits
    # exactly one batch summary to every opted-in webhook bot once the whole
    # batch settles (see ai_notifications.send_ai_batch_execution_notification
    # at the end). Per-case notifications are disabled at module import (see
    # the note next to the imports): delegating to the batch notifier per case
    # would ship a premature "共 1 条" summary and lock out the real report.
    batch_id = uuid.uuid4()
    batch_started_at = timezone.now()
    cases = list(AICase.objects.filter(
        execution_target__in=['desktop', 'dual'],
        desktop_app_profile__isnull=False,
    ).order_by('id'))

    # Pre-create every member record up front so the AI report page lists the
    # whole batch (as 等待中) from the first second. Creating them lazily made
    # the batch row read "批量执行（1 条用例）" and grow one case at a time,
    # which looked like the run was stuck on its first case. Each executor
    # resets start_time/status when its case really begins (see
    # desktop_engine.run_desktop_case), so durations stay exact.
    records = [
        AIExecutionRecord.objects.create(
            project=case.project,
            ai_case=case,
            case_name=case.name,
            task_description=(
                case.desktop_task_description
                if case.execution_target == 'dual'
                else case.task_description
            ),
            execution_target='desktop',
            batch_id=batch_id,
            batch_started_at=batch_started_at,
            batch_run_mode='sequential',
            status='pending',
            logs='等待执行...\n',
        )
        for case in cases
    ]

    emit({'event': 'started', 'batch_id': str(batch_id), 'total': len(cases)})

    totals = {'passed': 0, 'failed': 0, 'stopped': 0}
    for index, (case, record) in enumerate(zip(cases, records), 1):
        # Use the platform's own desktop-config builder instead of assembling
        # profile + cdp defaults by hand. _desktop_execution_config also folds
        # the case's setup template into cdp_login_credentials; the hand-rolled
        # dict skipped that step, so every isolated Electron profile started
        # logged-out and the login-dependent cases (e.g. "登录成功") looped on
        # the login dialog forever.
        config = _desktop_execution_config(case)
        emit({'event': 'case_started', 'index': index, 'total': len(cases), 'case_id': case.id, 'record_id': record.id, 'name': case.name})
        try:
            run_desktop_case(record, config, should_stop=lambda: False)
            record.refresh_from_db()
        except Exception as exc:
            record.status = 'failed'
            record.logs += f'\n[Full regression] Unhandled runner error: {exc}\n'
            record.save(update_fields=['status', 'logs'])
        status = record.status if record.status in totals else 'failed'
        totals[status] += 1
        emit({'event': 'case_finished', 'index': index, 'total': len(cases), 'case_id': case.id, 'record_id': record.id, 'name': case.name, 'status': status})

    emit({'event': 'finished', 'batch_id': str(batch_id), 'total': len(cases), **totals})

    # Fire a single batch summary to every opted-in webhook bot now that all
    # records under batch_id are terminal. Wrapped so a notification failure can
    # never fail the pipeline itself.
    try:
        notify_results = ai_notifications.send_ai_batch_execution_notification(batch_id)
        notify_results = list(notify_results) if notify_results else []
        emit({'event': 'notification', 'batch_id': str(batch_id), 'results': notify_results})
    except Exception as notify_error:
        emit({'event': 'notification_error', 'batch_id': str(batch_id), 'error': str(notify_error)})

    return 0 if not totals['failed'] and not totals['stopped'] else 1


if __name__ == '__main__':
    sys.exit(main())

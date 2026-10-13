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

from apps.ui_automation.desktop_engine import run_desktop_case
from apps.ui_automation.models import AICase, AIExecutionRecord
from apps.ui_automation.views.ai import _default_nn_cdp_config
import apps.ui_automation.ai_notifications as ai_notifications


def emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def main() -> int:
    # A full sequential regression must not emit one enterprise-WeChat message
    # per case. The normal batch-report path remains responsible for summary
    # notification after the run is reviewed.
    ai_notifications.send_ai_execution_notification = lambda _record: None
    batch_id = uuid.uuid4()
    cases = list(AICase.objects.filter(
        execution_target__in=['desktop', 'dual'],
        desktop_app_profile__isnull=False,
    ).order_by('id'))
    emit({'event': 'started', 'batch_id': str(batch_id), 'total': len(cases)})

    totals = {'passed': 0, 'failed': 0, 'stopped': 0}
    for index, case in enumerate(cases, 1):
        task_description = (
            case.desktop_task_description
            if case.execution_target == 'dual'
            else case.task_description
        )
        profile_config = case.desktop_app_profile.to_execution_config()
        config = {
            **profile_config,
            **_default_nn_cdp_config(case, profile_config),
            **(case.desktop_config or {}),
        }
        record = AIExecutionRecord.objects.create(
            project=case.project,
            ai_case=case,
            case_name=case.name,
            task_description=task_description,
            execution_target='desktop',
            batch_id=batch_id,
            batch_run_mode='sequential',
            status='running',
            logs='Full Windows regression started.\n',
        )
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
    return 0 if not totals['failed'] and not totals['stopped'] else 1


if __name__ == '__main__':
    sys.exit(main())

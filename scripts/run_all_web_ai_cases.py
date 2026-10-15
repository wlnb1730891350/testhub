"""Run AI browser cases sequentially with one reusable authenticated session cache.

The normal web executor still creates a fresh context and page for every case.
Only the validated same-origin login material is shared by the process-local
cache, so each case remains independent from the previous case's UI/data state.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

import django


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')
django.setup()

import apps.ui_automation.ai_notifications as ai_notifications
from apps.ui_automation.models import AICase, AIExecutionRecord
from apps.ui_automation.views.ai import _run_ai_case_with_target


def emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def is_article_case(case: AICase) -> bool:
    return '文章' in f'{case.name}\n{case.web_task_description or case.task_description}'


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--case-ids', default='', help='Comma-separated AI case IDs. Defaults to all web-capable cases.')
    parser.add_argument('--limit', type=int, default=0, help='Maximum number of selected web cases. 0 means no limit.')
    parser.add_argument('--skip-articles', action='store_true')
    parser.add_argument('--article-delay', type=float, default=20.0, help='Delay between article cases to reduce site rate limiting.')
    args = parser.parse_args()

    if args.limit < 0:
        parser.error('--limit must be 0 or greater')

    requested_ids = [int(value) for value in args.case_ids.split(',') if value.strip()]
    cases = AICase.objects.filter(execution_target__in=['web', 'dual']).order_by('id')
    if requested_ids:
        cases = cases.filter(id__in=requested_ids)
    cases = list(cases.select_related('setup_template', 'project'))
    if args.skip_articles:
        cases = [case for case in cases if not is_article_case(case)]
    if args.limit:
        cases = cases[:args.limit]

    # A full run writes its own database reports and emits exactly one batch
    # summary to every opted-in webhook bot once the whole batch settles
    # (see ai_notifications.send_ai_batch_execution_notification at the end).
    # Per-case spam is avoided because that notifier only fires after every
    # AIExecutionRecord under the same batch_id reaches a terminal status.
    batch_id = uuid.uuid4()
    totals = {'passed': 0, 'failed': 0, 'stopped': 0}
    emit({'event': 'started', 'batch_id': str(batch_id), 'target': 'web', 'total': len(cases)})

    previous_was_article = False
    for index, case in enumerate(cases, 1):
        article_case = is_article_case(case)
        if article_case and previous_was_article and args.article_delay > 0:
            time.sleep(args.article_delay)
        previous_was_article = article_case

        task_description = case.web_task_description if case.execution_target == 'dual' else case.task_description
        record = AIExecutionRecord.objects.create(
            project=case.project,
            ai_case=case,
            case_name=case.name,
            task_description=task_description,
            execution_target='web',
            batch_id=batch_id,
            batch_run_mode='sequential',
            status='running',
            logs='Full browser regression started.\n',
        )
        emit({'event': 'case_started', 'index': index, 'total': len(cases), 'case_id': case.id, 'record_id': record.id, 'name': case.name})
        try:
            _run_ai_case_with_target(record, case, lambda: False, execution_target='web')
            record.refresh_from_db()
        except Exception as exc:
            record.status = 'failed'
            record.logs += f'\n[Full browser regression] Unhandled runner error: {exc}\n'
            record.save(update_fields=['status', 'logs'])
        status = record.status if record.status in totals else 'failed'
        totals[status] += 1
        emit({'event': 'case_finished', 'index': index, 'total': len(cases), 'case_id': case.id, 'record_id': record.id, 'name': case.name, 'status': status})

    emit({'event': 'finished', 'batch_id': str(batch_id), 'target': 'web', 'total': len(cases), **totals})

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

"""Run AI cases serially on the local Playwright executor."""
import threading

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.ui_automation.models import AICase, AIExecutionRecord, SetupTemplate
from apps.ui_automation.views._helpers import STOP_SIGNALS
from apps.ui_automation.views.ai import _run_ai_case_with_target


def _task_snapshot_for_target(case, execution_target):
    """Return the immutable case variant selected for this execution record."""
    target = str(execution_target or '').lower()
    if target == 'desktop':
        return str(getattr(case, 'desktop_task_description', '') or case.task_description or '')
    if target == 'web':
        return str(getattr(case, 'web_task_description', '') or case.task_description or '')
    return str(case.task_description or '')


class Command(BaseCommand):
    help = 'Run AI cases serially and persist one execution record per case.'

    def add_arguments(self, parser):
        parser.add_argument('--case-ids', nargs='*', type=int, help='Optional AI case IDs to run.')
        parser.add_argument('--template-id', type=int, default=2, help='Fallback setup template for cases without one.')
        parser.add_argument('--case-timeout', type=int, default=90, help='Maximum seconds per case before moving on.')
        parser.add_argument(
            '--execution-target',
            choices=['auto', 'web', 'desktop'],
            default='auto',
            help='Execution backend. auto uses the case target; dual-mode cases default to web.',
        )

    def handle(self, *args, **options):
        case_ids = options.get('case_ids') or []
        cases = AICase.objects.order_by('id')
        if case_ids:
            cases = cases.filter(id__in=case_ids)
        cases = list(cases.select_related('project', 'setup_template'))
        if not cases:
            raise CommandError('No AI cases found.')

        fallback_template = SetupTemplate.objects.filter(id=options['template_id']).first()
        user = get_user_model().objects.filter(is_superuser=True).first() or get_user_model().objects.first()
        results = []
        total = len(cases)
        requested_target = options['execution_target']

        for index, case in enumerate(cases, 1):
            setup_template = case.setup_template or fallback_template
            execution_target = requested_target
            if execution_target == 'auto':
                execution_target = 'web' if case.execution_target == 'dual' else (case.execution_target or 'web')
            task_snapshot = _task_snapshot_for_target(case, execution_target)
            record = AIExecutionRecord.objects.create(
                project=case.project,
                ai_case=case,
                case_name=case.name,
                task_description=task_snapshot,
                execution_target=execution_target,
                status='running',
                executed_by=user,
                logs=f'本机串行回归 {index}/{total} 开始。\n',
            )
            self.stdout.write(f'[{index}/{total}] case={case.id} record={record.id} started')
            STOP_SIGNALS[record.id] = False
            timer = threading.Timer(options['case_timeout'], lambda: STOP_SIGNALS.__setitem__(record.id, True))
            timer.daemon = True
            timer.start()
            try:
                _run_ai_case_with_target(
                    record,
                    case,
                    should_stop=lambda record_id=record.id: STOP_SIGNALS.get(record_id, False),
                    execution_target=execution_target,
                )
            except Exception as exc:
                record.status = 'failed'
                record.logs += f'\n串行回归执行异常: {exc}'
                record.save(update_fields=['status', 'logs'])
            finally:
                timer.cancel()
                STOP_SIGNALS.pop(record.id, None)

            record.refresh_from_db()
            results.append((case.id, record.id, record.status))
            self.stdout.write(f'[{index}/{total}] case={case.id} record={record.id} {record.status}')

        passed = sum(status == 'passed' for _, _, status in results)
        failed = sum(status != 'passed' for _, _, status in results)
        self.stdout.write(self.style.SUCCESS(
            f'Finished: total={total}, passed={passed}, failed={failed}'
        ))

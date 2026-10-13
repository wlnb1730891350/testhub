from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection, transaction

from apps.ui_automation.models import AIExecutionRecord


class Command(BaseCommand):
    help = 'Remove old AI execution GIF/screenshots and clear their media references.'

    def add_arguments(self, parser):
        parser.add_argument('--keep-latest', type=int, default=100)
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument(
            '--skip-binlog',
            action='store_true',
            help='For a verified single-node local MySQL maintenance run only.',
        )
        parser.add_argument(
            '--compact',
            action='store_true',
            help='Rebuild the execution record table after cleanup to return freed space to the filesystem.',
        )

    def handle(self, *args, **options):
        keep_latest = max(0, options['keep_latest'])
        dry_run = options['dry_run']
        compact = options['compact']
        if compact and (dry_run or not options['skip_binlog']):
            raise CommandError('--compact requires --skip-binlog on a verified single-node local MySQL instance.')
        if options['skip_binlog'] and not dry_run:
            with connection.cursor() as cursor:
                cursor.execute('SET SESSION sql_log_bin = 0')
        media_dir = Path(settings.MEDIA_ROOT) / 'ui_automation' / 'ai_execution'
        if not media_dir.exists():
            self.stdout.write('AI execution media directory does not exist.')
            return

        protected_ids = set(
            AIExecutionRecord.objects.filter(status__in=['running', 'pending'])
            .values_list('id', flat=True)
        )
        recent_ids = set(
            AIExecutionRecord.objects.exclude(status__in=['running', 'pending'])
            .order_by('-end_time', '-start_time', '-id')
            .values_list('id', flat=True)[:keep_latest]
        )
        protected_ids.update(recent_ids)

        removed_ids = []
        removed_orphans = []
        reclaimed_bytes = 0
        for directory in media_dir.iterdir():
            if not directory.is_dir():
                continue
            try:
                record_id = int(directory.name)
            except ValueError:
                continue
            if record_id in protected_ids:
                continue
            directory_size = sum(item.stat().st_size for item in directory.rglob('*') if item.is_file())
            reclaimed_bytes += directory_size
            if not dry_run:
                import shutil
                shutil.rmtree(directory)
            if AIExecutionRecord.objects.filter(id=record_id).exists():
                removed_ids.append(record_id)
            else:
                removed_orphans.append(record_id)

        stale_media_ids = set()
        if not dry_run:
            records_with_media = AIExecutionRecord.objects.exclude(
                status__in=['running', 'pending']
            ).exclude(gif_path__isnull=True).exclude(gif_path='').only('id')
            stale_media_ids = {
                record.id for record in records_with_media
                if not (media_dir / str(record.id)).exists()
            }

        metadata_ids = set(removed_ids).union(stale_media_ids)
        metadata_warning = ''
        if metadata_ids and not dry_run:
            try:
                # Keep MySQL temporary-file use bounded. This table contains
                # large JSON report columns, so one massive UPDATE can exhaust
                # the server's temporary workspace even after media is freed.
                ordered_ids = sorted(metadata_ids)
                for start in range(0, len(ordered_ids), 10):
                    with transaction.atomic():
                        AIExecutionRecord.objects.filter(id__in=ordered_ids[start:start + 10]).update(
                            gif_path=None,
                            screenshots_sequence=[],
                        )
            except DatabaseError as exc:
                # Media reclamation must not fail merely because MySQL is
                # temporarily restarting. The next scheduled run will retry
                # metadata cleanup; files have already been removed safely.
                metadata_warning = f' Database metadata was not updated: {str(exc)[:180]}'

        inline_screenshot_records = 0
        inline_screenshot_warning = ''
        if not dry_run:
            try:
                records = AIExecutionRecord.objects.exclude(
                    status__in=['running', 'pending']
                ).only('id', 'steps_completed').order_by('id').iterator(chunk_size=20)
                for record in records:
                    steps = record.steps_completed or []
                    cleaned_steps = [
                        {key: value for key, value in step.items() if key != 'screenshot'}
                        for step in steps
                        if isinstance(step, dict)
                    ]
                    if cleaned_steps != steps:
                        AIExecutionRecord.objects.filter(id=record.id).update(
                            steps_completed=cleaned_steps,
                        )
                        inline_screenshot_records += 1
            except DatabaseError as exc:
                inline_screenshot_warning = (
                    f' Inline screenshot metadata was not cleaned: {str(exc)[:180]}'
                )

        compact_result = ''
        if compact:
            try:
                with connection.cursor() as cursor:
                    cursor.execute('OPTIMIZE TABLE ui_ai_execution_records')
                    compact_result = f' Table compaction: {cursor.fetchall()}.'
            except DatabaseError as exc:
                compact_result = f' Table compaction failed: {str(exc)[:180]}.'

        mode = 'Would remove' if dry_run else 'Removed'
        self.stdout.write(
            f'{mode} {len(removed_ids)} execution directories and {len(removed_orphans)} orphan directories; '
            f'reclaimed approximately {reclaimed_bytes / 1024 / 1024:.1f} MB. '
            f'Keeping {keep_latest} latest completed records and all active records. '
            f'Cleared {len(metadata_ids)} stale media references and '
            f'{inline_screenshot_records} inline screenshot records.'
            f'{metadata_warning}{inline_screenshot_warning}{compact_result}'
        )

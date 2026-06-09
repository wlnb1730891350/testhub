"""
Core application views.
"""
from datetime import timedelta
import logging

from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.api_testing.models import ScheduledTask as ApiScheduledTask
from apps.api_testing.models import TestExecution as ApiTestExecution
from apps.app_automation.models import AppScheduledTask, AppTestExecution
from apps.executions.models import TestRun
from apps.projects.models import Project
from apps.reports.models import TestReport
from apps.requirement_analysis.models import GeneratedTestCase, RequirementDocument, TestCaseGenerationTask
from apps.reviews.models import TestCaseReview
from apps.ui_automation.models import TestExecution as UiTestExecution
from apps.ui_automation.models import UiScheduledTask

from .models import UnifiedNotificationConfig
from .serializers import UnifiedNotificationConfigSerializer

logger = logging.getLogger(__name__)


class UnifiedNotificationConfigViewSet(viewsets.ModelViewSet):
    """Unified notification configuration view set."""

    queryset = UnifiedNotificationConfig.objects.all()
    serializer_class = UnifiedNotificationConfigSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['config_type', 'is_default', 'is_active']
    search_fields = ['name']
    ordering_fields = ['created_at']
    ordering = ['-created_at']

    def perform_create(self, serializer):
        instance = serializer.save(created_by=self.request.user)
        logger.info("Created unified notification config: %s", instance.name)

    def perform_update(self, serializer):
        instance = serializer.save()
        logger.info("Updated unified notification config: %s", instance.name)

    def perform_destroy(self, instance):
        logger.info("Deleted unified notification config: %s", instance.name)
        instance.delete()

    @action(detail=True, methods=['post'])
    def set_default(self, request, pk=None):
        config = self.get_object()
        UnifiedNotificationConfig.objects.filter(is_default=True).update(is_default=False)
        config.is_default = True
        config.save()
        return Response({'message': '已设置为默认配置'})

    @action(detail=False, methods=['get'])
    def active_configs(self, request):
        configs = UnifiedNotificationConfig.objects.filter(is_active=True)
        serializer = self.get_serializer(configs, many=True)
        return Response(serializer.data)


class WorkspaceViewSet(viewsets.ViewSet):
    """Aggregated workspace dashboard data."""

    permission_classes = [IsAuthenticated]

    def list(self, request):
        now = timezone.now()
        seven_days_ago = now - timedelta(days=7)

        metrics = {
            'project_count': Project.objects.count(),
            'active_project_count': Project.objects.filter(status='active').count(),
            'requirement_doc_count': RequirementDocument.objects.count(),
            'generated_case_count': GeneratedTestCase.objects.count(),
            'pending_review_count': TestCaseReview.objects.filter(status__in=['pending', 'in_progress']).count(),
            'report_count': TestReport.objects.count(),
            'active_schedule_count': self._active_schedule_count(),
            'execution_lane_count': 4,
            'module_count': 8,
        }

        focus = {
            'recent_generation_count': TestCaseGenerationTask.objects.filter(created_at__gte=seven_days_ago).count(),
            'recent_execution_count': self._recent_execution_count(seven_days_ago),
            'recent_report_count': TestReport.objects.filter(created_at__gte=seven_days_ago).count(),
            'api_execution_count': ApiTestExecution.objects.count(),
            'ui_execution_count': UiTestExecution.objects.count(),
            'app_execution_count': AppTestExecution.objects.count(),
            'manual_run_count': TestRun.objects.count(),
        }

        health = {
            'ai_asset_pipeline': 'enabled' if metrics['generated_case_count'] > 0 else 'building',
            'reporting_center': 'healthy' if metrics['report_count'] > 0 else 'needs_attention',
            'orchestration_center': 'healthy' if metrics['active_schedule_count'] > 0 else 'building',
        }

        return Response({
            'metrics': metrics,
            'focus': focus,
            'health': health,
            'recent_activities': self._build_recent_activities(limit=10),
        })

    @action(detail=False, methods=['get'], url_path='system-health')
    def system_health(self, request):
        """Return real-time system health status for all services."""
        import time
        from django.db import connection
        services = []
        # Database health
        db_start = time.time()
        db_ok = False
        db_msg = ''
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
            db_ok = True
            db_msg = 'MySQL ok'
        except Exception as e:
            db_msg = f'MySQL error: {str(e)[:80]}'
        db_latency = round((time.time() - db_start) * 1000, 1)
        services.append({
            'name': 'MySQL Database',
            'status': 'healthy' if db_ok else 'error',
            'latency_ms': db_latency,
            'message': db_msg,
        })
        # AI Model availability
        try:
            from apps.requirement_analysis.models import AIModelConfig
            active_models = AIModelConfig.objects.filter(is_active=True).count()
            services.append({
                'name': 'AI Models',
                'status': 'healthy' if active_models > 0 else 'warning',
                'latency_ms': 0,
                'message': f'{active_models} models configured',
            })
        except Exception as e:
            services.append({
                'name': 'AI Models',
                'status': 'error',
                'latency_ms': 0,
                'message': f'Config query failed: {str(e)[:80]}',
            })
        # Celery worker health
        try:
            from backend.celery import app as celery_app
            inspect = celery_app.control.inspect(timeout=1.0)
            active_workers = inspect.active_queues()
            worker_count = len(active_workers) if active_workers else 0
            services.append({
                'name': 'Celery Worker',
                'status': 'healthy' if worker_count > 0 else 'warning',
                'latency_ms': 0,
                'message': f'{worker_count} workers online' if worker_count > 0 else 'No workers online',
            })
        except Exception:
            services.append({
                'name': 'Celery Worker',
                'status': 'warning',
                'latency_ms': 0,
                'message': 'Cannot check Celery status',
            })
        # Disk space
        try:
            import shutil
            total, used, free = shutil.disk_usage('C:\\')
            free_gb = round(free / (1024**3), 1)
            usage_pct = round(used / total * 100, 1)
            services.append({
                'name': 'Disk Space',
                'status': 'healthy' if usage_pct < 85 else ('warning' if usage_pct < 95 else 'error'),
                'latency_ms': 0,
                'message': f'{usage_pct}% used, {free_gb}GB free',
            })
        except Exception:
            services.append({
                'name': 'Disk Space',
                'status': 'unknown',
                'latency_ms': 0,
                'message': 'Cannot check disk info',
            })
        statuses = [s['status'] for s in services]
        if 'error' in statuses:
            overall = 'error'
        elif 'warning' in statuses:
            overall = 'warning'
        else:
            overall = 'healthy'
        return Response({
            'overall': overall,
            'services': services,
            'timestamp': timezone.now().isoformat(),
        })

    @action(detail=False, methods=['get'])
    def report_center(self, request):
        current_module = request.query_params.get('module', 'all')
        current_status = request.query_params.get('status', 'all')
        keyword = request.query_params.get('q', '').strip().lower()

        recent_reports = [
            {
                'id': report.id,
                'type': 'manual_report',
                'channel_key': 'manual',
                'title': report.name,
                'status': report.report_type,
                'module': 'Manual Reports',
                'route': '/ai-generation/reports',
                'created_at': report.created_at.isoformat(),
            }
            for report in TestReport.objects.select_related('project').order_by('-created_at')[:6]
        ]

        recent_api = [
            {
                'id': execution.id,
                'type': 'api',
                'channel_key': 'api',
                'title': execution.test_suite.name if execution.test_suite else f'API Execution #{execution.id}',
                'status': execution.status,
                'module': 'API Testing',
                'route': '/api-testing/reports',
                'created_at': execution.created_at.isoformat(),
                'total': execution.total_requests,
                'passed': execution.passed_requests,
                'failed': execution.failed_requests,
            }
            for execution in ApiTestExecution.objects.select_related('test_suite').order_by('-created_at')[:6]
        ]

        recent_ui = [
            {
                'id': execution.id,
                'type': 'ui',
                'channel_key': 'ui',
                'title': execution.test_suite.name if execution.test_suite else f'UI Execution #{execution.id}',
                'status': execution.status,
                'module': 'UI Automation',
                'route': '/ui-automation/reports',
                'created_at': execution.created_at.isoformat(),
                'total': execution.total_cases,
                'passed': execution.passed_cases,
                'failed': execution.failed_cases,
            }
            for execution in UiTestExecution.objects.select_related('test_suite').order_by('-created_at')[:6]
        ]

        recent_app = [
            {
                'id': execution.id,
                'type': 'app',
                'channel_key': 'app',
                'title': execution.case_name or f'APP Execution #{execution.id}',
                'status': execution.status,
                'module': 'APP Automation',
                'route': '/app-automation/reports',
                'created_at': execution.created_at.isoformat(),
                'total': execution.total_steps,
                'passed': execution.passed_steps,
                'failed': execution.failed_steps,
            }
            for execution in AppTestExecution.objects.order_by('-created_at')[:6]
        ]

        recent_manual_runs = [
            {
                'id': run.id,
                'type': 'manual_execution',
                'channel_key': 'execution',
                'title': run.name,
                'status': run.status,
                'module': 'Manual Execution',
                'route': '/ai-generation/executions',
                'created_at': run.created_at.isoformat(),
                'total': run.progress_stats.get('total', 0),
                'passed': run.progress_stats.get('passed', 0),
                'failed': run.progress_stats.get('failed', 0),
            }
            for run in TestRun.objects.order_by('-created_at')[:6]
        ]

        merged_reports = sorted(
            recent_reports + recent_api + recent_ui + recent_app + recent_manual_runs,
            key=lambda item: item['created_at'],
            reverse=True
        )
        filtered_reports = self._filter_workspace_items(
            merged_reports,
            current_module=current_module,
            current_status=current_status,
            keyword=keyword,
            text_key='title'
        )[:16]

        return Response({
            'summary': {
                'manual_reports': TestReport.objects.count(),
                'api_reports': ApiTestExecution.objects.count(),
                'ui_reports': UiTestExecution.objects.count(),
                'app_reports': AppTestExecution.objects.count(),
                'manual_executions': TestRun.objects.count(),
            },
            'channels': [
                {
                    'key': 'manual',
                    'label': 'Manual Reports',
                    'count': TestReport.objects.count(),
                    'route': '/ai-generation/reports',
                },
                {
                    'key': 'api',
                    'label': 'API Testing',
                    'count': ApiTestExecution.objects.count(),
                    'route': '/api-testing/reports',
                },
                {
                    'key': 'ui',
                    'label': 'UI Automation',
                    'count': UiTestExecution.objects.count(),
                    'route': '/ui-automation/reports',
                },
                {
                    'key': 'app',
                    'label': 'APP Automation',
                    'count': AppTestExecution.objects.count(),
                    'route': '/app-automation/reports',
                },
                {
                    'key': 'execution',
                    'label': 'Manual Execution',
                    'count': TestRun.objects.count(),
                    'route': '/ai-generation/executions',
                },
            ],
            'filters': {
                'current': {
                    'module': current_module,
                    'status': current_status,
                    'q': keyword,
                },
                'available_modules': ['all', 'manual', 'api', 'ui', 'app', 'execution'],
                'available_statuses': self._collect_statuses(merged_reports),
            },
            'recent_reports': filtered_reports,
        })

    @action(detail=False, methods=['get'])
    def scheduler_center(self, request):
        current_module = request.query_params.get('module', 'all')
        current_status = request.query_params.get('status', 'all')
        keyword = request.query_params.get('q', '').strip().lower()

        api_tasks = list(ApiScheduledTask.objects.order_by('-created_at')[:8])
        ui_tasks = list(UiScheduledTask.objects.order_by('-created_at')[:8])
        app_tasks = list(AppScheduledTask.objects.order_by('-created_at')[:8])

        channels = [
            {
                'key': 'api',
                'label': 'API Testing',
                'count': ApiScheduledTask.objects.count(),
                'active_count': ApiScheduledTask.objects.filter(status='ACTIVE').count(),
                'route': '/api-testing/scheduled-tasks',
            },
            {
                'key': 'ui',
                'label': 'UI Automation',
                'count': UiScheduledTask.objects.count(),
                'active_count': UiScheduledTask.objects.filter(status='ACTIVE').count(),
                'route': '/ui-automation/scheduled-tasks',
            },
            {
                'key': 'app',
                'label': 'APP Automation',
                'count': AppScheduledTask.objects.count(),
                'active_count': AppScheduledTask.objects.filter(status='ACTIVE').count(),
                'route': '/app-automation/scheduled-tasks',
            },
        ]

        recent_tasks = []
        recent_tasks.extend(self._serialize_scheduler_items(api_tasks, 'api', 'API Testing', '/api-testing/scheduled-tasks'))
        recent_tasks.extend(self._serialize_scheduler_items(ui_tasks, 'ui', 'UI Automation', '/ui-automation/scheduled-tasks'))
        recent_tasks.extend(self._serialize_scheduler_items(app_tasks, 'app', 'APP Automation', '/app-automation/scheduled-tasks'))
        recent_tasks.sort(key=lambda item: item['created_at'], reverse=True)
        filtered_tasks = self._filter_workspace_items(
            recent_tasks,
            current_module=current_module,
            current_status=current_status,
            keyword=keyword,
            text_key='name'
        )[:18]

        return Response({
            'summary': {
                'total_tasks': sum(item['count'] for item in channels),
                'active_tasks': sum(item['active_count'] for item in channels),
                'paused_tasks': (
                    ApiScheduledTask.objects.filter(status='PAUSED').count()
                    + UiScheduledTask.objects.filter(status='PAUSED').count()
                    + AppScheduledTask.objects.filter(status='PAUSED').count()
                ),
                'failed_tasks': (
                    ApiScheduledTask.objects.filter(status='FAILED').count()
                    + UiScheduledTask.objects.filter(status='FAILED').count()
                    + AppScheduledTask.objects.filter(status='FAILED').count()
                ),
            },
            'channels': channels,
            'filters': {
                'current': {
                    'module': current_module,
                    'status': current_status,
                    'q': keyword,
                },
                'available_modules': ['all', 'api', 'ui', 'app'],
                'available_statuses': self._collect_statuses(recent_tasks),
            },
            'recent_tasks': filtered_tasks,
        })

    def _active_schedule_count(self):
        return (
            ApiScheduledTask.objects.filter(status='ACTIVE').count()
            + UiScheduledTask.objects.filter(status='ACTIVE').count()
            + AppScheduledTask.objects.filter(status='ACTIVE').count()
        )

    def _recent_execution_count(self, since):
        return (
            ApiTestExecution.objects.filter(created_at__gte=since).count()
            + UiTestExecution.objects.filter(created_at__gte=since).count()
            + AppTestExecution.objects.filter(created_at__gte=since).count()
            + TestRun.objects.filter(created_at__gte=since).count()
        )

    def _build_recent_activities(self, limit=10):
        items = []

        for task in TestCaseGenerationTask.objects.order_by('-created_at')[:4]:
            items.append({
                'type': 'requirement',
                'title': task.title,
                'status': task.status,
                'time': task.created_at,
                'route': f'/ai-generation/task-detail/{task.task_id}',
                'module': 'AI Generation',
            })

        for execution in ApiTestExecution.objects.select_related('test_suite').order_by('-created_at')[:3]:
            items.append({
                'type': 'api_execution',
                'title': execution.test_suite.name if execution.test_suite else 'API Execution',
                'status': execution.status,
                'time': execution.created_at,
                'route': '/api-testing/reports',
                'module': 'API Testing',
            })

        for execution in UiTestExecution.objects.select_related('test_suite').order_by('-created_at')[:3]:
            items.append({
                'type': 'ui_execution',
                'title': execution.test_suite.name if execution.test_suite else 'UI Execution',
                'status': execution.status,
                'time': execution.created_at,
                'route': '/ui-automation/executions',
                'module': 'UI Automation',
            })

        for execution in AppTestExecution.objects.select_related('test_case').order_by('-created_at')[:3]:
            items.append({
                'type': 'app_execution',
                'title': execution.case_name or 'APP Execution',
                'status': execution.status,
                'time': execution.created_at,
                'route': '/app-automation/executions',
                'module': 'APP Automation',
            })

        for report in TestReport.objects.select_related('project').order_by('-created_at')[:3]:
            items.append({
                'type': 'report',
                'title': report.name,
                'status': report.report_type,
                'time': report.created_at,
                'route': '/ui-automation/reports',
                'module': 'Reports',
            })

        items.sort(key=lambda item: item['time'], reverse=True)
        return [{**item, 'time': item['time'].isoformat()} for item in items[:limit]]

    def _serialize_scheduler_items(self, tasks, channel_key, module_name, route):
        items = []
        for task in tasks:
            items.append({
                'id': task.id,
                'name': task.name,
                'channel_key': channel_key,
                'status': task.status,
                'trigger_type': task.trigger_type,
                'next_run_time': task.next_run_time.isoformat() if task.next_run_time else None,
                'last_run_time': task.last_run_time.isoformat() if task.last_run_time else None,
                'created_at': task.created_at.isoformat(),
                'total_runs': task.total_runs,
                'successful_runs': task.successful_runs,
                'failed_runs': task.failed_runs,
                'module': module_name,
                'route': route,
            })
        return items

    def _filter_workspace_items(self, items, current_module='all', current_status='all', keyword='', text_key='title'):
        filtered = items

        if current_module and current_module != 'all':
            filtered = [item for item in filtered if item.get('channel_key') == current_module]

        if current_status and current_status != 'all':
            target_status = current_status.lower()
            filtered = [item for item in filtered if str(item.get('status', '')).lower() == target_status]

        if keyword:
            filtered = [item for item in filtered if keyword in str(item.get(text_key, '')).lower()]

        return filtered

    def _collect_statuses(self, items):
        statuses = sorted({str(item.get('status')) for item in items if item.get('status')})
        return ['all', *statuses]

import json
import os
import threading

from django.conf import settings
from django.db import models
from django.http import FileResponse, HttpResponse
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .executor import PerformanceTestExecutor, run_performance_execution, stop_execution_process
from .jmx_builder import JMeterPlanBuilder, UploadedJMXPlanBuilder, default_script_config, normalize_config
from .jmx_importer import JMXImporter, JMXImportError
from .models import PerformanceDataset, PerformanceExecution, PerformanceProject, PerformanceScript
from .realtime_report import get_realtime_report_config, query_realtime_report
from .serializers import (
    PerformanceDatasetSerializer,
    PerformanceExecutionSerializer,
    PerformanceProjectSerializer,
    PerformanceScriptSerializer,
    inspect_csv_dataset,
)


class AccessMixin:
    def accessible_projects(self):
        user = self.request.user
        return PerformanceProject.objects.filter(models.Q(owner=user) | models.Q(members=user)).distinct()


class PerformanceDashboardViewSet(AccessMixin, viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['get'])
    def stats(self, request):
        projects = self.accessible_projects()
        scripts = PerformanceScript.objects.filter(project__in=projects)
        executions = PerformanceExecution.objects.filter(project__in=projects)
        latest = executions.order_by('-created_at')[:10]
        return Response({
            'project_count': projects.count(),
            'script_count': scripts.count(),
            'execution_count': executions.count(),
            'running_count': executions.filter(status='RUNNING').count(),
            'failed_count': executions.filter(status='FAILED').count(),
            'latest_executions': PerformanceExecutionSerializer(latest, many=True).data,
        })

    @action(detail=False, methods=['get'], url_path='jmeter-health')
    def jmeter_health(self, request):
        from .executor import PerformanceTestExecutor

        executor = PerformanceTestExecutor()
        command = executor._find_jmeter_command()
        realtime_report = getattr(settings, 'PERFORMANCE_REALTIME_REPORT', {}) or {}
        return Response({
            'available': bool(command),
            'command': command or '',
            'execution_mode': getattr(settings, 'PERFORMANCE_EXECUTION_MODE', 'thread'),
            'realtime_report': {
                'enabled': bool(realtime_report.get('enabled')),
                'url': realtime_report.get('write_url') or realtime_report.get('url') or '',
                'database': realtime_report.get('database') or '',
                'bucket': realtime_report.get('bucket') or '',
                'org': realtime_report.get('org') or realtime_report.get('org_id') or '',
                'measurement': realtime_report.get('measurement') or '',
            },
            'message': 'JMeter 可用' if command else '未找到 JMeter，请配置 JMETER_BIN_PATH 或 JMETER_HOME',
        })


class PerformanceProjectViewSet(AccessMixin, viewsets.ModelViewSet):
    serializer_class = PerformanceProjectSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'description']
    ordering_fields = ['created_at', 'name']
    ordering = ['-created_at']

    def get_queryset(self):
        return self.accessible_projects()

    def perform_destroy(self, instance):
        instance.delete()


class PerformanceScriptViewSet(AccessMixin, viewsets.ModelViewSet):
    serializer_class = PerformanceScriptSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['project', 'script_type', 'status', 'is_active']
    search_fields = ['name', 'description']
    ordering_fields = ['created_at', 'updated_at', 'name']
    ordering = ['-updated_at']

    def get_queryset(self):
        return PerformanceScript.objects.filter(project__in=self.accessible_projects()).select_related('project', 'created_by')

    @action(detail=True, methods=['post'])
    def execute(self, request, pk=None):
        script = self.get_object()
        executor = PerformanceTestExecutor()
        jmeter_command = executor._find_jmeter_command()
        if not jmeter_command:
            return Response({
                'error': '未找到 JMeter 可执行文件，请配置 JMETER_BIN_PATH 或 JMETER_HOME',
            }, status=status.HTTP_400_BAD_REQUEST)

        execution = PerformanceExecution.objects.create(
            project=script.project,
            script=script,
            status='QUEUED',
            executed_by=request.user,
        )

        thread = threading.Thread(
            target=run_performance_execution,
            args=(execution.id,),
            name=f'performance-execution-{execution.id}',
            daemon=True,
        )
        thread.start()
        task_id = f'thread-{thread.ident or execution.id}'

        execution.task_id = task_id or ''
        execution.save(update_fields=['task_id'])
        return Response(PerformanceExecutionSerializer(execution).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=['get'], url_path='export-jmx')
    def export_jmx(self, request, pk=None):
        script = self.get_object()
        if script.script_type == 'JMX_UPLOAD' and script.original_jmx:
            with script.original_jmx.open('rb') as handle:
                content = UploadedJMXPlanBuilder(
                    handle.read(),
                    script.config,
                    testname=script.name,
                    realtime_config=get_realtime_report_config(test_title=script.name),
                ).build_string()
            return self._jmx_response(content, script.name)

        config = normalize_config(script.config, base_url=script.project.base_url)
        content = JMeterPlanBuilder(
            config,
            testname=script.name,
            base_url=script.project.base_url,
            realtime_config=get_realtime_report_config(test_title=script.name),
        ).build_string()
        return self._jmx_response(content, script.name)

    @action(detail=True, methods=['post'], url_path='upload-jmx')
    def upload_jmx(self, request, pk=None):
        script = self.get_object()
        upload = request.FILES.get('file')
        if not upload:
            return Response({'error': '请上传 JMX 文件'}, status=status.HTTP_400_BAD_REQUEST)

        raw = upload.read()
        content = raw.decode('utf-8-sig', errors='ignore')
        upload.seek(0)
        try:
            parsed = JMXImporter().parse(content)
        except JMXImportError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        script.original_jmx = upload
        script.config = parsed['config']
        script.import_warnings = parsed['warnings']
        script.script_type = 'JMX_UPLOAD'
        script.status = 'ready'
        script.version += 1
        script.save(update_fields=[
            'original_jmx', 'config', 'import_warnings',
            'script_type', 'status', 'version', 'updated_at',
        ])
        return Response(PerformanceScriptSerializer(script, context={'request': request}).data)

    @action(detail=False, methods=['post'], url_path='export-jmx')
    def export_current_jmx(self, request):
        config = request.data.get('config') or {}
        name = request.data.get('name') or 'test_plan'
        project_id = request.data.get('project')
        base_url = request.data.get('base_url') or ''

        if project_id:
            try:
                project = self.accessible_projects().get(id=project_id)
                base_url = project.base_url
            except PerformanceProject.DoesNotExist:
                return Response({'error': '项目不存在或无权限'}, status=status.HTTP_404_NOT_FOUND)

        if not isinstance(config, dict):
            return Response({'error': '缺少可导出的编排配置'}, status=status.HTTP_400_BAD_REQUEST)

        normalized = normalize_config(config, base_url=base_url)
        content = JMeterPlanBuilder(
            normalized,
            testname=name,
            base_url=base_url,
            realtime_config=get_realtime_report_config(test_title=name),
        ).build_string()
        return self._jmx_response(content, name)

    @action(detail=False, methods=['get'], url_path='default-config')
    def default_config(self, request):
        return Response(default_script_config(request.query_params.get('base_url', '')))

    def _jmx_response(self, content, name):
        raw_name = name or 'test_plan'
        if not raw_name.lower().endswith('.jmx'):
            raw_name = f'{raw_name}.jmx'
        filename = ''.join(
            char if char.isalnum() or char in ('-', '_', '.') else '_'
            for char in raw_name
        )
        response = HttpResponse(content, content_type='application/xml; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


class PerformanceDatasetViewSet(AccessMixin, viewsets.ModelViewSet):
    serializer_class = PerformanceDatasetSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['project']
    search_fields = ['name', 'description']
    ordering = ['-created_at']

    def get_queryset(self):
        return PerformanceDataset.objects.filter(project__in=self.accessible_projects()).select_related('project', 'created_by')

    def perform_create(self, serializer):
        instance = serializer.save(created_by=self.request.user)
        variables, row_count = inspect_csv_dataset(instance)
        instance.variables = variables
        instance.row_count = row_count
        instance.save(update_fields=['variables', 'row_count'])


class PerformanceExecutionViewSet(AccessMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = PerformanceExecutionSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['project', 'script', 'status', 'report_status']
    search_fields = ['script__name', 'project__name']
    ordering = ['-created_at']

    def get_queryset(self):
        user = self.request.user
        return PerformanceExecution.objects.filter(
            models.Q(project__in=self.accessible_projects()) | models.Q(executed_by=user)
        ).select_related('project', 'script', 'executed_by').distinct()

    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        execution = self.get_object()
        if execution.status not in ('QUEUED', 'RUNNING'):
            return Response({'message': '当前执行记录不在运行状态'})
        stopped = stop_execution_process(execution.jmeter_pid)
        execution.status = 'CANCELLED'
        execution.finished_at = timezone.now()
        if execution.started_at:
            execution.duration = (execution.finished_at - execution.started_at).total_seconds()
        execution.error_message = '用户手动停止' if stopped else '停止请求已提交，但未确认进程状态'
        execution.save(update_fields=['status', 'finished_at', 'duration', 'error_message'])
        return Response(PerformanceExecutionSerializer(execution).data)

    @action(detail=True, methods=['get'], url_path='realtime-report')
    def realtime_report(self, request, pk=None):
        execution = self.get_object()
        return Response(query_realtime_report(
            execution,
            window=request.query_params.get('window', ''),
        ))

    @action(detail=True, methods=['get'], url_path='download-jtl')
    def download_jtl(self, request, pk=None):
        execution = self.get_object()
        return self._download_file(execution.jtl_path, f'performance_execution_{execution.id}.jtl')

    @action(detail=True, methods=['get'], url_path='download-jmx')
    def download_jmx(self, request, pk=None):
        execution = self.get_object()
        return self._download_file(execution.jmx_path, f'performance_execution_{execution.id}.jmx')

    def _download_file(self, path, filename):
        if not path or not os.path.exists(path):
            return Response({'error': '文件不存在'}, status=status.HTTP_404_NOT_FOUND)
        response = FileResponse(open(path, 'rb'), as_attachment=True, filename=filename)
        return response


class JMXImportPreviewView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        upload = request.FILES.get('file')
        content = request.data.get('content')
        filename = ''
        if upload:
            filename = upload.name
            raw = upload.read()
            content = raw.decode('utf-8-sig', errors='ignore')
            upload.seek(0)
        if not content:
            return Response({'error': '请上传 JMX 文件或提供 JMX 内容'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            result = JMXImporter().parse(content)
            result['filename'] = filename
            return Response(result)
        except JMXImportError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class JMXImportConfirmView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        project_id = request.data.get('project_id')
        name = request.data.get('name') or '导入JMX脚本'
        description = request.data.get('description') or ''
        script_type = request.data.get('script_type') or request.data.get('import_mode') or 'JMX_UPLOAD'
        config = request.data.get('config')
        warnings = request.data.get('warnings') or []

        if script_type not in ('ONLINE', 'JMX_UPLOAD'):
            return Response({'error': '不支持的 JMX 导入方式'}, status=status.HTTP_400_BAD_REQUEST)

        if isinstance(config, str):
            try:
                config = json.loads(config)
            except json.JSONDecodeError:
                config = None
        if isinstance(warnings, str):
            try:
                warnings = json.loads(warnings)
            except json.JSONDecodeError:
                warnings = [warnings] if warnings else []

        try:
            project = PerformanceProject.objects.get(
                models.Q(owner=request.user) | models.Q(members=request.user),
                id=project_id,
            )
        except PerformanceProject.DoesNotExist:
            return Response({'error': '项目不存在或无权限'}, status=status.HTTP_404_NOT_FOUND)

        upload = request.FILES.get('file')
        if not config and upload:
            raw = upload.read()
            content = raw.decode('utf-8-sig', errors='ignore')
            upload.seek(0)
            try:
                parsed = JMXImporter().parse(content)
                config = parsed['config']
                warnings = parsed['warnings']
            except JMXImportError as exc:
                return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if not isinstance(config, dict):
            return Response({'error': '缺少可保存的编排配置'}, status=status.HTTP_400_BAD_REQUEST)
        if script_type == 'JMX_UPLOAD' and not upload:
            return Response({'error': '纯 JMX 脚本必须保留原始 JMX 文件'}, status=status.HTTP_400_BAD_REQUEST)

        script = PerformanceScript.objects.create(
            project=project,
            name=name,
            description=description,
            script_type=script_type,
            status='ready',
            config=config,
            import_warnings=warnings,
            original_jmx=upload if script_type == 'JMX_UPLOAD' else None,
            created_by=request.user,
        )
        return Response(PerformanceScriptSerializer(script, context={'request': request}).data, status=status.HTTP_201_CREATED)

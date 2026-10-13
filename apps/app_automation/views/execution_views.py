# -*- coding: utf-8 -*-
"""APP测试执行管理视图"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.filters import SearchFilter
from django.db.models import Q
from django.db import transaction
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from django.http import FileResponse, Http404
from django.views.decorators.csrf import csrf_exempt
import logging
import os

from ..models import AppTestExecution, AppTestBatchReport, AppDevice
from ..serializers import AppTestExecutionSerializer, AppTestBatchReportSerializer
from ..tasks import send_execution_update
from .test_case_views import AppPagination

logger = logging.getLogger(__name__)


class AppTestExecutionViewSet(viewsets.ModelViewSet):
    """APP测试执行记录 ViewSet"""
    queryset = AppTestExecution.objects.all()
    serializer_class = AppTestExecutionSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ['status', 'test_case', 'device', 'batch_report']
    search_fields = ['test_case__name', 'device__name', 'device__device_id', 'user__username']
    pagination_class = AppPagination
    
    def get_queryset(self):
        queryset = super().get_queryset()

        # 支持 test_suite__isnull 过滤，用于区分单独执行和套件执行
        suite_isnull = self.request.query_params.get('test_suite__isnull')
        if suite_isnull is not None:
            queryset = queryset.filter(test_suite__isnull=(suite_isnull.lower() in ('true', '1')))

        batch_isnull = self.request.query_params.get('batch_report__isnull')
        if batch_isnull is not None:
            queryset = queryset.filter(batch_report__isnull=(batch_isnull.lower() in ('true', '1')))

        # 支持按项目间接过滤（通过 test_case.project）
        project_id = self.request.query_params.get('project')
        if project_id:
            queryset = queryset.filter(test_case__project_id=project_id)

        search_value = (self.request.query_params.get('search') or '').strip()
        if not search_value:
            return queryset
        return queryset.filter(
            Q(test_case__name__icontains=search_value) |
            Q(device__name__icontains=search_value) |
            Q(device__device_id__icontains=search_value) |
            Q(user__username__icontains=search_value)
        )
    
    def destroy(self, request, *args, **kwargs):
        """删除非运行中执行记录，并在最后一个任务删除后释放设备。"""
        with transaction.atomic():
            execution = self.get_object()
            if execution.status == 'running':
                return Response({
                    'success': False,
                    'message': '执行中的任务请先停止，停止后再删除记录',
                }, status=status.HTTP_400_BAD_REQUEST)
            if execution.batch_report_id:
                return Response({
                    'success': False,
                    'message': '批次子记录请在批次报告中统一管理，不能单独删除',
                }, status=status.HTTP_400_BAD_REQUEST)

            device_id = execution.device_id
            self.perform_destroy(execution)
            if device_id:
                device = AppDevice.objects.select_for_update().filter(id=device_id).first()
                has_active_execution = AppTestExecution.objects.filter(
                    device_id=device_id, status__in=['pending', 'running']
                ).exists()
                if device and not has_active_execution and device.status == 'locked' and device.locked_by == request.user:
                    device.unlock()

        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=['get'])
    def ws_status(self, request):
        """检查 WebSocket 是否可用"""
        try:
            import daphne
            from channels.layers import get_channel_layer
            channel_layer = get_channel_layer()
            ws_available = channel_layer is not None and not isinstance(
                channel_layer, type(None)
            )
            # 检查是否通过 ASGI 服务器运行（非 runserver）
            server_type = request.META.get('SERVER_SOFTWARE', '')
            is_asgi = 'daphne' in server_type.lower() or request.META.get('asgi', False)
            return Response({'websocket': ws_available and is_asgi})
        except (ImportError, Exception):
            return Response({'websocket': False})

    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        """停止执行"""
        execution = self.get_object()
        
        if execution.status not in ['pending', 'running']:
            return Response({
                'success': False,
                'message': '只能停止待执行或执行中的任务'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # 停止 Celery 任务
            if execution.task_id:
                from celery import current_app
                current_app.control.revoke(execution.task_id, terminate=True, signal='SIGTERM')
                logger.info(f"Celery任务已终止: task_id={execution.task_id}")
            
            execution.status = 'stopped'
            execution.finished_at = timezone.now()
            if execution.started_at:
                execution.duration = (execution.finished_at - execution.started_at).total_seconds()
            execution.save()
            send_execution_update(
                execution.id,
                status='stopped',
                progress=execution.progress,
                message='任务已停止',
                report_path=execution.report_path,
                finished_at=execution.finished_at
            )
            
            return Response({
                'success': True,
                'message': '任务已停止'
            })
        except Exception as e:
            logger.error(f"停止任务失败: {str(e)}")
            return Response({
                'success': False,
                'message': f'停止任务失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AppTestBatchReportViewSet(viewsets.ReadOnlyModelViewSet):
    """APP 批量执行的汇总报告。"""
    queryset = AppTestBatchReport.objects.select_related('test_suite', 'device', 'user')
    serializer_class = AppTestBatchReportSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ['status', 'test_suite', 'device']
    search_fields = ['batch_id', 'test_suite__name', 'device__name', 'device__device_id']
    pagination_class = AppPagination

    def get_queryset(self):
        queryset = super().get_queryset()
        project_id = self.request.query_params.get('project')
        if project_id:
            queryset = queryset.filter(executions__test_case__project_id=project_id).distinct()
        return queryset

    @action(detail=True, methods=['get'])
    def executions(self, request, pk=None):
        batch_report = self.get_object()
        executions = batch_report.executions.select_related('test_case', 'device', 'user').order_by('created_at', 'id')
        return Response({'success': True, 'data': AppTestExecutionSerializer(executions, many=True).data})


def _serve_report_path(report_path, file_path=''):
    if not report_path:
        raise Http404("报告路径不存在")
    if not file_path:
        file_path = 'index.html'

    report_dir = report_path
    full_path = os.path.join(report_dir, file_path)
    report_dir_abs = os.path.abspath(report_dir)
    full_path_abs = os.path.abspath(full_path)
    if not full_path_abs.startswith(report_dir_abs + os.sep) and full_path_abs != report_dir_abs:
        raise Http404("无效的文件路径")
    if not os.path.exists(full_path_abs) or not os.path.isfile(full_path_abs):
        raise Http404("文件不存在")
    return FileResponse(open(full_path_abs, 'rb'), content_type=_get_content_type(file_path))


def serve_report_file(request, execution_id, file_path=''):
    """提供 Allure 报告文件访问"""
    try:
        execution = AppTestExecution.objects.get(id=execution_id)
        return _serve_report_path(execution.report_path, file_path)
    except AppTestExecution.DoesNotExist:
        raise Http404("执行记录不存在")


@csrf_exempt
def serve_batch_report_file(request, batch_report_id, file_path=''):
    """提供批次汇总 Allure 报告文件访问。"""
    try:
        batch_report = AppTestBatchReport.objects.get(id=batch_report_id)
        return _serve_report_path(batch_report.report_path, file_path)
    except AppTestBatchReport.DoesNotExist:
        raise Http404("批次报告不存在")


def _get_content_type(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    content_types = {
        '.html': 'text/html',
        '.js': 'application/javascript',
        '.css': 'text/css',
        '.json': 'application/json',
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.gif': 'image/gif',
        '.svg': 'image/svg+xml',
        '.ico': 'image/x-icon',
        '.woff': 'font/woff',
        '.woff2': 'font/woff2',
        '.ttf': 'font/ttf',
        '.eot': 'application/vnd.ms-fontobject',
        '.txt': 'text/plain',
    }
    return content_types.get(ext, 'application/octet-stream')

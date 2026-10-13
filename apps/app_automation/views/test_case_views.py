# -*- coding: utf-8 -*-
"""APP测试用例管理视图"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination
from rest_framework.filters import SearchFilter
from django_filters.rest_framework import DjangoFilterBackend
from django.db import transaction
import logging

from ..models import AppPackage, AppTestCase, AppDevice, AppTestExecution, AppTestBatchReport
from ..serializers import AppPackageSerializer, AppTestCaseSerializer, AppTestExecutionSerializer
from ..services.device_preflight import (
    preflight_device,
    resolve_package_name,
    validate_test_case,
)
from ..services.execution_queue import check_execution_queue

logger = logging.getLogger(__name__)


class AppPagination(PageNumberPagination):
    """APP自动化模块通用分页"""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class AppPackageViewSet(viewsets.ModelViewSet):
    """APP应用包名管理 ViewSet"""
    queryset = AppPackage.objects.all()
    serializer_class = AppPackageSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = AppPagination
    search_fields = ['name', 'package_name']
    
    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class AppTestCaseViewSet(viewsets.ModelViewSet):
    """APP测试用例 ViewSet"""
    queryset = AppTestCase.objects.all()
    serializer_class = AppTestCaseSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = AppPagination
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ['project', 'app_package']
    search_fields = ['name']
    
    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @staticmethod
    def _active_execution_exists(device):
        return AppTestExecution.objects.filter(
            device=device,
            status__in=['pending', 'running'],
        ).exists()

    @staticmethod
    def _preflight_response(device, package_name):
        result = preflight_device(device, package_name, recover_environment=True)
        if result.get('ready'):
            return None
        return Response({
            'success': False,
            'message': '执行前预检未通过',
            'preflight': result,
        }, status=status.HTTP_400_BAD_REQUEST)

    def _reserve_device(self, device_id, user, create_executions):
        """在同一事务内锁定设备并创建执行记录，避免同用户并发重复投递。"""
        with transaction.atomic():
            device = AppDevice.objects.select_for_update().get(device_id=device_id)
            if device.status == 'locked' and device.locked_by != user:
                return None, None, '设备已被其他用户锁定'
            if self._active_execution_exists(device):
                return None, None, '设备已有正在排队或执行的任务，请等待当前任务完成'
            if device.status != 'locked':
                device.lock(user)
            return device, create_executions(device), ''

    @staticmethod
    def _release_reservation(device, user):
        if not device:
            return
        device.refresh_from_db()
        if device.status == 'locked' and device.locked_by == user:
            device.unlock()
    
    @action(detail=True, methods=['post'])
    def execute(self, request, pk=None):
        """执行测试用例"""
        test_case = self.get_object()
        device_id = request.data.get('device_id')
        package_name = resolve_package_name(test_case, request.data.get('package_name') or '')
        
        if not device_id:
            return Response({
                'success': False,
                'message': '请选择执行设备'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        valid, reason = validate_test_case(test_case)
        if not valid:
            return Response({'success': False, 'message': reason}, status=status.HTTP_400_BAD_REQUEST)

        queue_ready, queue_message = check_execution_queue()
        if not queue_ready:
            return Response({'success': False, 'message': queue_message}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        execution = None
        device = None
        try:
            device = AppDevice.objects.get(device_id=device_id)
            preflight_error = self._preflight_response(device, package_name)
            if preflight_error:
                return preflight_error

            device, execution, reservation_error = self._reserve_device(
                device_id,
                request.user,
                lambda reserved_device: AppTestExecution.objects.create(
                    test_case=test_case, device=reserved_device, user=request.user, status='pending'
                ),
            )
            if reservation_error:
                return Response({'success': False, 'message': reservation_error}, status=status.HTTP_400_BAD_REQUEST)

            from ..tasks import execute_app_test_task
            task = execute_app_test_task.delay(execution.id, package_name=package_name)
            execution.task_id = task.id
            execution.save(update_fields=['task_id'])
            
            logger.info(f"测试已提交执行: execution_id={execution.id}, task_id={task.id}")
            
            return Response({
                'success': True,
                'message': '测试已提交执行',
                'execution': AppTestExecutionSerializer(execution).data
            })
            
        except AppDevice.DoesNotExist:
            return Response({
                'success': False,
                'message': '设备不存在'
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.exception('执行测试失败')
            if execution:
                execution.status = 'error'
                execution.error_message = f'任务提交失败: {e}'
                execution.save(update_fields=['status', 'error_message'])
            self._release_reservation(device, request.user)
            return Response({
                'success': False,
                'message': f'执行测试失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'], url_path='execute-batch')
    def execute_batch(self, request):
        """同设备批量执行：一次预检、一次独占、由一个任务严格顺序执行。"""
        raw_case_ids = request.data.get('case_ids') or []
        device_id = request.data.get('device_id')
        package_override = (request.data.get('package_name') or '').strip()
        if not device_id:
            return Response({'success': False, 'message': '请选择执行设备'}, status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(raw_case_ids, list) or not raw_case_ids:
            return Response({'success': False, 'message': '请至少选择一个用例'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            case_ids = list(dict.fromkeys(int(case_id) for case_id in raw_case_ids))
        except (TypeError, ValueError):
            return Response({'success': False, 'message': '用例编号格式错误'}, status=status.HTTP_400_BAD_REQUEST)
        cases_by_id = {
            case.id: case for case in AppTestCase.objects.filter(id__in=case_ids).select_related('app_package')
        }
        missing_ids = [case_id for case_id in case_ids if case_id not in cases_by_id]
        if missing_ids:
            return Response({'success': False, 'message': f'用例不存在: {missing_ids}'}, status=status.HTTP_400_BAD_REQUEST)
        test_cases = [cases_by_id[case_id] for case_id in case_ids]
        invalid_cases = [case.name for case in test_cases if not validate_test_case(case)[0]]
        if invalid_cases:
            return Response({
                'success': False,
                'message': f'以下用例没有可执行步骤: {"、".join(invalid_cases)}',
            }, status=status.HTTP_400_BAD_REQUEST)

        queue_ready, queue_message = check_execution_queue()
        if not queue_ready:
            return Response({'success': False, 'message': queue_message}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        executions = []
        batch_report = None
        device = None
        try:
            device = AppDevice.objects.get(device_id=device_id)
            packages = {resolve_package_name(case, package_override) for case in test_cases}
            for package_name in packages:
                preflight_error = self._preflight_response(device, package_name)
                if preflight_error:
                    return preflight_error

            created = {}

            def create_batch_executions(reserved_device):
                batch = AppTestBatchReport.objects.create(
                    device=reserved_device,
                    user=request.user,
                    total_cases=len(test_cases),
                    status='pending',
                )
                created['batch_report'] = batch
                return [
                    AppTestExecution.objects.create(
                        test_case=case,
                        batch_report=batch,
                        device=reserved_device,
                        user=request.user,
                        status='pending',
                    )
                    for case in test_cases
                ]

            device, executions, reservation_error = self._reserve_device(
                device_id,
                request.user,
                create_batch_executions,
            )
            if reservation_error:
                return Response({'success': False, 'message': reservation_error}, status=status.HTTP_400_BAD_REQUEST)
            batch_report = created['batch_report']

            from ..tasks import execute_app_suite_task
            task = execute_app_suite_task.delay(
                suite_id=None,
                execution_ids=[execution.id for execution in executions],
                package_name=package_override or None,
                batch_report_id=batch_report.id,
            )
            executions[0].task_id = task.id
            executions[0].save(update_fields=['task_id'])
            batch_report.task_id = task.id
            batch_report.save(update_fields=['task_id'])
            return Response({
                'success': True,
                'message': f'已提交 {len(executions)} 个用例，将按顺序执行',
                'data': {
                    'task_id': task.id,
                    'batch_report_id': batch_report.id,
                    'execution_ids': [execution.id for execution in executions],
                    'test_case_count': len(executions),
                },
            })
        except AppDevice.DoesNotExist:
            return Response({'success': False, 'message': '设备不存在'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as exc:
            logger.exception('批量提交 APP 测试失败')
            for execution in executions:
                execution.status = 'error'
                execution.error_message = f'任务提交失败: {exc}'
                execution.save(update_fields=['status', 'error_message'])
            if batch_report:
                batch_report.status = 'error'
                batch_report.error_message = f'任务提交失败: {exc}'
                batch_report.save(update_fields=['status', 'error_message'])
            self._release_reservation(device, request.user)
            return Response({'success': False, 'message': f'批量执行失败: {exc}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

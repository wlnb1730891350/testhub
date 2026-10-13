from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
from django.db import models

from ..models import (
    UiProject, TestSuite, TestSuiteScript, TestExecution, Screenshot
)
from ..serializers import (
    TestSuiteSerializer, TestSuiteCreateSerializer, TestSuiteUpdateSerializer,
    TestSuiteWithScriptsSerializer, TestSuiteScriptSerializer, TestSuiteTestCaseSerializer,
    TestExecutionSerializer, TestExecutionCreateSerializer,
    ScreenshotSerializer,
)
from ..operation_logger import log_operation
from ._helpers import StandardPagination

import logging
logger = logging.getLogger(__name__)


class TestSuiteViewSet(viewsets.ModelViewSet):
    queryset = TestSuite.objects.all()
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['project']
    search_fields = ['name', 'description']
    ordering = ['-created_at']

    def get_serializer_class(self):
        if self.action == 'create':
            return TestSuiteCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return TestSuiteUpdateSerializer
        elif self.action == 'retrieve':
            return TestSuiteWithScriptsSerializer
        return TestSuiteSerializer

    def get_queryset(self):
        user = self.request.user
        accessible_projects = UiProject.objects.filter(
            models.Q(owner=user) | models.Q(members=user)
        ).distinct()
        return TestSuite.objects.filter(project__in=accessible_projects)

    def perform_create(self, serializer):
        instance = serializer.save()
        log_operation('create', 'suite', instance.id, instance.name, self.request.user)

    def perform_update(self, serializer):
        instance = serializer.save()
        log_operation('edit', 'suite', instance.id, instance.name, self.request.user)

    def perform_destroy(self, instance):
        log_operation('delete', 'suite', instance.id, instance.name, self.request.user)
        instance.delete()

    @action(detail=True, methods=['get'])
    def scripts(self, request, pk=None):
        test_suite = self.get_object()
        scripts = test_suite.suite_scripts.all()
        serializer = TestSuiteScriptSerializer(scripts, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def add_script(self, request, pk=None):
        test_suite = self.get_object()
        data = request.data
        data['test_suite'] = pk
        serializer = TestSuiteScriptSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['delete'])
    def remove_script(self, request, pk=None, script_id=None):
        test_suite = self.get_object()
        try:
            suite_script = TestSuiteScript.objects.get(test_suite=test_suite, id=script_id)
            suite_script.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except TestSuiteScript.DoesNotExist:
            return Response({'error': '脚本不存在于该测试套件中'}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=['get'])
    def test_cases(self, request, pk=None):
        test_suite = self.get_object()
        test_cases = test_suite.suite_test_cases.all()
        serializer = TestSuiteTestCaseSerializer(test_cases, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def add_test_case(self, request, pk=None):
        test_suite = self.get_object()
        test_case_id = request.data.get('test_case_id')
        order = request.data.get('order', 0)
        try:
            from ..models import TestSuiteTestCase
            suite_test_case = TestSuiteTestCase.objects.create(
                test_suite=test_suite,
                test_case_id=test_case_id,
                order=order
            )
            serializer = TestSuiteTestCaseSerializer(suite_test_case)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['delete'])
    def remove_test_case(self, request, pk=None):
        test_suite = self.get_object()
        test_case_id = request.data.get('test_case_id')
        try:
            from ..models import TestSuiteTestCase
            suite_test_case = TestSuiteTestCase.objects.get(
                test_suite=test_suite,
                test_case_id=test_case_id
            )
            suite_test_case.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except TestSuiteTestCase.DoesNotExist:
            return Response({'error': '测试用例不存在于该测试套件中'}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=['post'])
    def update_test_case_order(self, request, pk=None):
        test_suite = self.get_object()
        test_case_orders = request.data.get('test_case_orders', [])
        try:
            from ..models import TestSuiteTestCase
            for item in test_case_orders:
                TestSuiteTestCase.objects.filter(
                    test_suite=test_suite,
                    test_case_id=item['test_case_id']
                ).update(order=item['order'])
            return Response({'message': '顺序更新成功'}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def run_suite(self, request, pk=None):
        test_suite = self.get_object()
        test_case_count = test_suite.suite_test_cases.count()
        if test_case_count == 0:
            return Response({
                'error': '该测试套件未包含任何测试用例，无法执行'
            }, status=status.HTTP_400_BAD_REQUEST)

        engine = request.data.get('engine', 'playwright')
        browser = request.data.get('browser', 'chrome')
        headless = request.data.get('headless', False)

        test_suite.execution_status = 'running'
        test_suite.save()

        log_operation('run', 'suite', test_suite.id, test_suite.name, request.user)

        import threading
        import traceback
        from ..test_executor import TestExecutor

        def run_test():
            try:
                logger.info(f"[测试套件] 开始执行: {test_suite.name} (ID: {test_suite.id})")
                logger.info(f"[测试套件] 配置: engine={engine}, browser={browser}, headless={headless}")
                executor = TestExecutor(
                    test_suite=test_suite,
                    engine=engine,
                    browser=browser,
                    headless=headless,
                    executed_by=request.user
                )
                executor.run()
                logger.info(f"[测试套件] 执行完成: {test_suite.name}")
            except Exception as e:
                logger.error(f"[测试套件] 执行异常: {test_suite.name}")
                logger.error(f"[测试套件] 错误: {str(e)}")
                traceback.print_exc()
                try:
                    test_suite.execution_status = 'failed'
                    test_suite.save()
                    logger.info(f"[测试套件] 已更新状态为失败")
                except Exception as save_error:
                    logger.error(f"[测试套件] 更新状态失败: {save_error}")

        thread = threading.Thread(target=run_test, daemon=False)
        thread.start()

        return Response({
            'message': '测试套件开始执行',
            'suite_id': test_suite.id,
            'test_case_count': test_case_count,
            'engine': engine,
            'browser': browser,
            'headless': headless
        }, status=status.HTTP_200_OK)


class TestExecutionViewSet(viewsets.ModelViewSet):
    queryset = TestExecution.objects.all()
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['project', 'test_suite', 'test_script', 'status', 'environment', 'executed_by']
    search_fields = ['error_message']
    ordering = ['-created_at']
    pagination_class = StandardPagination

    def get_queryset(self):
        user = self.request.user
        accessible_projects = UiProject.objects.filter(
            models.Q(owner=user) | models.Q(members=user)
        ).distinct()
        return TestExecution.objects.filter(
            project__in=accessible_projects
        ).select_related('project', 'test_suite', 'test_script', 'executed_by')

    def get_serializer_class(self):
        if self.action == 'create':
            return TestExecutionCreateSerializer
        return TestExecutionSerializer

    def perform_destroy(self, instance):
        suite_name = instance.test_suite.name if instance.test_suite else f"执行记录#{instance.id}"
        log_operation('delete', 'report', instance.id, suite_name, self.request.user)
        instance.delete()


class ScreenshotViewSet(viewsets.ModelViewSet):
    queryset = Screenshot.objects.all()
    permission_classes = [IsAuthenticated]
    serializer_class = ScreenshotSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['execution']

    def get_queryset(self):
        user = self.request.user
        accessible_projects = UiProject.objects.filter(
            models.Q(owner=user) | models.Q(members=user)
        ).distinct()
        executions = TestExecution.objects.filter(project__in=accessible_projects)
        return Screenshot.objects.filter(execution__in=executions)

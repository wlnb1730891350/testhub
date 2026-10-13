from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
from django.db import models

from ..models import (
    UiProject, TestCase, TestSuite, TestExecution, TestCaseExecution,
    RecordingSession, SetupTemplate
)
from ..serializers import (
    RecordingSessionSerializer, SetupTemplateSerializer,
)

import logging
logger = logging.getLogger(__name__)


class UiDashboardViewSet(viewsets.ViewSet):
    """UI自动化仪表盘视图集"""
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['get'])
    def stats(self, request):
        user = request.user
        accessible_projects = UiProject.objects.filter(
            models.Q(owner=user) | models.Q(members=user)
        ).distinct()
        project_ids = accessible_projects.values_list('id', flat=True)
        project_count = accessible_projects.count()
        test_case_count = TestCase.objects.filter(project_id__in=project_ids).count()
        suite_count = TestSuite.objects.filter(project_id__in=project_ids).count()
        from ..models import TestSuiteTestCase
        suite_test_case_count = TestSuiteTestCase.objects.filter(
            test_suite__project_id__in=project_ids
        ).count()
        execution_count = TestExecution.objects.filter(project_id__in=project_ids).count()
        test_case_execution_count = TestCaseExecution.objects.filter(project_id__in=project_ids).count()
        total_execution_count = execution_count + test_case_execution_count
        return Response({
            'project_count': project_count,
            'test_case_count': test_case_count,
            'suite_count': suite_test_case_count,
            'execution_count': total_execution_count
        })


class RecordingSessionViewSet(viewsets.ModelViewSet):
    """录制会话视图集"""
    queryset = RecordingSession.objects.all()
    serializer_class = RecordingSessionSerializer
    permission_classes = [IsAuthenticated]

    def create(self, request, *args, **kwargs):
        from ..recording_engine import RecordingEngine
        import uuid
        start_url = request.data.get('start_url', 'https://example.com')
        project_id = request.data.get('project_id')
        browser_type = request.data.get('browser', 'chromium')
        headless = request.data.get('headless', False)
        if not project_id:
            return Response({'error': '请指定项目'}, status=status.HTTP_400_BAD_REQUEST)
        session_id = f"rec_{uuid.uuid4().hex[:12]}"
        auth_token = str(request.auth.token) if hasattr(request, 'auth') and request.auth else ''
        result = RecordingEngine.start_recording(
            session_id=session_id,
            start_url=start_url,
            project_id=project_id,
            browser_type=browser_type,
            headless=headless,
            user=request.user,
            auth_token=auth_token,
        )
        if result.get('success'):
            return Response({'session_id': session_id, 'message': '录制已启动'})
        else:
            return Response({'error': result.get('error', '启动录制失败')}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'], url_path=r'(?P<session_id>[\w-]+)/stop')
    def stop(self, request, session_id=None):
        from ..recording_engine import RecordingEngine
        result = RecordingEngine.stop_recording(session_id)
        if result.get('success'):
            return Response({
                'success': True,
                'actions': result.get('actions', []),
                'error': result.get('error'),
            })
        else:
            return Response({'error': result.get('error', '停止录制失败')}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'], url_path=r'actions')
    def actions_list(self, request):
        from ..recording_engine import RecordingEngine
        session_id = request.query_params.get('session_id')
        if not session_id:
            return Response({'error': '缺少session_id参数'}, status=status.HTTP_400_BAD_REQUEST)
        actions = RecordingEngine.get_actions(session_id)
        return Response({'actions': actions})

    @action(detail=False, methods=['post'], url_path=r'actions')
    def add_actions(self, request):
        from ..recording_engine import RecordingEngine
        session_id = request.data.get('session_id')
        actions = request.data.get('actions', [])
        if not session_id:
            return Response({'error': '缺少session_id参数'}, status=status.HTTP_400_BAD_REQUEST)
        result = RecordingEngine.add_actions(session_id, actions)
        return Response(result)

    @action(detail=False, methods=['get'], url_path=r'(?P<session_id>[\w-]+)/status-check')
    def status_check(self, request, session_id=None):
        from ..recording_engine import RecordingEngine
        result = RecordingEngine.get_status(session_id)
        return Response(result)

    @action(detail=False, methods=['get'], url_path=r'active')
    def active_sessions(self, request):
        from ..recording_engine import _active_sessions, _session_lock
        with _session_lock:
            sessions = []
            for sid, data in _active_sessions.items():
                sessions.append({
                    'session_id': sid,
                    'status': data.get('session', {}).status if data.get('session') else 'unknown',
                    'actions_count': len(data.get('actions', [])),
                })
        return Response({'sessions': sessions})

    @action(detail=False, methods=['post'], url_path=r'(?P<session_id>[\w-]+)/save-as-test-case')
    def save_as_test_case(self, request, session_id=None):
        from ..recording_engine import RecordingEngine
        test_case_name = request.data.get('name', f'录制用例_{session_id}')
        project_id = request.data.get('project_id')
        target_test_case_id = request.data.get('target_test_case_id')
        selected_action_indexes = request.data.get('selected_action_indexes')
        if not project_id:
            return Response({'error': '请指定项目'}, status=status.HTTP_400_BAD_REQUEST)
        result = RecordingEngine.save_as_test_case(
            session_id=session_id,
            test_case_name=test_case_name,
            project_id=project_id,
            user=request.user,
            target_test_case_id=target_test_case_id,
            selected_action_indexes=selected_action_indexes,
        )
        if result.get('success'):
            return Response({
                'success': True,
                'test_case_id': result.get('test_case_id'),
                'test_case_name': result.get('test_case_name'),
                'steps_count': result.get('steps_created', 0),
                'steps_created': result.get('steps_created', 0),
                'steps_before_save': result.get('steps_before_save', 0),
                'total_steps_after_save': result.get('total_steps_after_save', result.get('steps_created', 0)),
                'save_mode': result.get('save_mode'),
                'message': result.get('message', '保存成功'),
            })
        else:
            return Response({'error': result.get('error', '保存失败')}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'], url_path=r'clean-actions')
    def clean_actions(self, request):
        from ..recording_engine import RecordingEngine
        actions = request.data.get('actions', [])
        clean = RecordingEngine._clean_actions(actions)
        return Response({'actions': clean, 'removed_count': len(actions) - len(clean)})


class SetupTemplateViewSet(viewsets.ModelViewSet):
    """前置步骤模板ViewSet"""
    queryset = SetupTemplate.objects.all()
    serializer_class = SetupTemplateSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['project']
    search_fields = ['name', 'description']

    def get_queryset(self):
        qs = super().get_queryset()
        project_id = self.request.query_params.get('project_id')
        if project_id:
            qs = qs.filter(project_id=project_id)
        return qs.select_related('project', 'created_by')

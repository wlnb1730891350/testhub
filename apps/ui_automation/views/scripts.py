from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
from django.db import models

from ..models import (
    UiProject, TestScript, ScriptStep, ScriptElementUsage
)
from ..serializers import (
    TestScriptSerializer, TestScriptCreateSerializer, TestScriptUpdateSerializer,
    ScriptStepSerializer, ScriptElementUsageSerializer, ScriptAnalysisSerializer,
)

import logging
logger = logging.getLogger(__name__)


class ScriptStepViewSet(viewsets.ModelViewSet):
    queryset = ScriptStep.objects.all()
    permission_classes = [IsAuthenticated]
    serializer_class = ScriptStepSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['script', 'action_type', 'target_element', 'page_object']

    def get_queryset(self):
        user = self.request.user
        accessible_projects = UiProject.objects.filter(
            models.Q(owner=user) | models.Q(members=user)
        ).distinct()
        return ScriptStep.objects.filter(
            script__project__in=accessible_projects
        ).select_related('script', 'target_element', 'page_object').order_by('step_order')

    @action(detail=False, methods=['post'])
    def batch_create(self, request):
        steps_data = request.data.get('steps', [])
        created_steps = []
        for step_data in steps_data:
            serializer = ScriptStepSerializer(data=step_data)
            if serializer.is_valid():
                step = serializer.save()
                created_steps.append(step)
            else:
                return Response({
                    'error': f'步骤创建失败: {serializer.errors}'
                }, status=status.HTTP_400_BAD_REQUEST)
        response_serializer = ScriptStepSerializer(created_steps, many=True)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class ScriptElementUsageViewSet(viewsets.ModelViewSet):
    queryset = ScriptElementUsage.objects.all()
    permission_classes = [IsAuthenticated]
    serializer_class = ScriptElementUsageSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['script', 'element', 'usage_type']

    def get_queryset(self):
        user = self.request.user
        accessible_projects = UiProject.objects.filter(
            models.Q(owner=user) | models.Q(members=user)
        ).distinct()
        return ScriptElementUsage.objects.filter(
            script__project__in=accessible_projects
        ).select_related('script', 'element').order_by('script', 'line_number')

    @action(detail=False, methods=['post'])
    def analyze_script(self, request):
        script_id = request.data.get('script_id')
        if not script_id:
            return Response({'error': '需要指定脚本ID'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            script = TestScript.objects.get(id=script_id)
            analysis_result = self._analyze_script_elements(script)
            serializer = ScriptAnalysisSerializer(analysis_result)
            return Response(serializer.data)
        except TestScript.DoesNotExist:
            return Response({'error': '脚本不存在'}, status=status.HTTP_404_NOT_FOUND)

    def _analyze_script_elements(self, script):
        usages = ScriptElementUsage.objects.filter(script=script).select_related('element')
        total_usages = usages.count()
        unique_elements = usages.values('element').distinct().count()
        usage_types = {}
        for usage in usages:
            usage_types[usage.usage_type] = usage_types.get(usage.usage_type, 0) + 1
        return {
            'script_id': script.id,
            'script_name': script.name,
            'total_usages': total_usages,
            'unique_elements': unique_elements,
            'usage_types': usage_types,
            'usages': ScriptElementUsageSerializer(usages, many=True).data
        }


class TestScriptViewSet(viewsets.ModelViewSet):
    queryset = TestScript.objects.all()
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['project', 'script_type']
    search_fields = ['name', 'description']
    ordering = ['-created_at']

    def get_serializer_class(self):
        if self.action == 'create':
            return TestScriptCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return TestScriptUpdateSerializer
        return TestScriptSerializer

    def get_queryset(self):
        user = self.request.user
        accessible_projects = UiProject.objects.filter(
            models.Q(owner=user) | models.Q(members=user)
        ).distinct()
        return TestScript.objects.filter(project__in=accessible_projects)

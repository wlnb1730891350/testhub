import csv
import json

from django.contrib.auth import get_user_model
from rest_framework import serializers

from .jmx_builder import default_script_config
from .models import PerformanceDataset, PerformanceExecution, PerformanceProject, PerformanceScript
from .realtime_report import get_realtime_report_url

User = get_user_model()


class UserLiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name']


class NullableDateField(serializers.DateField):
    def to_internal_value(self, value):
        if value == '' or value is None:
            return None
        return super().to_internal_value(value)


class PerformanceProjectSerializer(serializers.ModelSerializer):
    owner = UserLiteSerializer(read_only=True)
    members = UserLiteSerializer(many=True, read_only=True)
    member_ids = serializers.ListField(child=serializers.IntegerField(), write_only=True, required=False)
    start_date = NullableDateField(required=False, allow_null=True)
    end_date = NullableDateField(required=False, allow_null=True)

    class Meta:
        model = PerformanceProject
        fields = [
            'id', 'name', 'description', 'status', 'base_url',
            'owner', 'members', 'member_ids', 'start_date', 'end_date',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at', 'owner', 'members']

    def create(self, validated_data):
        member_ids = validated_data.pop('member_ids', [])
        validated_data['owner'] = self.context['request'].user
        project = super().create(validated_data)
        self._set_members(project, member_ids)
        return project

    def update(self, instance, validated_data):
        member_ids = validated_data.pop('member_ids', None)
        project = super().update(instance, validated_data)
        if member_ids is not None:
            self._set_members(project, member_ids)
        return project

    def _set_members(self, project, member_ids):
        if member_ids:
            project.members.set(User.objects.filter(id__in=member_ids))
        else:
            project.members.clear()

class PerformanceScriptSerializer(serializers.ModelSerializer):
    project_name = serializers.CharField(source='project.name', read_only=True)
    created_by = UserLiteSerializer(read_only=True)
    config = serializers.JSONField(required=False)

    class Meta:
        model = PerformanceScript
        fields = [
            'id', 'project', 'project_name', 'name', 'description',
            'script_type', 'status', 'config', 'original_jmx', 'generated_jmx',
            'import_warnings', 'version', 'is_active', 'created_by',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'generated_jmx', 'import_warnings', 'version',
            'created_by', 'created_at', 'updated_at',
        ]

    def validate_config(self, value):
        if not value:
            return default_script_config()
        if not isinstance(value, dict):
            raise serializers.ValidationError('脚本配置必须是 JSON 对象')
        return value

    def create(self, validated_data):
        validated_data['created_by'] = self.context['request'].user
        if not validated_data.get('config'):
            project = validated_data.get('project')
            validated_data['config'] = default_script_config(project.base_url if project else '')
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if _has_versioned_changes(instance, validated_data):
            validated_data['version'] = instance.version + 1
        return super().update(instance, validated_data)


class PerformanceDatasetSerializer(serializers.ModelSerializer):
    project_name = serializers.CharField(source='project.name', read_only=True)
    created_by = UserLiteSerializer(read_only=True)
    file_path = serializers.SerializerMethodField()
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = PerformanceDataset
        fields = [
            'id', 'project', 'project_name', 'name', 'description',
            'file', 'file_path', 'file_url', 'variables', 'row_count', 'created_by',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['file_path', 'file_url', 'variables', 'row_count', 'created_by', 'created_at', 'updated_at']

    def get_file_path(self, obj):
        try:
            return obj.file.path if obj.file else ''
        except NotImplementedError:
            return ''

    def get_file_url(self, obj):
        return obj.file.url if obj.file else ''


class PerformanceExecutionSerializer(serializers.ModelSerializer):
    project_name = serializers.CharField(source='project.name', read_only=True)
    script_name = serializers.CharField(source='script.name', read_only=True)
    executed_by = UserLiteSerializer(read_only=True)
    realtime_report_url = serializers.SerializerMethodField()

    class Meta:
        model = PerformanceExecution
        fields = [
            'id', 'project', 'project_name', 'script', 'script_name',
            'status', 'started_at', 'finished_at', 'duration',
            'executed_by', 'task_id', 'jmeter_pid', 'jmx_path', 'jtl_path',
            'log_path', 'report_url', 'realtime_report_url', 'report_status', 'summary',
            'metrics', 'error_message', 'created_at',
        ]
        read_only_fields = fields

    def get_realtime_report_url(self, obj):
        return get_realtime_report_url(obj)


def inspect_csv_dataset(instance):
    variables = []
    row_count = 0
    try:
        with instance.file.open('r') as handle:
            reader = csv.reader(handle)
            for index, row in enumerate(reader):
                if index == 0:
                    variables = [cell.strip() for cell in row if cell.strip()]
                else:
                    row_count += 1
    except UnicodeDecodeError:
        with instance.file.open('rb') as handle:
            text = handle.read().decode('utf-8-sig', errors='ignore').splitlines()
        reader = csv.reader(text)
        for index, row in enumerate(reader):
            if index == 0:
                variables = [cell.strip() for cell in row if cell.strip()]
            else:
                row_count += 1
    return variables, row_count


def _has_versioned_changes(instance, validated_data):
    return any(
        field in validated_data and _canonical(validated_data[field]) != _canonical(getattr(instance, field))
        for field in ('config', 'name', 'description')
    )


def _canonical(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return value

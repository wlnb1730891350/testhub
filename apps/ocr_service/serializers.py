# -*- coding: utf-8 -*-
from rest_framework import serializers
from .models import OCRConfig, OCRTask


class OCRConfigSerializer(serializers.ModelSerializer):
    """OCR 配置序列化器"""
    provider_display = serializers.CharField(source='get_provider_display', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    
    class Meta:
        model = OCRConfig
        fields = [
            'id', 'name', 'provider', 'provider_display',
            'api_key', 'base_url', 'model_name',
            'language', 'min_confidence', 'extra_config',
            'is_active', 'is_default',
            'created_by', 'created_by_name',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']
        extra_kwargs = {
            'api_key': {'write_only': True}
        }


class OCRConfigListSerializer(serializers.ModelSerializer):
    """OCR 配置列表序列化器（简化版）"""
    provider_display = serializers.CharField(source='get_provider_display', read_only=True)
    
    class Meta:
        model = OCRConfig
        fields = [
            'id', 'name', 'provider', 'provider_display',
            'base_url', 'model_name', 'language',
            'min_confidence',
            'is_active', 'is_default',
            'created_at', 'updated_at'
        ]


class OCRTaskSerializer(serializers.ModelSerializer):
    """OCR 任务序列化器"""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    config_name = serializers.CharField(source='config.name', read_only=True)
    
    class Meta:
        model = OCRTask
        fields = [
            'id', 'task_id', 'config', 'config_name',
            'image_path', 'status', 'status_display',
            'result_text', 'result_data', 'confidence',
            'error_message', 'processing_time',
            'created_at', 'completed_at'
        ]
        read_only_fields = ['id', 'task_id', 'created_at', 'completed_at']


class OCRRecognizeSerializer(serializers.Serializer):
    """OCR 识别请求序列化器"""
    image = serializers.ImageField(help_text='要识别的图片')
    config_id = serializers.IntegerField(required=False, help_text='OCR 配置 ID，不指定则使用默认配置')
    language = serializers.CharField(required=False, default='chi_sim+eng', help_text='识别语言')
    return_details = serializers.BooleanField(required=False, default=False, help_text='是否返回详细信息')


class OCRRecognizeResultSerializer(serializers.Serializer):
    """OCR 识别结果序列化器"""
    success = serializers.BooleanField()
    text = serializers.CharField()
    confidence = serializers.FloatField()
    engine = serializers.CharField()
    texts = serializers.ListField(
        child=serializers.DictField(),
        required=False
    )
    error_message = serializers.CharField(required=False)


class OCRBatchRecognizeSerializer(serializers.Serializer):
    """批量 OCR 识别请求序列化器"""
    images = serializers.ListField(
        child=serializers.ImageField(),
        help_text='要识别的图片列表'
    )
    config_id = serializers.IntegerField(required=False, help_text='OCR 配置 ID，不指定则使用默认配置')
    language = serializers.CharField(required=False, default='chi_sim+eng', help_text='识别语言')


class OCRBatchRecognizeResultSerializer(serializers.Serializer):
    """批量 OCR 识别结果序列化器"""
    success = serializers.BooleanField()
    total = serializers.IntegerField()
    processed = serializers.IntegerField()
    results = serializers.ListField(
        child=serializers.DictField()
    )
    combined_text = serializers.CharField()
    error_message = serializers.CharField(required=False)

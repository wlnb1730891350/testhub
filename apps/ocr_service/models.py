# -*- coding: utf-8 -*-
from django.db import models
from django.conf import settings


class OCRConfig(models.Model):
    """OCR 配置模型"""
    PROVIDER_CHOICES = [
        ('tesseract', 'Tesseract OCR'),
        ('openai', 'OpenAI GPT-4V'),
        ('zhipu', '智谱 GLM-4V'),
        ('siliconflow', '硅基流动'),
        ('baidu', '百度 AI OCR'),
        ('tencent', '腾讯 OCR'),
        ('aliyun', '阿里云 OCR'),
        ('custom', '自定义 OCR'),
    ]
    
    name = models.CharField(max_length=100, verbose_name='配置名称')
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, verbose_name='OCR 服务提供商')
    
    api_key = models.CharField(max_length=200, verbose_name='API Key', blank=True, null=True)
    base_url = models.URLField(verbose_name='API Base URL', blank=True, null=True)
    model_name = models.CharField(max_length=100, verbose_name='模型名称', blank=True, null=True)
    
    language = models.CharField(
        max_length=20,
        default='chi_sim+eng',
        verbose_name='识别语言',
        help_text='Tesseract: chi_sim(中文), eng(英文), chi_sim+eng(中英文)'
    )
    min_confidence = models.FloatField(default=0.3, verbose_name='最小置信度')
    
    extra_config = models.JSONField(default=dict, blank=True, verbose_name='额外配置')
    
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    is_default = models.BooleanField(default=False, verbose_name='是否默认')
    
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        verbose_name='创建者'
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    
    class Meta:
        db_table = 'ocr_config'
        verbose_name = 'OCR 配置'
        verbose_name_plural = 'OCR 配置'
        ordering = ['-is_default', '-created_at']
    
    def __str__(self):
        return f"{self.name} ({self.get_provider_display()})"
    
    @classmethod
    def get_default_config(cls):
        """获取默认 OCR 配置"""
        config = cls.objects.filter(is_default=True, is_active=True).first()
        if not config:
            config = cls.objects.filter(is_active=True).first()
        return config
    
    @classmethod
    def get_active_configs(cls):
        """获取所有活跃的 OCR 配置"""
        return cls.objects.filter(is_active=True).order_by('-is_default', 'name')


class OCRTask(models.Model):
    """OCR 识别任务记录"""
    STATUS_CHOICES = [
        ('pending', '待处理'),
        ('processing', '处理中'),
        ('completed', '已完成'),
        ('failed', '失败'),
    ]
    
    task_id = models.CharField(max_length=50, unique=True, verbose_name='任务ID')
    config = models.ForeignKey(
        OCRConfig,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name='OCR 配置'
    )
    
    image_path = models.CharField(max_length=500, verbose_name='图片路径')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name='状态')
    
    result_text = models.TextField(blank=True, verbose_name='识别结果')
    result_data = models.JSONField(null=True, blank=True, verbose_name='详细结果')
    confidence = models.FloatField(null=True, blank=True, verbose_name='置信度')
    
    error_message = models.TextField(blank=True, verbose_name='错误信息')
    processing_time = models.FloatField(null=True, blank=True, verbose_name='处理耗时(秒)')
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name='完成时间')
    
    class Meta:
        db_table = 'ocr_task'
        verbose_name = 'OCR 任务'
        verbose_name_plural = 'OCR 任务'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.task_id} - {self.get_status_display()}"

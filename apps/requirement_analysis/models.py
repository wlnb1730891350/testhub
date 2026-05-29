from django.db import models
from django.utils import timezone
from apps.users.models import User
from apps.projects.models import Project
import json
import httpx
import asyncio
from typing import Dict, Any, List, AsyncIterator
import logging

logger = logging.getLogger(__name__)


class RequirementDocument(models.Model):
    """需求文档模型"""
    DOCUMENT_TYPE_CHOICES = [
        ('pdf', 'PDF文档'),
        ('docx', 'Word文档'),
        ('txt', '文本文档'),
        ('md', 'Markdown文档'),
    ]

    STATUS_CHOICES = [
        ('uploaded', '已上传'),
        ('analyzing', '分析中'),
        ('analyzed', '分析完成'),
        ('failed', '分析失败'),
    ]

    title = models.CharField(max_length=200, verbose_name='文档标题')
    file = models.FileField(upload_to='requirement_docs/%Y/%m/', verbose_name='文档文件')
    document_type = models.CharField(max_length=10, choices=DOCUMENT_TYPE_CHOICES, verbose_name='文档类型')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='uploaded', verbose_name='状态')
    uploaded_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='uploaded_documents',
                                    verbose_name='上传者')
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='requirement_documents',
                                verbose_name='关联项目', null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    file_size = models.PositiveIntegerField(verbose_name='文件大小(bytes)', null=True, blank=True)
    extracted_text = models.TextField(verbose_name='提取的文本内容', blank=True)

    class Meta:
        db_table = 'requirement_documents'
        verbose_name = '需求文档'
        verbose_name_plural = '需求文档'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} - {self.get_status_display()}"

class RequirementAnalysis(models.Model):
    """需求分析记录"""
    document = models.OneToOneField(RequirementDocument, on_delete=models.CASCADE, related_name='analysis',
                                    verbose_name='关联文档')
    analysis_report = models.TextField(verbose_name='分析报告', blank=True)
    requirements_count = models.PositiveIntegerField(verbose_name='需求数量', default=0)
    analysis_time = models.FloatField(verbose_name='分析耗时(秒)', null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'requirement_analyses'
        verbose_name = '需求分析'
        verbose_name_plural = '需求分析'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.document.title} - 分析报告"


class BusinessRequirement(models.Model):
    """业务需求模型"""
    REQUIREMENT_TYPE_CHOICES = [
        ('functional', '功能需求'),
        ('performance', '性能需求'),
        ('security', '安全需求'),
        ('usability', '可用性需求'),
        ('interface', '接口需求'),
        ('other', '其他需求'),
    ]

    REQUIREMENT_LEVEL_CHOICES = [
        ('high', '高'),
        ('medium', '中'),
        ('low', '低'),
    ]

    analysis = models.ForeignKey(RequirementAnalysis, on_delete=models.CASCADE, related_name='requirements',
                                 verbose_name='关联分析')
    requirement_id = models.CharField(max_length=50, verbose_name='需求编号')
    requirement_name = models.CharField(max_length=200, verbose_name='需求名称')
    requirement_type = models.CharField(max_length=20, choices=REQUIREMENT_TYPE_CHOICES, verbose_name='需求类型')
    parent_requirement = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True,
                                           verbose_name='父级需求')
    module = models.CharField(max_length=100, verbose_name='所属模块')
    requirement_level = models.CharField(max_length=10, choices=REQUIREMENT_LEVEL_CHOICES, verbose_name='需求级别')
    reviewer = models.CharField(max_length=50, verbose_name='评审人', default='admin')
    estimated_hours = models.PositiveIntegerField(verbose_name='预计工时', default=8)
    description = models.TextField(verbose_name='需求描述')
    acceptance_criteria = models.TextField(verbose_name='验收标准')
    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'business_requirements'
        verbose_name = '业务需求'
        verbose_name_plural = '业务需求'
        ordering = ['-created_at']
        unique_together = ['analysis', 'requirement_id']

    def __str__(self):
        return f"{self.requirement_id} - {self.requirement_name}"


class GeneratedTestCase(models.Model):
    """生成的测试用例模型"""
    PRIORITY_CHOICES = [
        ('P0', '最高优先级'),
        ('P1', '高优先级'),
        ('P2', '中优先级'),
        ('P3', '低优先级'),
    ]

    STATUS_CHOICES = [
        ('generated', '已生成'),
        ('reviewing', '评审中'),
        ('reviewed', '已评审'),
        ('approved', '已批准'),
        ('rejected', '已拒绝'),
        ('adopted', '已采纳'),
        ('discarded', '已弃用'),
    ]

    requirement = models.ForeignKey(BusinessRequirement, on_delete=models.CASCADE, related_name='test_cases',
                                    verbose_name='关联需求')
    case_id = models.CharField(max_length=50, verbose_name='用例编号')
    title = models.CharField(max_length=300, verbose_name='用例标题')
    priority = models.CharField(max_length=5, choices=PRIORITY_CHOICES, verbose_name='优先级')
    precondition = models.TextField(verbose_name='前置条件')
    test_steps = models.TextField(verbose_name='测试步骤')
    expected_result = models.TextField(verbose_name='预期结果')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='generated', verbose_name='状态')
    generated_by_ai = models.CharField(max_length=50, verbose_name='生成AI模型', default='AI-A')
    reviewed_by_ai = models.CharField(max_length=50, verbose_name='评审AI模型', null=True, blank=True)
    review_comments = models.TextField(verbose_name='评审意见', blank=True)
    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'generated_test_cases'
        verbose_name = '生成的测试用例'
        verbose_name_plural = '生成的测试用例'
        ordering = ['-created_at']
        unique_together = ['requirement', 'case_id']

    def __str__(self):
        return f"{self.case_id} - {self.title[:50]}"


class AnalysisTask(models.Model):
    """分析任务模型"""
    TASK_TYPE_CHOICES = [
        ('requirement_analysis', '需求分析'),
        ('testcase_generation', '测试用例生成'),
        ('testcase_review', '测试用例评审'),
    ]

    STATUS_CHOICES = [
        ('pending', '待处理'),
        ('running', '运行中'),
        ('completed', '已完成'),
        ('failed', '失败'),
    ]

    task_id = models.CharField(max_length=100, unique=True, verbose_name='任务ID')
    task_type = models.CharField(max_length=30, choices=TASK_TYPE_CHOICES, verbose_name='任务类型')
    document = models.ForeignKey(RequirementDocument, on_delete=models.CASCADE, related_name='tasks',
                                 verbose_name='关联文档')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name='状态')
    progress = models.PositiveIntegerField(default=0, verbose_name='进度百分比')
    result = models.JSONField(verbose_name='任务结果', null=True, blank=True)
    error_message = models.TextField(verbose_name='错误信息', blank=True)
    started_at = models.DateTimeField(null=True, blank=True, verbose_name='开始时间')
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name='完成时间')
    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')

    class Meta:
        db_table = 'analysis_tasks'
        verbose_name = '分析任务'
        verbose_name_plural = '分析任务'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.task_id} - {self.get_task_type_display()}"


class AIModelConfig(models.Model):
    """AI模型配置模型"""
    MODEL_CHOICES = [
        ('openai', 'OpenAI (GPT)'),
        ('azure_openai', 'Azure OpenAI'),
        ('anthropic', 'Anthropic Claude'),
        ('google_gemini', 'Google Gemini'),
        ('ollama', 'Ollama (本地)'),
        ('deepseek', 'DeepSeek'),
        ('qwen', '通义千问'),
        ('siliconflow', '硅基流动'),
        ('zhipu', '智谱GLM'),
        ('baichuan', '百川智能'),
        ('moonshot', '月之暗面(Kimi)'),
        ('doubao', '豆包(字节)'),
        ('other', '其他(兼容OpenAI API)'),
    ]

    ROLE_CHOICES = [
        ('writer', '测试用例编写专家'),
        ('reviewer', '测试评审专家'),
        ('browser_use_text', 'Browser Use - 文本模式'),
    ]

    name = models.CharField(max_length=100, verbose_name='配置名称')
    model_type = models.CharField(max_length=20, choices=MODEL_CHOICES, verbose_name='模型类型')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, verbose_name='角色')
    api_key = models.CharField(max_length=200, verbose_name='API Key', blank=True, null=True)
    base_url = models.URLField(verbose_name='API Base URL')
    model_name = models.CharField(max_length=100, verbose_name='模型名称')
    max_tokens = models.IntegerField(default=16384, verbose_name='最大Token数')
    temperature = models.FloatField(default=0.8, verbose_name='温度参数')
    top_p = models.FloatField(default=0.9, verbose_name='Top P参数')
    verify_ssl = models.BooleanField(default=True, verbose_name='SSL证书校验')
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='创建者')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'ai_model_config'
        verbose_name = 'AI模型配置'
        verbose_name_plural = 'AI模型配置'
        # 移除 unique_together 约束，允许同一个 role 有多个配置
        # 在应用层面通过代码控制：每个 role 只能有一个 is_active=True 的配置

    def __str__(self):
        return f"{self.get_model_type_display()} - {self.get_role_display()}"

    @classmethod
    def get_active_config(cls, model_type: str, role: str):
        """获取活跃的配置"""
        return cls.objects.filter(
            model_type=model_type,
            role=role,
            is_active=True
        ).first()


class PromptConfig(models.Model):
    """提示词配置模型"""
    PROMPT_CHOICES = [
        ('writer', '用例编写提示词'),
        ('reviewer', '用例评审提示词'),
        ('clarifier', '需求评审/澄清提示词'),
    ]

    name = models.CharField(max_length=100, verbose_name='配置名称')
    prompt_type = models.CharField(max_length=20, choices=PROMPT_CHOICES, verbose_name='提示词类型')
    content = models.TextField(verbose_name='提示词内容')
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='创建者')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'prompt_config'
        verbose_name = '提示词配置'
        verbose_name_plural = '提示词配置'

    def __str__(self):
        return f"{self.get_prompt_type_display()} - {self.name}"

    @classmethod
    def get_active_config(cls, prompt_type: str):
        """获取活跃的提示词配置"""
        return cls.objects.filter(
            prompt_type=prompt_type,
            is_active=True
        ).first()


class GenerationConfig(models.Model):
    """生成行为配置模型"""
    OUTPUT_MODE_CHOICES = [
        ('stream', '实时流式输出'),
        ('complete', '完整输出'),
    ]

    name = models.CharField(max_length=100, verbose_name='配置名称', default='默认生成配置')
    default_output_mode = models.CharField(
        max_length=10,
        choices=OUTPUT_MODE_CHOICES,
        default='stream',
        verbose_name='默认输出模式',
        help_text='测试用例生成的默认输出方式'
    )

    # 扩展配置字段
    enable_auto_review = models.BooleanField(
        default=True,
        verbose_name='启用AI评审和改进',
        help_text='生成完成后自动进行AI评审，并根据评审意见改进测试用例'
    )
    review_timeout = models.IntegerField(
        default=120,
        verbose_name='评审和改进超时时间（秒）',
        help_text='AI评审和改进的最大等待时间（总时长）'
    )

    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'generation_config'
        verbose_name = '生成行为配置'
        verbose_name_plural = '生成行为配置'

    def __str__(self):
        return self.name

    @classmethod
    def get_active_config(cls):
        """获取活跃的生成配置"""
        return cls.objects.filter(is_active=True).first()


class TestCaseGenerationTask(models.Model):
    """测试用例生成任务模型"""
    STATUS_CHOICES = [
        ('pending', '等待中'),
        ('pending_clarification', '待需求澄清'),
        ('clarified', '澄清完成-待生成'),
        ('generating', '生成中'),
        ('writing', '用例编写中'),
        ('reviewing', '评审中'),
        ('revising', '改进中'),
        ('completing', '完成中'),
        ('completed', '已完成'),
        ('failed', '失败'),
        ('cancelled', '已取消'),
    ]

    OUTPUT_MODE_CHOICES = [
        ('stream', '实时流式输出'),
        ('complete', '完整输出'),
    ]

    task_id = models.CharField(max_length=50, unique=True, verbose_name='任务ID')
    title = models.CharField(max_length=200, verbose_name='任务标题')
    requirement_text = models.TextField(verbose_name='需求描述')
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='pending', verbose_name='状态')
    progress = models.IntegerField(default=0, verbose_name='进度百分比')

    # 流式输出配置
    output_mode = models.CharField(
        max_length=10,
        choices=OUTPUT_MODE_CHOICES,
        default='stream',
        verbose_name='输出模式'
    )

    # 流式缓冲区和状态跟踪
    stream_buffer = models.TextField(blank=True, verbose_name='流式输出缓冲区')
    stream_position = models.IntegerField(default=0, verbose_name='流式输出位置')
    last_stream_update = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='最后流式更新时间'
    )

    project = models.ForeignKey(
        Project,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='generation_tasks',
        verbose_name='关联项目'
    )

    # 配置参数
    source_document = models.ForeignKey(
        RequirementDocument,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='linked_generation_tasks',
        verbose_name='来源需求文档'
    )

    writer_model_config = models.ForeignKey(
        AIModelConfig, on_delete=models.SET_NULL, null=True,
        related_name='writer_tasks', verbose_name='编写模型配置'
    )
    reviewer_model_config = models.ForeignKey(
        AIModelConfig, on_delete=models.SET_NULL, null=True,
        related_name='reviewer_tasks', verbose_name='评审模型配置'
    )
    writer_prompt_config = models.ForeignKey(
        PromptConfig, on_delete=models.SET_NULL, null=True,
        related_name='writer_tasks', verbose_name='编写提示词配置'
    )
    reviewer_prompt_config = models.ForeignKey(
        PromptConfig, on_delete=models.SET_NULL, null=True,
        related_name='reviewer_tasks', verbose_name='评审提示词配置'
    )

    # 生成结果
    requirement_breakdown = models.TextField(blank=True, verbose_name='需求模块拆解')
    generated_test_cases = models.TextField(blank=True, verbose_name='生成的测试用例')
    review_feedback = models.TextField(blank=True, verbose_name='评审反馈')
    final_test_cases = models.TextField(blank=True, verbose_name='最终测试用例')

    # 元数据
    generation_log = models.TextField(blank=True, verbose_name='生成日志')
    error_message = models.TextField(blank=True, verbose_name='错误信息')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='创建者')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name='完成时间')
    is_saved_to_records = models.BooleanField(default=False, verbose_name='是否已保存到记录')
    saved_at = models.DateTimeField(null=True, blank=True, verbose_name='保存到记录时间')

    class Meta:
        db_table = 'testcase_generation_task'
        verbose_name = '测试用例生成任务'
        verbose_name_plural = '测试用例生成任务'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} - {self.get_status_display()}"

    def resolve_source_document(self):
        if self.source_document_id:
            return self.source_document

        return RequirementDocument.objects.filter(
            title=self.title
        ).order_by('-created_at').first()


class RequirementClarification(models.Model):
    """需求澄清多轮对话记录"""
    ROLE_CHOICES = [
        ('ai', 'AI'),
        ('user', '用户'),
    ]

    task = models.ForeignKey(
        TestCaseGenerationTask,
        on_delete=models.CASCADE,
        related_name='clarifications',
        verbose_name='关联任务'
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, verbose_name='角色')
    content = models.TextField(verbose_name='内容')
    order = models.PositiveIntegerField(default=0, verbose_name='排序')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        db_table = 'requirement_clarification'
        verbose_name = '需求澄清对话'
        verbose_name_plural = '需求澄清对话'
        ordering = ['order', 'created_at']

    def __str__(self):
        return f"{self.task.task_id} #{self.order} [{self.role}]"


class AIModelService:
    """AI模型服务类"""

    @staticmethod
    async def call_openai_compatible_api(
            config: AIModelConfig,
            messages: List[Dict[str, str]],
            max_tokens: int = None
    ) -> Dict[str, Any]:
        """
        调用OpenAI兼容格式的API

        Args:
            config: AI模型配置
            messages: 消息列表
            max_tokens: 可选的最大token数，如果不指定则使用config.max_tokens

        Returns:
            API响应字典
        """
        headers = {
            'Authorization': f'Bearer {config.api_key}',
            'Content-Type': 'application/json'
        }

        # 使用传入的max_tokens或默认使用config.max_tokens
        actual_max_tokens = max_tokens if max_tokens is not None else config.max_tokens

        data = {
            'model': config.model_name,
            'messages': messages,
            'max_tokens': actual_max_tokens,
            'temperature': config.temperature,
            'top_p': config.top_p,
            'stream': False
        }

        # 确保base_url不以/结尾
        base_url = config.base_url.rstrip('/')
        # 如果用户没有输入完整的/chat/completions路径，尝试智能补全
        if not base_url.endswith('/chat/completions'):
            # 检查是否已经包含版本号（如v1, v4等）
            import re
            version_match = re.search(r'/v(\d+)/?$', base_url)
            if version_match:
                # 如果已经以版本号结尾（如/v1, /v4），直接添加/chat/completions
                url = f"{base_url}/chat/completions"
            else:
                # 默认假设是根路径，尝试添加 v1/chat/completions
                # 但对于某些API（如DeepSeek），base_url可能已经是 https://api.deepseek.com
                url = f"{base_url}/v1/chat/completions"
        else:
            url = base_url

        logger.info(f"=== API调用详情 ===")
        logger.info(f"原始base_url: {config.base_url}")
        logger.info(f"最终请求URL: {url}")
        logger.info(f"模型名称: {config.model_name}")
        logger.info(f"请求参数: max_tokens={actual_max_tokens}, temperature={config.temperature}, top_p={config.top_p}")

        try:
            # 增加HTTP超时时间到900秒（15分钟），支持大文档生成
            # 禁用HTTP/2，使用HTTP/1.1以提高兼容性
            # 显式设置所有超时参数，避免默认的连接超时导致请求失败
            timeout_config = httpx.Timeout(
                connect=60.0,  # 连接超时：60秒
                read=900.0,  # 读取超时：900秒（15分钟）
                write=60.0,  # 写入超时：60秒
                pool=60.0  # 连接池超时：60秒
            )
            async with httpx.AsyncClient(timeout=timeout_config, http2=False, verify=config.verify_ssl) as client:
                logger.info(f"发送POST请求到: {url}")
                response = await client.post(
                    url,
                    headers=headers,
                    json=data
                )

                logger.info(f"收到响应: status_code={response.status_code}")

                if response.status_code != 200:
                    error_detail = response.text
                    logger.error(f"API调用返回错误: Status={response.status_code}, Body={error_detail}")

                response.raise_for_status()
                result = response.json()
                logger.info(f"API调用成功，响应内容: {str(result)[:200]}...")
                return result
        except httpx.HTTPStatusError as e:
            provider_name = config.get_model_type_display()
            error_msg = f"{provider_name} API返回错误 {e.response.status_code}: {e.response.text}"
            logger.error(error_msg)
            raise Exception(error_msg)
        except httpx.TimeoutException as e:
            provider_name = config.get_model_type_display()
            logger.error(f"{provider_name} API请求超时: {repr(e)}")
            raise Exception(f"{provider_name} API请求超时，请稍后再试或检查网络连接")
        except Exception as e:
            provider_name = config.get_model_type_display()
            # Use repr(e) to capture the full exception type and message, especially if str(e) is empty
            logger.error(f"{provider_name} API调用失败: {repr(e)}")
            raise Exception(f"{provider_name} API调用失败: {str(e) or repr(e)}")

    @staticmethod
    async def call_deepseek_api(config: AIModelConfig, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """调用DeepSeek API (兼容OpenAI格式)"""
        return await AIModelService.call_openai_compatible_api(config, messages)

    @staticmethod
    async def call_qwen_api(config: AIModelConfig, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """调用千问API (兼容OpenAI格式)"""
        return await AIModelService.call_openai_compatible_api(config, messages)

    @staticmethod
    async def call_openai_compatible_api_stream(
            config: AIModelConfig,
            messages: List[Dict[str, str]],
            callback=None,
            max_tokens: int = None
    ) -> AsyncIterator[str]:
        """
        流式调用OpenAI兼容格式的API，支持自动续写
        """
        headers = {
            'Authorization': f'Bearer {config.api_key}',
            'Content-Type': 'application/json'
        }

        # 使用传入的max_tokens或默认使用config.max_tokens
        actual_max_tokens = max_tokens if max_tokens is not None else config.max_tokens

        # 确保base_url不以/结尾
        base_url = config.base_url.rstrip('/')
        if not base_url.endswith('/chat/completions'):
            # 检查是否已经包含版本号（如v1, v4等）
            import re
            version_match = re.search(r'/v(\d+)/?$', base_url)
            if version_match:
                # 如果已经以版本号结尾（如/v1, /v4），直接添加/chat/completions
                url = f"{base_url}/chat/completions"
            else:
                # 默认假设是根路径，尝试添加 v1/chat/completions
                url = f"{base_url}/v1/chat/completions"
        else:
            url = base_url

        # 续写控制
        current_messages = list(messages)  # 浅拷贝
        continuation_count = 0
        MAX_CONTINUATIONS = 5  # 最大续写次数，防止死循环

        while continuation_count <= MAX_CONTINUATIONS:
            data = {
                'model': config.model_name,
                'messages': current_messages,
                'max_tokens': actual_max_tokens,
                'temperature': config.temperature,
                'top_p': config.top_p,
                'stream': True
            }

            logger.info(f"发起流式请求 (第{continuation_count + 1}次), messages数量: {len(current_messages)}")

            chunk_content_buffer = ""  # 本次请求生成的完整内容缓存
            finish_reason = None

            try:
                # 显式设置所有超时参数
                timeout_config = httpx.Timeout(
                    connect=60.0,  # 连接超时：60秒
                    read=900.0,  # 读取超时：900秒（15分钟）
                    write=60.0,  # 写入超时：60秒
                    pool=60.0  # 连接池超时：60秒
                )
                async with httpx.AsyncClient(timeout=timeout_config, http2=False, verify=config.verify_ssl) as client:
                    async with client.stream('POST', url, headers=headers, json=data) as response:
                        if response.status_code != 200:
                            error_detail = await response.aread()
                            error_msg = error_detail.decode('utf-8')
                            logger.error(f"流式API调用返回错误: Status={response.status_code}, Body={error_msg}")
                            response.raise_for_status()

                        async for line in response.aiter_lines():
                            if not line.strip():
                                continue

                            if line.startswith('data: '):
                                data_str = line[6:]
                                if data_str.strip() == '[DONE]':
                                    break

                                try:
                                    chunk_data = json.loads(data_str)
                                    if 'choices' in chunk_data and len(chunk_data['choices']) > 0:
                                        choice = chunk_data['choices'][0]
                                        delta = choice.get('delta', {})
                                        finish_reason = choice.get('finish_reason', None)
                                        content = delta.get('content', '')

                                        if content:
                                            chunk_content_buffer += content
                                            if callback:
                                                await callback(content)
                                            yield content

                                        # 如果在中途就收到了finish_reason（有些流式实现会在最后一条数据带上finish_reason）
                                        if finish_reason:
                                            pass

                                except json.JSONDecodeError:
                                    continue

                # 本次请求结束
                # 检查 finish_reason
                if finish_reason == 'length':
                    logger.warning(
                        f"检测到生成被截断 (finish_reason='length')，准备自动续写。当前已续写 {continuation_count} 次。")
                    continuation_count += 1

                    # 将本次生成的内容作为 assistant 回复加入历史
                    # 注意：如果之前已经有assistant消息，需要追加内容而不是新增消息
                    if current_messages[-1]['role'] == 'assistant':
                        current_messages[-1]['content'] += chunk_content_buffer
                    else:
                        current_messages.append({"role": "assistant", "content": chunk_content_buffer})

                    # 只有当上一条不是user的续写指令时，才添加新的user指令
                    # 防止多次续写时堆叠重复的 user 指令
                    if current_messages[-1]['role'] != 'user':
                        current_messages.append(
                            {"role": "user", "content": "请继续输出剩余的内容，不要重复已输出的部分，紧接着上文继续。"})

                    # 发送换行符以分隔续写内容（可选，视模型而定，通常不需要，但为了保险）
                    # yield "\n"
                    continue
                else:
                    logger.info(f"流式生成正常结束 (finish_reason={finish_reason})")
                    break

            except Exception as e:
                logger.error(f"流式请求异常: {e}")
                # 如果是超时或其他网络错误，可能需要重试机制，这里暂时直接抛出
                raise e

    @staticmethod
    async def generate_test_cases(task: TestCaseGenerationTask) -> str:
        """生成测试用例"""
        writer_prompt = task.writer_prompt_config.content

        # 所有规则由数据库中的Writer Prompt（system角色）控制
        # user_message 只需传递需求文档内容
        user_message = f"【需求文档内容】\n{task.requirement_text}"

        messages = [
            {"role": "system", "content": writer_prompt},
            {"role": "user", "content": user_message}
        ]

        # 使用兼容OpenAI的接口，不硬编码max_tokens
        response = await AIModelService.call_openai_compatible_api(
            task.writer_model_config,
            messages
        )

        return response['choices'][0]['message']['content']

    @staticmethod
    async def clarify_requirements(
        clarifier_config,
        clarifier_prompt: str,
        requirement_text: str,
        history: list,
    ) -> str:
        """需求澄清多轮对话。

        Args:
            clarifier_config: AIModelConfig（复用 writer 或专用 clarifier role）
            clarifier_prompt: system prompt 内容
            requirement_text: 原始需求文档
            history: [{'role': 'ai'|'user', 'content': str}, ...] 已有对话
        Returns:
            AI 本轮回复文本
        """
        messages = [
            {"role": "system", "content": clarifier_prompt},
            {"role": "user", "content": f"【需求文档】\n{requirement_text}"},
        ]
        for msg in history:
            role = 'assistant' if msg.get('role') == 'ai' else 'user'
            messages.append({"role": role, "content": msg.get('content', '')})

        response = await AIModelService.call_openai_compatible_api(
            clarifier_config,
            messages,
        )
        return response['choices'][0]['message']['content']

    @staticmethod
    async def review_test_cases(task: TestCaseGenerationTask, test_cases: str) -> str:
        """评审测试用例"""
        try:
            reviewer_prompt = task.reviewer_prompt_config.content

            # 增强的评审指令
            user_message = (
                f"请对以下生成的测试用例进行严格的专家级评审。\n\n"
                f"【评审重点】\n"
                f"1. **覆盖率漏洞**：请仔细比对用例集是否覆盖了常见的异常场景（如断网、超时、数据冲突）和边界条件。\n"
                f"2. **逻辑严密性**：检查预期结果是否具体、可验证（例如'提示错误'是不够的，需说明具体错误码或文案）。\n"
                f"3. **冗余检查**：指出是否有重复或无效的用例。\n\n"
                f"【待评审用例】\n{test_cases}\n\n"
                f"【输出格式要求】\n"
                f"请输出一份包含评分、问题列表和改进建议的详细评审报告。"
                f"**重要**：输出格式要求紧凑，不要在段落之间添加多余的空行，每个问题点之间用单空行分隔即可，用例展示仍为markdown形式。"
            )

            messages = [
                {"role": "system", "content": reviewer_prompt},
                {"role": "user", "content": user_message}
            ]

            # 所有支持的模型都使用兼容OpenAI的接口
            response = await AIModelService.call_openai_compatible_api(task.reviewer_model_config, messages)

            return response['choices'][0]['message']['content']
        except Exception as e:
            logger.error(f"评审测试用例时出错: {e}")
            # 返回一个默认的评审结果
            return f"评审过程中出现错误: {str(e)}\n\n建议：测试用例结构完整，可以使用。"

    @staticmethod
    async def generate_test_cases_stream(
            task: TestCaseGenerationTask,
            callback=None
    ) -> str:
        """
        流式生成测试用例

        Args:
            task: 生成任务对象
            callback: 可选的回调函数，每收到一个chunk就调用，用于实时保存到数据库

        Returns:
            str: 完整的测试用例内容
        """
        writer_prompt = task.writer_prompt_config.content

        # 所有规则由数据库中的Writer Prompt（system角色）控制
        # user_message 只需传递需求文档内容
        user_message = f"【需求文档内容】\n{task.requirement_text}"

        messages = [
            {"role": "system", "content": writer_prompt},
            {"role": "user", "content": user_message}
        ]

        # 流式调用API，使用配置的max_tokens
        generator = AIModelService.call_openai_compatible_api_stream(
            task.writer_model_config,
            messages,
            callback=callback
        )

        full_content = ""
        chunk_count = 0
        try:
            async for chunk in generator:
                full_content += chunk
                chunk_count += 1
        except Exception as e:
            logger.error(f"流式生成测试用例时出错: {e}")
            raise
        finally:
            # 确保生成器被正确关闭
            try:
                await generator.aclose()
            except Exception as close_error:
                logger.warning(f"关闭generator时出错: {close_error}")

        logger.info(f"流式生成完成: 总chunk数={chunk_count}, 总字符数={len(full_content)}")

        # 统计生成的用例数量
        case_count = full_content.count('TC-') + full_content.count('TEST-') + full_content.count('测试用例')
        logger.info(f"生成用例统计: 约检测到{case_count}个用例编号标记")

        return full_content

    @staticmethod
    async def review_test_cases_stream(
            task: TestCaseGenerationTask,
            test_cases: str,
            callback=None
    ) -> str:
        """
        流式评审测试用例

        Args:
            task: 生成任务对象
            test_cases: 待评审的测试用例
            callback: 可选的回调函数，每收到一个chunk就调用

        Returns:
            str: 完整的评审反馈
        """
        reviewer_prompt = task.reviewer_prompt_config.content

        # 增强的评审指令
        user_message = (
            f"请对以下生成的测试用例进行严格的专家级评审。\n\n"
            f"【评审重点】\n"
            f"1. **覆盖率漏洞**：请仔细比对用例集是否覆盖了常见的异常场景（如断网、超时、数据冲突）和边界条件。\n"
            f"2. **逻辑严密性**：检查预期结果是否具体、可验证（例如'提示错误'是不够的，需说明具体错误码或文案）。\n"
            f"3. **冗余检查**：指出是否有重复或无效的用例。\n\n"
            f"【待评审用例】\n{test_cases}\n\n"
            f"【输出格式要求】\n"
            f"请输出一份包含评分、问题列表和改进建议的详细评审报告。"
            f"**重要**：输出格式要求紧凑，不要在段落之间添加多余的空行，每个问题点之间用单空行分隔即可，用例展示仍为markdown形式。"
        )

        messages = [
            {"role": "system", "content": reviewer_prompt},
            {"role": "user", "content": user_message}
        ]

        # 流式调用API，确保正确关闭生成器
        generator = AIModelService.call_openai_compatible_api_stream(
            task.reviewer_model_config,
            messages,
            callback=callback
        )

        full_content = ""
        chunk_count = 0
        try:
            async for chunk in generator:
                full_content += chunk
                chunk_count += 1
        except Exception as e:
            logger.error(f"流式评审测试用例时出错: {e}")
            return f"评审过程中出现错误: {str(e)}\n\n建议：测试用例结构完整，可以使用。"
        finally:
            # 确保生成器被正确关闭
            try:
                await generator.aclose()
            except Exception as close_error:
                logger.warning(f"关闭generator时出错: {close_error}")

        logger.info(f"流式评审完成: 总chunk数={chunk_count}, 总字符数={len(full_content)}")
        return full_content

    @staticmethod
    async def revise_test_cases_based_on_review(
            task: TestCaseGenerationTask,
            original_test_cases: str,
            review_feedback: str,
            callback=None
    ) -> str:
        """
        根据评审意见改进测试用例

        Args:
            task: 生成任务对象
            original_test_cases: 原始生成的测试用例
            review_feedback: AI评审意见
            callback: 可选的回调函数，每收到一个chunk就调用

        Returns:
            str: 改进后的测试用例
        """
        writer_prompt = task.writer_prompt_config.content

        # 构建改进指令（增量模式：AI 只输出有改动的用例，系统自动合并）
        user_message = (
            f"请根据以下专家评审意见，改进和完善测试用例。\n\n"
            f"【原始测试用例】\n{original_test_cases}\n\n"
            f"【评审意见】\n{review_feedback}\n\n"
            f"【⚠️ 增量输出模式 — 关键约束（违反将导致输出无效）】\n"
            f"本次采用【增量输出模式】，你的输出会被系统按编号自动合并回原始用例：\n"
            f"1. **只输出有改动的用例**（包括：被修改的、被新增的）。\n"
            f"2. **未修改的用例请直接省略，不要重复输出**。系统会自动保留它们。\n"
            f"3. **保留原始用例的表头**（| 所属模块 | 用例ID | ... |）\n"
            f"4. **绝对不要试图重写整份用例**，否则会被判定为输出无效。\n"
            f"5. **修改原有用例时**，必须保留原 ID，例如修改 CARD-001 就输出 CARD-001 而非新 ID。\n"
            f"6. **新增用例时**，编号必须延续原有规则（如原最后是 CARD-015，新增就是 CARD-016；如果是新模块，使用合理的新前缀如 NEW-001）。\n\n"
            f"【改进操作类型】\n"
            f"你有四种操作可选（每条改动必须明确归属一种）：\n"
            f"1. **修改**（评审指出预期结果不对/步骤不全/优先级错误）\n"
            f"   → 输出修改后的整行用例，保留原 ID\n"
            f"   → 例：`| 玩家主页 | CARD-001 | ... | **修改后内容** | ... |`\n"
            f"2. **新增**（评审指出缺少某类场景）\n"
            f"   → 输出新的测试用例行，编号延续规则\n"
            f"   → 例：`| **安全模块** | **SECURITY-001** | **新增测试目标** | ... |`（全部加粗）\n"
            f"3. **删除**（评审明确说某条冗余/重复，建议删除或合并）\n"
            f"   → **必须显式标记**：在 ID 后追加 `[DELETE]`，其他列可省略只填空 `-`\n"
            f"   → 例：`| - | MUT-003[DELETE] | - | - | - | - | - |`\n"
            f"   → ⚠️ **不允许用'省略不输出'的方式删除用例！省略 = 系统保留原样**\n"
            f"4. **无需改动**（评审未提及，或提及但你认为原内容已正确）\n"
            f"   → 直接省略不输出该用例。系统会自动保留原版本。\n\n"
            f"【加粗标记规则（用于前端高亮区分新增/修改部分）】\n"
            f"- **新增的整条用例**：所有单元格内容都用 ** 包裹，如 **CARD-016** | **新场景标题** | ...\n"
            f"- **修改现有用例的某个字段**：只对修改的字段内容加粗，未改字段保持原样\n"
            f"- 未修改的字段不要加粗\n\n"
            f"【特殊字符处理】\n"
            f"- 如果在表格内容中出现管道符 '|'，请使用 HTML 实体 '&#124;' 代替\n"
            f"- 不要使用反斜杠转义（如 '\\|'），会导致输出混乱\n\n"
            f"【输出示例】\n"
            f"假设原始有 100 条用例（CARD-001~050, TEAM-001~030, VOICE-001~020），评审意见只指出 CARD-004 预期结果有误 + 需要新增一条 SECURITY 场景，那么你的输出应该是：\n"
            f"```\n"
            f"| 所属模块 | 用例ID | 用例目标 | 前置条件 | 操作步骤 | 预期结果 | 优先级 | 用例分类 | 适配版本 |\n"
            f"|---------|--------|---------|---------|---------|---------|--------|---------|---------|\n"
            f"| 玩家主页 | CARD-004 | 验证未绑定输入PUBG ID进入授权 | 前置条件 | 操作步骤 | **修改后的准确预期结果** | P0 | 功能测试 | 6.1.1 |\n"
            f"| **安全模块** | **SECURITY-001** | **验证XSS注入防护** | **前置条件** | **操作步骤** | **预期结果** | **P0** | **安全测试** | **6.1.1** |\n"
            f"```\n"
            f"系统会自动保留其他 99 条未修改的用例，最终合并为 101 条（100 原始 + 1 新增）。\n\n"
            f"现在请直接输出表头 + 仅有改动的用例行，不要任何说明性文字。"
        )

        messages = [
            {"role": "system", "content": writer_prompt},
            {"role": "user", "content": user_message}
        ]

        # 流式调用API，确保正确关闭生成器
        # 使用配置的max_tokens，不硬编码限制
        generator = AIModelService.call_openai_compatible_api_stream(
            task.writer_model_config,
            messages,
            callback=callback
            # 不再硬编码max_tokens，使用配置文件中的值（如32000）
        )

        full_content = ""
        chunk_count = 0
        try:
            async for chunk in generator:
                full_content += chunk
                chunk_count += 1
        except Exception as e:
            logger.error(f"根据评审意见改进测试用例时出错: {e}")
            # 改进失败时返回原始用例
            return original_test_cases
        finally:
            # 确保生成器被正确关闭
            try:
                await generator.aclose()
            except Exception as close_error:
                logger.warning(f"关闭generator时出错: {close_error}")

        logger.info(f"流式改进完成: 总chunk数={chunk_count}, 总字符数={len(full_content)}")

        # 统计改进后的用例数量
        case_count = full_content.count('TC-') + full_content.count('**TC-') + full_content.count('测试用例')
        logger.info(f"改进用例统计: 约检测到{case_count}个用例编号标记")

        return full_content

    @staticmethod
    def sort_test_cases_by_id(test_cases_content: str) -> str:
        """
        按照测试用例编号排序测试用例内容

        Args:
            test_cases_content: 测试用例内容（字符串）

        Returns:
            str: 排序后的测试用例内容
        """
        if not test_cases_content:
            return test_cases_content

        import re

        # 按行分割内容
        lines = test_cases_content.split('\n')

        # 识别用例块：每个用例从包含编号的行开始
        # 支持多种编号格式：TC-001, TC001, TEST-001, 测试用例1, 1. 等
        case_pattern = re.compile(r'^(#{1,6}\s+)?(?:TC[-_]?\d+|TEST[-_]?\d+|测试用例\d+|\d+[\.\、]\s*[:：]?\s*\S+)',
                                  re.IGNORECASE | re.MULTILINE)

        # 找到所有用例块的起始位置
        case_starts = []
        for i, line in enumerate(lines):
            if case_pattern.match(line):
                case_starts.append(i)

        # 如果没有找到编号，返回原内容
        if len(case_starts) < 2:
            logger.info(f"未检测到足够的用例编号（只找到{len(case_starts)}个），保持原顺序")
            return test_cases_content

        # 提取每个用例块
        case_blocks = []
        for i in range(len(case_starts)):
            start = case_starts[i]
            # 下一个用例的开始位置，或者文件末尾
            end = case_starts[i + 1] if i + 1 < len(case_starts) else len(lines)
            block_lines = lines[start:end]
            block_content = '\n'.join(block_lines)
            case_blocks.append({
                'start': start,
                'content': block_content,
                'first_line': block_lines[0] if block_lines else ''
            })

        # 提取编号用于排序
        def extract_case_id(block):
            first_line = block['first_line']
            # 尝试匹配各种编号格式
            # TC-001, TC001, TEST-001, 测试用例1, 1. xxx 等
            match = re.search(r'(?:TC[-_]?|TEST[-_]?|测试用例)?(\d+)', first_line, re.IGNORECASE)
            if match:
                return int(match.group(1))
            return 0

        # 按编号排序
        try:
            case_blocks.sort(key=extract_case_id)
            logger.info(f"成功对{len(case_blocks)}个测试用例按编号排序")
        except Exception as e:
            logger.warning(f"排序失败: {e}，保持原顺序")

        # 重新组合内容
        sorted_content = '\n'.join([block['content'] for block in case_blocks])

        return sorted_content

    @staticmethod
    def extract_cases_from_markdown_table(content: str) -> tuple:
        """
        从 markdown 表格格式的用例内容中提取 {case_id: full_row_text}
        返回 (header_lines, cases_dict, non_table_prefix, non_table_suffix)
        - header_lines: 表头行列表（通常是名称行 + 分隔行）
        - cases_dict: {case_id: row_line_text}。case_id 从第二列提取
        - non_table_prefix: 表格之前的内容（如标题、说明）
        - non_table_suffix: 表格之后的内容
        """
        import re

        if not content:
            return [], {}, '', ''

        lines = content.split('\n')
        header_lines = []
        cases_dict = {}
        prefix_lines = []
        suffix_lines = []
        table_started = False
        table_ended = False

        # 匹配用例 ID 的正则：CARD-001 / TC-001 / TC001 / TEAM-001 等等，也支持中文后缀列名
        case_id_pattern = re.compile(r'^[A-Z][A-Z0-9_]*[-_]?\d+$', re.IGNORECASE)

        for line in lines:
            stripped = line.strip()

            # 判断是否是表格行（以 | 开头且包含多个 |）
            is_table_row = stripped.startswith('|') and stripped.count('|') >= 2
            is_separator = '---' in stripped and is_table_row

            if not is_table_row:
                if table_started:
                    table_ended = True
                if table_ended:
                    suffix_lines.append(line)
                else:
                    prefix_lines.append(line)
                continue

            # 是表格行
            if table_ended:
                # 表格结束后又出现的表格行，合并进主表（容错）
                table_ended = False

            table_started = True
            cells = [c.strip() for c in stripped.split('|')[1:-1]]

            if is_separator:
                if len(header_lines) == 1:
                    header_lines.append(line)
                continue

            # 判断是否是表头（第二列不是 case_id 格式，且还未设置过表头）
            if len(header_lines) == 0:
                # 第一个表格行为表头
                header_lines.append(line)
                continue

            # 提取 case_id（第二列，去除加粗标记）
            if len(cells) >= 2:
                raw_id = cells[1].replace('**', '').strip()
                # 检查是否看起来像 case_id
                # 兼容 [DELETE] 标记：CARD-001[DELETE]
                is_delete = '[DELETE]' in raw_id
                pure_id = raw_id.replace('[DELETE]', '').strip()
                if case_id_pattern.match(pure_id):
                    # 用纯 ID 作为 key，但保留行内的 [DELETE] 标记供后续判断
                    raw_id = pure_id
                    cases_dict[raw_id] = (line, is_delete)
                    continue
                if False:  # dead code, see logic above
                    pass
                else:
                    # 不是有效 case_id，当作额外表头或垃圾行，追加到后缀
                    if not header_lines:
                        header_lines.append(line)
                    # 否则忽略（避免重复表头污染）

        return header_lines, cases_dict, '\n'.join(prefix_lines), '\n'.join(suffix_lines)

    @staticmethod
    def merge_revised_cases(original_content: str, revised_content: str) -> dict:
        """
        合并原始用例和 AI 修改后的用例。

        合并规则：
        - revised 中出现的 case_id → 用 revised 版本（AI 修过或新增）
        - original 中有但 revised 中没有的 case_id → 保留 original 版本（AI 未修过）
        - revised 中新增的 case_id（original 中不存在）→ 追加

        返回:
            {
                'merged_content': 合并后的完整 markdown,
                'stats': {
                    'original_count': N,
                    'revised_count': M,
                    'modified_count': X,  # revised 中与 original 重叠的部分
                    'new_count': Y,  # revised 中新增的部分
                    'untouched_count': Z,  # original 中 AI 未修的部分（从 original 保留）
                    'final_count': W,
                    'retention_rate': R,  # final_count / original_count
                }
            }
        """
        orig_header, orig_cases, orig_prefix, orig_suffix = AIModelService.extract_cases_from_markdown_table(
            original_content)
        rev_header, rev_cases, rev_prefix, rev_suffix = AIModelService.extract_cases_from_markdown_table(
            revised_content)

        # 合并 case dict：
        # - revised 中正常输出的 → 覆盖（修改）或新增
        # - revised 中标记 [DELETE] 的 → 从最终结果移除
        # - original 中 AI 未提及的 → 保留（未修改）
        # 注意：orig_cases 和 rev_cases 现在的 value 是 tuple(line, is_delete)
        merged_cases = {cid: row for cid, (row, _) in orig_cases.items()}  # 原始用例 ID→row
        modified_count = 0
        new_count = 0
        deleted_count = 0
        for case_id, (row, is_delete) in rev_cases.items():
            if is_delete:
                # 显式删除：从最终结果移除该 ID
                if case_id in merged_cases:
                    del merged_cases[case_id]
                    deleted_count += 1
                # 如果原始里都没有这个 ID 还要求删，忽略（无害）
            else:
                if case_id in merged_cases:
                    modified_count += 1
                else:
                    new_count += 1
                merged_cases[case_id] = row

        untouched_count = len(orig_cases) - modified_count - deleted_count
        final_count = len(merged_cases)
        retention_rate = (final_count / len(orig_cases)) if orig_cases else 0

        # 重新拼接：使用 original 的 header（保证列名一致），后面追加所有 case rows
        # case rows 按 ID 自然顺序排序，后续 sort_test_cases_by_id 会再次排序
        output_lines = []
        if orig_prefix:
            output_lines.append(orig_prefix)
        if orig_header:
            output_lines.extend(orig_header)
        elif rev_header:
            output_lines.extend(rev_header)

        # 按 case_id 自然排序（字符串排序足够）
        for case_id in sorted(merged_cases.keys()):
            output_lines.append(merged_cases[case_id])

        if orig_suffix:
            output_lines.append(orig_suffix)

        merged_content = '\n'.join(output_lines)

        return {
            'merged_content': merged_content,
            'stats': {
                'original_count': len(orig_cases),
                'revised_count': len(rev_cases),
                'modified_count': modified_count,
                'new_count': new_count,
                'deleted_count': deleted_count,
                'untouched_count': untouched_count,
                'final_count': final_count,
                'retention_rate': retention_rate,
            }
        }

    @staticmethod
    def fix_incomplete_last_case(test_cases_content: str) -> str:
        """
        检测并修复不完整的最后一条测试用例

        Args:
            test_cases_content: 测试用例内容

        Returns:
            str: 修复后的测试用例内容
        """
        if not test_cases_content:
            return test_cases_content

        lines = test_cases_content.split('\n')

        # 检查最后几行，找到最后一个表格行
        table_lines = []
        for i in range(len(lines) - 1, -1, -1):
            line = lines[i].strip()
            if line.startswith('|') and line.endswith('|'):
                table_lines.insert(0, (i, line))
                # 只检查最后10行
                if len(table_lines) >= 10:
                    break

        if not table_lines:
            return test_cases_content

        # 检查最后一个表格行是否完整（应该有7个|，即7列）
        last_line_index, last_line = table_lines[-1]
        column_count = last_line.count('|')

        # 正常的表格应该有7个|（开头+结尾+5个分隔符）
        if column_count < 7:
            logger.warning(f"检测到最后一条用例不完整: 只有{column_count}列，应该是7列")
            # 删除不完整的最后一条用例
            # 找到完整的上一条用例
            for i in range(len(table_lines) - 2, -1, -1):
                prev_index, prev_line = table_lines[i]
                if prev_line.count('|') >= 7:
                    # 截断到上一条完整用例的位置
                    fixed_content = '\n'.join(lines[:prev_index + 1])
                    logger.info(f"已删除不完整的最后一条用例，保留了{prev_index + 1}行")
                    return fixed_content

            # 如果找不到完整的上一条，直接删除最后5行
            fixed_content = '\n'.join(lines[:-5])
            logger.info(f"删除最后5行不完整的内容")
            return fixed_content

        return test_cases_content

    @staticmethod
    def renumber_test_cases(test_cases_content: str) -> str:
        """
        重新编号测试用例，使其编号连续

        Args:
            test_cases_content: 测试用例内容（字符串）

        Returns:
            str: 重新编号后的测试用例内容
        """
        if not test_cases_content:
            return test_cases_content

        import re

        lines = test_cases_content.split('\n')

        # 找到表格分隔线
        separator_line = None
        separator_index = -1
        for i, line in enumerate(lines):
            if line.strip().startswith('|') and '|' in line and '---' in line:
                separator_line = line
                separator_index = i
                break

        if not separator_line:
            logger.warning("未找到表格分隔线，无法重新编号")
            return test_cases_content

        # 计算列数
        column_count = separator_line.count('|')

        # 找到第一个数据行（包含编号的行）
        first_data_index = -1
        for i in range(separator_index + 1, len(lines)):
            line = lines[i]
            if line.strip().startswith('|') and line.count('|') == column_count:
                first_data_index = i
                break

        if first_data_index == -1:
            logger.warning("未找到任何数据行")
            return test_cases_content

        # 从第一个数据行中提取编号格式
        first_line = lines[first_data_index]
        parts = first_line.split('|')
        if len(parts) < 2:
            logger.warning("无法解析第一列")
            return test_cases_content

        # 获取第一列的编号（例如：IMMSG001）
        first_id = parts[1].strip()

        # 提取编号格式前缀（例如：IMMSG）
        id_match = re.match(r'^([A-Z]+)(\d+)$', first_id)
        if not id_match:
            logger.warning(f"无法识别编号格式: {first_id}")
            return test_cases_content

        prefix = id_match.group(1)  # 例如：IMMSG
        total_cases = 0

        # 重新编号所有数据行
        result_lines = lines[:first_data_index]
        i = first_data_index

        while i < len(lines):
            line = lines[i]

            # 检查是否是数据行
            if not line.strip().startswith('|'):
                # 不是表格行，添加并继续
                result_lines.append(line)
                i += 1
                continue

            # 检查列数是否正确
            if line.count('|') != column_count:
                # 列数不对，可能是空行或其他内容
                result_lines.append(line)
                i += 1
                continue

            # 这是一个数据行，重新编号
            total_cases += 1
            new_id = f"{prefix}{total_cases:03d}"  # 格式：IMMSG001

            # 替换第一列的编号，保持原有格式
            parts = line.split('|')
            if len(parts) >= 2:
                # 保持第一列（空）和第二列（编号）之间的空格
                # 只替换编号部分
                parts[1] = f" {new_id} "
                new_line = '|'.join(parts)
                result_lines.append(new_line)

            i += 1

        renumbered_content = '\n'.join(result_lines)
        logger.info(f"重新编号完成: 共{total_cases}条测试用例，编号范围: {prefix}001-{prefix}{total_cases:03d}")

        return renumbered_content

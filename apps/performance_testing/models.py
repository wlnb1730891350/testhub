from django.conf import settings
from django.db import models
from django.utils import timezone


class PerformanceProject(models.Model):
    """性能测试项目"""

    STATUS_CHOICES = [
        ('not_started', '未开始'),
        ('active', '进行中'),
        ('paused', '暂停'),
        ('completed', '已完成'),
        ('archived', '已归档'),
    ]

    name = models.CharField(max_length=200, verbose_name='项目名称')
    description = models.TextField(blank=True, default='', verbose_name='项目描述')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='not_started', verbose_name='项目状态')
    base_url = models.URLField(blank=True, default='', verbose_name='基础URL')
    start_date = models.DateField(null=True, blank=True, verbose_name='开始日期')
    end_date = models.DateField(null=True, blank=True, verbose_name='结束日期')
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='owned_performance_projects',
        verbose_name='负责人',
    )
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name='performance_projects',
        verbose_name='团队成员',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'load_testing_projects'
        verbose_name = '性能测试项目'
        verbose_name_plural = '性能测试项目'
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class PerformanceScript(models.Model):
    """性能测试脚本，内部使用结构化配置，JMX 作为导入/导出/执行格式"""

    SCRIPT_TYPE_CHOICES = [
        ('ONLINE', '在线编排'),
        ('JMX_UPLOAD', 'JMX导入'),
    ]

    STATUS_CHOICES = [
        ('draft', '草稿'),
        ('ready', '就绪'),
        ('archived', '已归档'),
    ]

    project = models.ForeignKey(
        PerformanceProject,
        on_delete=models.CASCADE,
        related_name='scripts',
        verbose_name='所属项目',
    )
    name = models.CharField(max_length=200, verbose_name='脚本名称')
    description = models.TextField(blank=True, default='', verbose_name='脚本描述')
    script_type = models.CharField(max_length=20, choices=SCRIPT_TYPE_CHOICES, default='ONLINE', verbose_name='脚本类型')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft', verbose_name='状态')
    config = models.JSONField(default=dict, blank=True, verbose_name='编排配置')
    original_jmx = models.FileField(upload_to='performance_testing/jmx/uploads/', null=True, blank=True, verbose_name='原始JMX')
    generated_jmx = models.FileField(upload_to='performance_testing/jmx/generated/', null=True, blank=True, verbose_name='生成JMX')
    import_warnings = models.JSONField(default=list, blank=True, verbose_name='导入告警')
    version = models.IntegerField(default=1, verbose_name='版本')
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_performance_scripts',
        verbose_name='创建人',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'load_testing_scripts'
        verbose_name = '性能测试脚本'
        verbose_name_plural = '性能测试脚本'
        ordering = ['-updated_at']

    def __str__(self):
        return self.name


class PerformanceDataset(models.Model):
    """性能测试参数化数据集"""

    project = models.ForeignKey(
        PerformanceProject,
        on_delete=models.CASCADE,
        related_name='datasets',
        verbose_name='所属项目',
    )
    name = models.CharField(max_length=200, verbose_name='数据集名称')
    description = models.TextField(blank=True, default='', verbose_name='数据集描述')
    file = models.FileField(upload_to='performance_testing/datasets/', verbose_name='数据文件')
    variables = models.JSONField(default=list, blank=True, verbose_name='变量列名')
    row_count = models.IntegerField(default=0, verbose_name='数据行数')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_performance_datasets',
        verbose_name='创建人',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'load_testing_datasets'
        verbose_name = '性能测试数据集'
        verbose_name_plural = '性能测试数据集'
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class PerformanceExecution(models.Model):
    """性能测试执行记录"""

    STATUS_CHOICES = [
        ('QUEUED', '排队中'),
        ('RUNNING', '运行中'),
        ('COMPLETED', '已完成'),
        ('FAILED', '失败'),
        ('CANCELLED', '已取消'),
    ]

    REPORT_STATUS_CHOICES = [
        ('PENDING', '待生成'),
        ('GENERATING', '生成中'),
        ('SUCCESS', '成功'),
        ('FAILED', '失败'),
        ('SKIPPED', '跳过'),
    ]

    project = models.ForeignKey(
        PerformanceProject,
        on_delete=models.CASCADE,
        related_name='executions',
        verbose_name='所属项目',
    )
    script = models.ForeignKey(
        PerformanceScript,
        on_delete=models.CASCADE,
        related_name='executions',
        verbose_name='性能脚本',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='QUEUED', verbose_name='执行状态')
    started_at = models.DateTimeField(null=True, blank=True, verbose_name='开始时间')
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name='结束时间')
    duration = models.FloatField(default=0, verbose_name='执行时长(秒)')
    executed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='performance_executions',
        verbose_name='执行人',
    )
    task_id = models.CharField(max_length=100, blank=True, default='', verbose_name='异步任务ID')
    jmeter_pid = models.IntegerField(null=True, blank=True, verbose_name='JMeter进程ID')
    jmx_path = models.CharField(max_length=500, blank=True, default='', verbose_name='JMX文件路径')
    jtl_path = models.CharField(max_length=500, blank=True, default='', verbose_name='JTL结果路径')
    log_path = models.CharField(max_length=500, blank=True, default='', verbose_name='执行日志路径')
    report_url = models.CharField(max_length=500, blank=True, default='', verbose_name='报告URL')
    report_status = models.CharField(max_length=20, choices=REPORT_STATUS_CHOICES, default='PENDING', verbose_name='报告状态')
    summary = models.JSONField(default=dict, blank=True, verbose_name='汇总指标')
    metrics = models.JSONField(default=dict, blank=True, verbose_name='详细指标')
    error_message = models.TextField(blank=True, default='', verbose_name='错误信息')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        db_table = 'load_testing_executions'
        verbose_name = '性能测试执行记录'
        verbose_name_plural = '性能测试执行记录'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.script.name} - {self.get_status_display()}'

    def mark_finished(self, status, error_message=''):
        self.status = status
        self.finished_at = timezone.now()
        if self.started_at:
            self.duration = (self.finished_at - self.started_at).total_seconds()
        if error_message:
            self.error_message = error_message
        self.save(update_fields=['status', 'finished_at', 'duration', 'error_message'])

from django.apps import AppConfig


class PerformanceTestingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.performance_testing'
    verbose_name = '性能测试'

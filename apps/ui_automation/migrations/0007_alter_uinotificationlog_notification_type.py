from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ui_automation', '0006_setuptemplate_aicase_setup_template'),
    ]

    operations = [
        migrations.AlterField(
            model_name='uinotificationlog',
            name='notification_type',
            field=models.CharField(
                choices=[
                    ('task_execution', '定时任务执行'),
                    ('test_suite_execution', '测试套件执行'),
                    ('test_case_execution', '测试用例执行'),
                    ('ai_test_report', 'AI测试报告'),
                    ('system_alert', '系统警告'),
                    ('manual', '手动通知'),
                ],
                max_length=50,
                verbose_name='通知类型',
            ),
        ),
    ]

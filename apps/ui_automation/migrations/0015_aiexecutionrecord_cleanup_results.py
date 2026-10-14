from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('ui_automation', '0014_backfill_desktop_task_descriptions'),
    ]

    operations = [
        migrations.AddField(
            model_name='aiexecutionrecord',
            name='cleanup_results',
            field=models.JSONField(blank=True, default=dict, verbose_name='环境回收结果'),
        ),
    ]

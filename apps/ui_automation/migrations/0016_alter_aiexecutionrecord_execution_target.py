from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('ui_automation', '0015_aiexecutionrecord_cleanup_results'),
    ]

    operations = [
        migrations.AlterField(
            model_name='aiexecutionrecord',
            name='execution_target',
            field=models.CharField(
                choices=[
                    ('web', 'Web Browser'),
                    ('desktop', 'Windows Desktop'),
                    ('dual', 'Browser and Windows Desktop'),
                ],
                default='web',
                max_length=20,
                verbose_name='Execution target',
            ),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ui_automation', '0012_desktop_app_profile'),
    ]

    operations = [
        migrations.AddField(
            model_name='aicase',
            name='desktop_task_description',
            field=models.TextField(blank=True, default='', help_text='The Windows-specific task description for a dual-mode case.', verbose_name='Windows desktop task description'),
        ),
        migrations.AddField(
            model_name='aicase',
            name='web_task_description',
            field=models.TextField(blank=True, default='', help_text='The browser-specific task description for a dual-mode case.', verbose_name='Browser task description'),
        ),
        migrations.AlterField(
            model_name='aicase',
            name='execution_target',
            field=models.CharField(choices=[('web', 'Web Browser'), ('desktop', 'Windows Desktop'), ('dual', 'Browser and Windows Desktop')], default='web', max_length=20, verbose_name='Execution target'),
        ),
    ]

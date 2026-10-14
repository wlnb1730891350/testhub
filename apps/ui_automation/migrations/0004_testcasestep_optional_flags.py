from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ui_automation', '0003_merge_ai_assert'),
    ]

    operations = [
        migrations.AddField(
            model_name='testcasestep',
            name='is_optional',
            field=models.BooleanField(default=False, verbose_name='找不到时跳过'),
        ),
        migrations.AddField(
            model_name='testcasestep',
            name='optional_note',
            field=models.CharField(blank=True, default='', max_length=200, verbose_name='跳过说明'),
            preserve_default=False,
        ),
    ]

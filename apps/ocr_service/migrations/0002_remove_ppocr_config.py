# -*- coding: utf-8 -*-
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ocr_service', '0001_initial'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='ocrconfig',
            name='use_gpu',
        ),
        migrations.AlterField(
            model_name='ocrconfig',
            name='provider',
            field=models.CharField(choices=[('tesseract', 'Tesseract OCR'), ('openai', 'OpenAI GPT-4V'), ('zhipu', '智谱 GLM-4V'), ('baidu', '百度 AI OCR'), ('tencent', '腾讯 OCR'), ('aliyun', '阿里云 OCR'), ('custom', '自定义 OCR')], max_length=20, verbose_name='OCR 服务提供商'),
        ),
    ]

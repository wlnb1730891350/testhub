from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('requirement_analysis', '0004_add_requirement_breakdown'),
    ]

    operations = [
        migrations.AddField(
            model_name='aimodelconfig',
            name='verify_ssl',
            field=models.BooleanField(default=True, verbose_name='SSL证书校验'),
        ),
    ]

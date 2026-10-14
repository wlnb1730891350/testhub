from django.db import migrations


def backfill_desktop_task_descriptions(apps, schema_editor):
    AICase = apps.get_model('ui_automation', 'AICase')
    for case in AICase.objects.filter(execution_target='desktop').exclude(task_description=''):
        if not str(case.desktop_task_description or '').strip():
            case.desktop_task_description = case.task_description
            case.save(update_fields=['desktop_task_description'])


class Migration(migrations.Migration):

    dependencies = [
        ('ui_automation', '0013_aicase_dual_mode_task_descriptions'),
    ]

    operations = [
        migrations.RunPython(backfill_desktop_task_descriptions, migrations.RunPython.noop),
    ]

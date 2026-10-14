# Generated manually to reconcile the deployed MySQL schema with the Django model.
from django.db import migrations, models


ROLE_CHOICES = [
    ('admin', '管理员'),
    ('engineer', '开发人员'),
    ('tester', '测试人员'),
]


def _role_field():
    field = models.CharField(
        choices=ROLE_CHOICES,
        default='tester',
        max_length=20,
        verbose_name='角色',
    )
    field.set_attributes_from_name('role')
    return field


def ensure_user_role_column(apps, schema_editor):
    user_model = apps.get_model('users', 'User')
    table_name = user_model._meta.db_table
    existing_columns = {
        column.name
        for column in schema_editor.connection.introspection.get_table_description(
            schema_editor.connection.cursor(), table_name
        )
    }
    role_field = _role_field()
    if 'role' in existing_columns:
        old_field = models.CharField(max_length=20)
        old_field.set_attributes_from_name('role')
        schema_editor.alter_field(user_model, old_field, role_field, strict=False)
    else:
        schema_editor.add_field(user_model, role_field)


def remove_user_role_column(apps, schema_editor):
    user_model = apps.get_model('users', 'User')
    table_name = user_model._meta.db_table
    existing_columns = {
        column.name
        for column in schema_editor.connection.introspection.get_table_description(
            schema_editor.connection.cursor(), table_name
        )
    }
    if 'role' in existing_columns:
        schema_editor.remove_field(user_model, _role_field())


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(ensure_user_role_column, remove_user_role_column)],
            state_operations=[
                migrations.AddField(
                    model_name='user',
                    name='role',
                    field=models.CharField(
                        choices=ROLE_CHOICES,
                        default='tester',
                        max_length=20,
                        verbose_name='角色',
                    ),
                ),
            ],
        ),
    ]

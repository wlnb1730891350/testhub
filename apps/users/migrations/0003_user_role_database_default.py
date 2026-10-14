from django.db import migrations


def set_role_default(apps, schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        return
    table_name = schema_editor.quote_name(apps.get_model('users', 'User')._meta.db_table)
    column_name = schema_editor.quote_name('role')
    schema_editor.execute(
        f"ALTER TABLE {table_name} MODIFY COLUMN {column_name} varchar(20) NOT NULL DEFAULT 'tester'"
    )


def remove_role_default(apps, schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        return
    table_name = schema_editor.quote_name(apps.get_model('users', 'User')._meta.db_table)
    column_name = schema_editor.quote_name('role')
    schema_editor.execute(
        f"ALTER TABLE {table_name} MODIFY COLUMN {column_name} varchar(20) NOT NULL"
    )


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ('users', '0002_user_role_schema_sync'),
    ]

    operations = [
        migrations.RunPython(set_role_default, remove_role_default),
    ]

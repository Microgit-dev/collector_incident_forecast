from django.db import migrations

SQL = """
SELECT create_hypertable('telemetry_channeldaily', 'day',
    chunk_time_interval => INTERVAL '1 year', if_not_exists => TRUE, migrate_data => TRUE);
"""


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(SQL)


class Migration(migrations.Migration):
    dependencies = [("telemetry", "0003_channeldaily")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]

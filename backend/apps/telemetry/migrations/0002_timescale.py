"""
Превращает telemetry_reading в hypertable TimescaleDB и строит аналитическую витрину.

ТЗ §13 разделяет хранение на оперативный контур, архив и аналитические витрины:
- оперативный контур — несжатые свежие чанки hypertable;
- архив — сжатые чанки старше 30 дней (плюс Parquet для обучения моделей вне БД);
- витрина — continuous aggregate telemetry_reading_hourly.

На SQLite (локальные юнит-тесты) миграция ничего не делает.
"""

from django.db import migrations

HYPERTABLE = """
CREATE EXTENSION IF NOT EXISTS timescaledb;
SELECT create_hypertable('telemetry_reading', 'ts',
    chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE, migrate_data => TRUE);
ALTER TABLE telemetry_reading SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'channel_id',
    timescaledb.compress_orderby = 'ts DESC'
);
SELECT add_compression_policy('telemetry_reading', INTERVAL '30 days', if_not_exists => TRUE);
"""

HOURLY = """
CREATE MATERIALIZED VIEW IF NOT EXISTS telemetry_reading_hourly
WITH (timescaledb.continuous) AS
SELECT
    channel_id,
    time_bucket(INTERVAL '1 hour', ts) AS bucket,
    count(*)                                        AS readings,
    count(*) FILTER (WHERE state = 'alarm')         AS alarms,
    count(*) FILTER (WHERE state = 'fault')         AS faults,
    count(*) FILTER (WHERE state = 'power_loss')    AS power_losses,
    count(*) FILTER (WHERE state = 'unknown')       AS unknowns,
    avg(numeric)                                    AS numeric_avg,
    min(numeric)                                    AS numeric_min,
    max(numeric)                                    AS numeric_max
FROM telemetry_reading
GROUP BY channel_id, bucket
WITH NO DATA;
SELECT add_continuous_aggregate_policy('telemetry_reading_hourly',
    start_offset => INTERVAL '3 days', end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '30 minutes', if_not_exists => TRUE);
"""


def _is_postgres(schema_editor) -> bool:
    return schema_editor.connection.vendor == "postgresql"


def forwards(apps, schema_editor):
    if not _is_postgres(schema_editor):
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(HYPERTABLE)


def create_hourly(apps, schema_editor):
    if not _is_postgres(schema_editor):
        return
    # continuous aggregate нельзя создавать внутри транзакции — поэтому миграция atomic=False
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(HOURLY)


def drop_hourly(apps, schema_editor):
    if _is_postgres(schema_editor):
        with schema_editor.connection.cursor() as cursor:
            cursor.execute("DROP MATERIALIZED VIEW IF EXISTS telemetry_reading_hourly")


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("telemetry", "0001_initial")]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
        migrations.RunPython(create_hourly, drop_hourly),
    ]

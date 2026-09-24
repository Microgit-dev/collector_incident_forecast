from celery import shared_task
from django.db import connection

# Суточная витрина из оперативного контура: архив заполняет прошлое, эта задача — свежие сутки
ROLLUP_SQL = """
INSERT INTO telemetry_channeldaily (
    day, channel_id, readings, normal, warnings, alarms, faults, power_losses, unknowns, events,
    invalid, numeric_avg, numeric_min, numeric_max, first_ts, last_ts
)
SELECT
    (ts AT TIME ZONE 'Europe/Moscow')::date AS day,
    channel_id,
    count(*),
    count(*) FILTER (WHERE state = 'normal'),
    count(*) FILTER (WHERE state = 'warning'),
    count(*) FILTER (WHERE state = 'alarm'),
    count(*) FILTER (WHERE state = 'fault'),
    count(*) FILTER (WHERE state = 'power_loss'),
    count(*) FILTER (WHERE state = 'unknown'),
    count(*) FILTER (WHERE state = 'event'),
    count(*) FILTER (WHERE quality NOT IN ('ok', 'drift')),
    avg(numeric) FILTER (WHERE quality IN ('ok', 'drift')),
    min(numeric) FILTER (WHERE quality IN ('ok', 'drift')),
    max(numeric) FILTER (WHERE quality IN ('ok', 'drift')),
    min(ts),
    max(ts)
FROM telemetry_reading
WHERE ts >= date_trunc('day', now() AT TIME ZONE 'Europe/Moscow') AT TIME ZONE 'Europe/Moscow'
      - make_interval(days => %(days)s)
GROUP BY 1, 2
ON CONFLICT (day, channel_id) DO UPDATE SET
    readings = EXCLUDED.readings, normal = EXCLUDED.normal, warnings = EXCLUDED.warnings,
    alarms = EXCLUDED.alarms, faults = EXCLUDED.faults, power_losses = EXCLUDED.power_losses,
    unknowns = EXCLUDED.unknowns, events = EXCLUDED.events, invalid = EXCLUDED.invalid,
    numeric_avg = EXCLUDED.numeric_avg, numeric_min = EXCLUDED.numeric_min,
    numeric_max = EXCLUDED.numeric_max, first_ts = EXCLUDED.first_ts, last_ts = EXCLUDED.last_ts
"""


@shared_task
def rollup_daily(days: int = 1) -> int:
    """Пересчитать суточные сводки за сегодня и N предыдущих суток (celery beat, ежечасно)."""
    if connection.vendor != "postgresql":
        return 0
    with connection.cursor() as cursor:
        cursor.execute(ROLLUP_SQL, {"days": days})
        return cursor.rowcount

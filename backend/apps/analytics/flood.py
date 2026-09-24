"""
Нагрузка на диспетчера: сколько сигналов пришло бы «как есть» и во сколько эпизодов
они складываются. Считается по оперативному контуру (сырые переходы состояний) — это
и главный демонстрационный показатель: «N тревог → M карточек».
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.core.cache import cache
from django.db import connection

FLOOD_SQL = """
WITH r AS (
  SELECT ts, channel_id, state, lag(state) OVER (PARTITION BY channel_id ORDER BY ts) AS prev
  FROM telemetry_reading
  WHERE facet = 'primary' AND ts > %(start)s - interval '1 day' AND ts <= %(end)s
), t AS (
  SELECT r.ts, c.node_id,
         CASE WHEN r.state = 'alarm' THEN 'physical' ELSE 'technical' END AS contour
  FROM r JOIN assets_channel c ON c.id = r.channel_id
  WHERE r.ts > %(start)s AND r.state IS DISTINCT FROM r.prev
    AND r.state IN ('fault', 'power_loss', 'unknown', 'alarm')
), g AS (
  SELECT *, CASE WHEN ts - lag(ts) OVER (PARTITION BY node_id, contour ORDER BY ts) <= interval '30 min'
                 THEN 0 ELSE 1 END AS new_episode
  FROM t
), e AS (
  SELECT *, sum(new_episode) OVER (PARTITION BY node_id, contour ORDER BY ts) AS episode FROM g
)
SELECT contour, count(*) AS signals, count(DISTINCT (node_id, episode)) AS episodes,
       max(cnt) AS largest
FROM (SELECT *, count(*) OVER (PARTITION BY node_id, contour, episode) AS cnt FROM e) x
GROUP BY contour
"""


def flood_reduction(end: datetime, days: int = 30) -> dict:
    """Переходы в тревожные и технические состояния → эпизоды по правилам склейки. Кешируется на час."""
    key = f"analytics:flood:{end:%Y%m%d%H}:{days}"
    if (cached := cache.get(key)) is not None:
        return cached
    start = end - timedelta(days=days)
    with connection.cursor() as cursor:
        cursor.execute(FLOOD_SQL, {"start": start, "end": end})
        rows = cursor.fetchall()
    by_contour = {
        contour: {"signals": signals, "episodes": episodes, "largest_episode": largest}
        for contour, signals, episodes, largest in rows
    }
    signals = sum(v["signals"] for v in by_contour.values())
    episodes = sum(v["episodes"] for v in by_contour.values())
    result = {
        "period": {"from": start.isoformat(), "to": end.isoformat(), "days": days},
        "signals": signals,
        "episodes": episodes,
        "factor": round(signals / episodes, 1) if episodes else None,
        "per_day": {"signals": round(signals / days), "episodes": round(episodes / days, 1)},
        "by_contour": by_contour,
    }
    cache.set(key, result, 3600)
    return result

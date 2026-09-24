"""
Сценарии пожара и НСД: сбор окна данных из оперативного контура, индекс риска по правилам
(domain/scenarios.py), запись в журнал прогнозов и снимки риска объектов.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta

from django.db import connection
from django.db.models import Sum

from .channel_model import MSK
from .domain.scenarios import (
    FIRE_TYPES,
    INTRUSION_CONTACT,
    INTRUSION_MOTION,
    TEMP_TYPES,
    ChannelWindow,
    ScenarioContext,
    fire_risk,
    intrusion_risk,
    level,
)
from .models import ChannelHealth, ForecastTask, Prediction, RiskSnapshot

logger = logging.getLogger(__name__)

WINDOW = timedelta(minutes=60)
HORIZON_HOURS = 24
MIN_SCORE = 0.15
LEVEL_RANK = ["low", "medium", "high", "critical"]
TASK_TYPES = {
    ForecastTask.FIRE: FIRE_TYPES | TEMP_TYPES,
    ForecastTask.INTRUSION: INTRUSION_CONTACT | INTRUSION_MOTION,
}
TITLES = {ForecastTask.FIRE: "Риск пожара", ForecastTask.INTRUSION: "Риск несанкционированного доступа"}

WINDOW_SQL = """
SELECT c.id, c.node_id, st.name, c.name, c.picket,
       count(*) FILTER (WHERE r.state = 'alarm' AND r.ts > %(start)s) AS alarms,
       avg(r.numeric) FILTER (WHERE r.quality IN ('ok', 'drift') AND r.ts > %(now_from)s) AS numeric_now,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY r.numeric)
           FILTER (WHERE r.quality IN ('ok', 'drift')) AS numeric_base
FROM telemetry_reading r
JOIN assets_channel c ON c.id = r.channel_id
JOIN assets_sensortype st ON st.id = c.sensor_type_id
WHERE r.ts > %(base_from)s AND r.ts <= %(end)s AND r.facet = 'primary' AND st.name = ANY(%(types)s)
GROUP BY 1, 2, 3, 4, 5
HAVING count(*) FILTER (WHERE r.state = 'alarm' AND r.ts > %(start)s) > 0
    OR (st.name = ANY(%(temp)s) AND avg(r.numeric) FILTER (WHERE r.quality IN ('ok', 'drift') AND r.ts > %(now_from)s)
        - percentile_cont(0.5) WITHIN GROUP (ORDER BY r.numeric) FILTER (WHERE r.quality IN ('ok', 'drift')) >= 3)
"""

GUARD_SQL = """
SELECT DISTINCT ON (c.node_id) c.node_id, r.raw_value, r.ts
FROM telemetry_reading r
JOIN assets_channel c ON c.id = r.channel_id
JOIN assets_sensortype st ON st.id = c.sensor_type_id
WHERE st.name = 'Состояние охраны' AND r.raw_value IN ('На охране', 'Снято с охраны')
  AND r.ts > %(since)s AND r.ts <= %(end)s AND c.node_id = ANY(%(nodes)s)
ORDER BY c.node_id, r.ts DESC
"""


def _windows(as_of: datetime) -> dict[int, list[ChannelWindow]]:
    params = {
        "start": as_of - WINDOW,
        "now_from": as_of - timedelta(minutes=30),
        "base_from": as_of - timedelta(hours=24),
        "end": as_of,
        "types": sorted(TASK_TYPES[ForecastTask.FIRE] | TASK_TYPES[ForecastTask.INTRUSION]),
        "temp": sorted(TEMP_TYPES),
    }
    with connection.cursor() as cursor:
        cursor.execute(WINDOW_SQL, params)
        rows = cursor.fetchall()
    ids = [r[0] for r in rows]
    health = dict(ChannelHealth.objects.filter(channel_id__in=ids).values_list("channel_id", "score"))
    history = _fault_history(ids, as_of)
    by_node: dict[int, list[ChannelWindow]] = defaultdict(list)
    for cid, node_id, stype, name, picket, alarms, now, base in rows:
        by_node[node_id].append(
            ChannelWindow(
                channel_id=cid,
                sensor_type=stype,
                name=name,
                picket=float(picket) if picket is not None else None,
                alarms=alarms,
                numeric_now=now,
                numeric_base=base,
                health=health.get(cid),
                fault_history=history.get(cid, 0),
            )
        )
    return by_node


def _fault_history(ids: list[int], as_of: datetime) -> dict[int, int]:
    from apps.telemetry.models import ChannelDaily

    day = as_of.astimezone(MSK).date()
    return dict(
        ChannelDaily.objects.filter(channel_id__in=ids, day__gte=day - timedelta(days=90), day__lt=day)
        .values("channel_id")
        .annotate(n=Sum("faults"))
        .values_list("channel_id", "n")
    )


def _guard(nodes: list[int], as_of: datetime) -> dict[int, tuple[bool, bool]]:
    if not nodes:
        return {}
    with connection.cursor() as cursor:
        cursor.execute(GUARD_SQL, {"since": as_of - timedelta(days=7), "end": as_of, "nodes": nodes})
        rows = cursor.fetchall()
    return {node: (raw == "На охране", as_of - ts <= WINDOW) for node, raw, ts in rows}


def _works(nodes: list[int]) -> dict[int, int]:
    from apps.topology.models import Node
    from apps.workorders.models import WorkOrder

    paths = dict(Node.objects.filter(pk__in=nodes).values_list("pk", "path"))
    active = list(
        WorkOrder.objects.filter(status=WorkOrder.Status.IN_PROGRESS).values_list("node__path", flat=True)
    )
    return {node: sum(p.startswith(path) for p in active) for node, path in paths.items()}


def assess(as_of: datetime) -> list[tuple[str, int, object]]:
    """Все объекты с признаками угрозы: (задача, объект, оценка)."""
    by_node = _windows(as_of)
    nodes = list(by_node)
    guard, works = _guard(nodes, as_of), _works(nodes)
    local = as_of.astimezone(MSK)
    results = []
    for node_id, channels in by_node.items():
        armed, changed = guard.get(node_id, (None, False))
        ctx = ScenarioContext(
            local_time=local,
            works_in_progress=works.get(node_id, 0),
            guard_armed=armed,
            guard_changed_recently=changed,
        )
        for task, fn in ((ForecastTask.FIRE, fire_risk), (ForecastTask.INTRUSION, intrusion_risk)):
            assessment = fn(channels, ctx)
            if assessment.score >= MIN_SCORE:
                results.append((task, node_id, assessment))
    return results


def run_scenarios(as_of: datetime, backtest: bool = False) -> dict:
    from apps.assets.models import Channel
    from apps.incidents.models import Alert, Incident
    from apps.incidents.services import raise_alert
    from apps.topology.models import Node

    assessments = assess(as_of)
    nodes = Node.objects.in_bulk([n for _, n, _ in assessments])
    counts: dict[str, dict] = {task: {"nodes": 0, "predictions": 0, "alerts": 0} for task in TASK_TYPES}
    snapshots = []
    for task, node_id, a in assessments:
        lvl = level(a.score)
        counts[task]["nodes"] += 1
        snapshots.append(
            RiskSnapshot(
                node_id=node_id,
                task=task,
                as_of=as_of,
                max_probability=a.score,
                expected_failures=a.score,
                channels_total=len(a.factors),
                channels_at_risk=1,
                risk_level=lvl,
            )
        )
        if LEVEL_RANK.index(lvl) < 1:
            continue
        node = nodes[node_id]
        summary = f"{TITLES[task]} на объекте «{node.name}»: индекс {a.score:.2f}. " + "; ".join(
            f["title"] for f in a.factors
        )
        current = Prediction.objects.filter(
            task=task, node_id=node_id, outcome=Prediction.Outcome.PENDING, valid_until__gt=as_of
        ).first()
        if current and LEVEL_RANK.index(lvl) <= LEVEL_RANK.index(current.risk_level):
            continue
        if current:
            current.probability, current.risk_level, current.factors, current.summary = (
                a.score,
                lvl,
                a.factors,
                summary,
            )
            current.save(update_fields=["probability", "risk_level", "factors", "summary"])
            prediction = current
        else:
            prediction = Prediction.objects.create(
                task=task,
                node_id=node_id,
                channel_id=a.channel_id,
                issued_at=as_of,
                horizon_hours=HORIZON_HOURS,
                valid_until=as_of + timedelta(hours=HORIZON_HOURS),
                probability=a.score,
                risk_level=lvl,
                factors=a.factors,
                summary=summary,
                is_backtest=backtest,
            )
            counts[task]["predictions"] += 1
        # Если по объекту уже открыта карточка-факт той же угрозы, её гипотезы и так видны диспетчеру
        fact_open = Incident.objects.filter(
            node_id=node_id, type=task, is_forecast=False, status__in=Incident.OPEN_STATUSES
        ).exists()
        if not backtest and lvl in ("high", "critical") and not fact_open:
            raise_alert(
                type=task,
                severity=lvl,
                node=node,
                channel=Channel.objects.filter(pk=a.channel_id).first(),
                prediction=prediction,
                title=f"{TITLES[task]}: {node.name}",
                source=Alert.Source.FORECAST,
                raised_at=as_of,
                probability=a.score,
                horizon_hours=HORIZON_HOURS,
                details={"factors": a.factors},
            )
            counts[task]["alerts"] += 1
    RiskSnapshot.objects.bulk_create(
        snapshots,
        update_conflicts=True,
        unique_fields=["node", "task", "as_of"],
        update_fields=[
            "max_probability",
            "expected_failures",
            "channels_total",
            "channels_at_risk",
            "risk_level",
        ],
    )
    return counts


RESOLVE_SQL = """
UPDATE forecasting_prediction p SET outcome = CASE WHEN EXISTS (
        SELECT 1 FROM telemetry_reading r
        JOIN assets_channel c ON c.id = r.channel_id
        JOIN assets_sensortype st ON st.id = c.sensor_type_id
        WHERE c.node_id = p.node_id AND r.state = 'alarm' AND st.name = ANY(%(types)s)
          AND r.ts > p.issued_at + interval '1 hour' AND r.ts <= p.valid_until
    ) THEN 'confirmed' ELSE 'not_confirmed' END,
    outcome_at = %(as_of)s
WHERE p.outcome = 'pending' AND p.task = %(task)s AND p.valid_until <= %(as_of)s
"""


def resolve_scenarios(as_of: datetime) -> int:
    """
    Исход индикатора: угроза «проявилась», если после первого часа в горизонте снова были тревоги
    того же рода на объекте. Решение диспетчера по карточке (подтверждено / ложное) приоритетнее.
    """
    resolved = 0
    with connection.cursor() as cursor:
        for task, types in TASK_TYPES.items():
            cursor.execute(RESOLVE_SQL, {"as_of": as_of, "task": task, "types": sorted(types)})
            resolved += cursor.rowcount
    return resolved

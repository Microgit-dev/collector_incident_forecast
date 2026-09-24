"""
Качество прогнозов за период (ТЗ §9) по журналу — оперативному или бэктесту:
- точность: доля подтвердившихся среди прогнозов с известным исходом, доля ложных;
- полнота по факту: сколько начавшихся за период событий было заранее предупреждено
  прогнозом уровня «высокий» и выше (события — по суточной витрине, как при обучении);
- нагрузка: записей журнала в сутки; упреждение — по тесту активной модели;
- доля прогнозных карточек, по которым диспетчер указал результат, и «помог ли прогноз».
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import connection
from django.db.models import Count

from apps.forecasting import specs
from apps.forecasting.models import MLModel, Prediction
from apps.incidents.models import Decision
from apps.topology.selectors import has_global_scope, scope_queryset, user_scope_node

MSK = ZoneInfo("Europe/Moscow")
TASKS = ("sensor_failure", "gas", "flood", "fire", "intrusion")

ONSETS_SQL = """
WITH d AS (
    SELECT d.channel_id, d.day, ({event}) AS ev,
           lag({healthy}) OVER (PARTITION BY d.channel_id ORDER BY d.day) AS prev_ok,
           lag(d.day) OVER (PARTITION BY d.channel_id ORDER BY d.day) AS prev_day
    FROM telemetry_channeldaily d
    JOIN assets_channel c ON c.id = d.channel_id
    JOIN topology_node n ON n.id = c.node_id
    LEFT JOIN assets_sensortype st ON st.id = c.sensor_type_id
    WHERE d.day >= %(since)s - 1 AND d.day <= %(until)s AND n.path LIKE %(scope)s {types}
)
SELECT count(*) AS onsets,
       count(*) FILTER (WHERE EXISTS (
           SELECT 1 FROM forecasting_prediction p
           WHERE p.channel_id = d.channel_id AND p.task = %(task)s AND p.is_backtest = %(backtest)s
             AND p.risk_level IN ('high', 'critical')
             AND p.issued_at < (d.day + 1)::timestamp AT TIME ZONE 'Europe/Moscow'
             AND p.valid_until > d.day::timestamp AT TIME ZONE 'Europe/Moscow'
       )) AS warned
FROM d
WHERE d.day >= %(since)s AND d.ev AND d.prev_ok AND d.prev_day = d.day - 1
"""


def _onsets(user, task: str, since, until, backtest: bool) -> dict | None:
    """Начала событий за период и сколько из них было предупреждено. Только для задач-моделей."""
    if task not in specs.SPECS or connection.vendor != "postgresql":
        return None
    spec = specs.SPECS[task]
    node = None if has_global_scope(user) else user_scope_node(user)
    if node is None and not has_global_scope(user):
        return {"onsets": 0, "warned": 0, "recall": None}
    types = ""
    params = {
        "since": since,
        "until": until,
        "task": task,
        "backtest": backtest,
        "scope": f"{node.path if node else ''}%",
    }
    if spec.sensor_types:
        types = "AND st.name = ANY(%(types)s)"
        params["types"] = list(spec.sensor_types)
    sql = ONSETS_SQL.format(event=spec.event_sql, healthy=spec.healthy_sql, types=types)
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        onsets, warned = cursor.fetchone()
    return {"onsets": onsets, "warned": warned, "recall": round(warned / onsets, 3) if onsets else None}


def quality(user, since: datetime, until: datetime, backtest: bool = False) -> dict:
    journal = scope_queryset(
        Prediction.objects.filter(issued_at__gte=since, issued_at__lt=until, is_backtest=backtest),
        user,
        "node",
    )
    days = max((until - since).total_seconds() / 86400, 1)
    d_since, d_until = since.astimezone(MSK).date(), (until - timedelta(seconds=1)).astimezone(MSK).date()
    tasks = {}
    for task in TASKS:
        qs = journal.filter(task=task)
        by_outcome = dict(qs.order_by().values_list("outcome").annotate(n=Count("pk")))
        by_level = {}
        for level, outcome, n in qs.order_by().values_list("risk_level", "outcome").annotate(n=Count("pk")):
            by_level.setdefault(level, Counter())[outcome] += n
        total = sum(by_outcome.values())
        confirmed = by_outcome.get("confirmed", 0)
        not_confirmed = by_outcome.get("not_confirmed", 0)
        resolved = confirmed + not_confirmed
        model = MLModel.objects.filter(task=task, status=MLModel.Status.ACTIVE).first()
        test = (model.metrics or {}).get("levels_test", {}).get("high", {}) if model else {}
        tasks[task] = {
            "total": total,
            "per_day": round(total / days, 1),
            "by_outcome": by_outcome,
            "precision": round(confirmed / resolved, 3) if resolved else None,
            "false_share": round(not_confirmed / resolved, 3) if resolved else None,
            "prevented": by_outcome.get("prevented", 0),
            "by_level": {
                lvl: {
                    "total": sum(c.values()),
                    "precision": round(c["confirmed"] / (c["confirmed"] + c["not_confirmed"]), 3)
                    if c["confirmed"] + c["not_confirmed"]
                    else None,
                }
                for lvl, c in by_level.items()
            },
            "recall": _onsets(user, task, d_since, d_until, backtest) if total else None,
            "model": {
                "version": model.version,
                "test_precision_high": test.get("precision"),
                "test_recall_high": test.get("recall"),
                "lead_time_median_h": (test.get("lead_time_hours") or {}).get("median"),
            }
            if model
            else None,
        }
    forecast_cards = scope_queryset(
        Decision.objects.filter(
            incident__is_forecast=True, incident__opened_at__gte=since, incident__opened_at__lt=until
        ),
        user,
        "incident__node",
    )
    useful = Counter(
        "yes" if v else "no" if v is False else "unknown"
        for v in forecast_cards.values_list("forecast_useful", flat=True)
    )
    return {
        "period": {"from": since, "to": until},
        "backtest": backtest,
        "tasks": tasks,
        "forecast_cards": {"decided": sum(useful.values()), "useful": dict(useful)},
    }

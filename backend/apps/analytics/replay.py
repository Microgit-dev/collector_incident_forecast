"""
Разбор исторического эпизода (сценарный анализ, ТЗ §6): как система отработала бы интервал
на объекте. Использует те же функции, что и работающая система: нормализованные состояния,
склейку сигналов в эпизоды, гипотезы, чек-листы, прогнозные модели на начало интервала.

Источник показаний — оперативный контур (hypertable), а для дат старше него — Parquet-архив.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import polars as pl
from django.conf import settings
from django.db import connection

from apps.assets.models import Channel
from apps.incidents.domain.actions import next_actions
from apps.incidents.domain.correlation import TECHNICAL, Context, Signal, contour, hypotheses, technical_type
from apps.incidents.rules import _ALARM_SEVERITY, _DOMAIN_TO_TYPE
from apps.topology.models import Node

MSK = ZoneInfo("Europe/Moscow")
MAX_SPAN = timedelta(hours=24)
GAP = timedelta(minutes=30)
ABNORMAL = ("alarm", "fault", "power_loss", "unknown")
STATE_TYPE = {"fault": "sensor_failure", "power_loss": "power", "unknown": "communication"}
STATE_SEVERITY = {"fault": "medium", "power_loss": "medium", "unknown": "low"}

READINGS_SQL = """
SELECT ts, channel_id, state, raw_value, numeric
FROM telemetry_reading
WHERE channel_id = ANY(%(ids)s) AND facet = 'primary' AND ts > %(start)s AND ts <= %(end)s
ORDER BY ts
"""


class ReplayError(Exception):
    pass


def _operational_start():
    with connection.cursor() as cursor:
        cursor.execute("SELECT min(ts) FROM telemetry_reading")
        return cursor.fetchone()[0]


def _readings(ids: list[int], start: datetime, end: datetime) -> tuple[pl.DataFrame, str]:
    """Показания с суточным запасом до начала — чтобы знать предыдущее состояние канала."""
    lead_in = start - timedelta(days=1)
    oldest = _operational_start()
    if oldest and lead_in >= oldest:
        with connection.cursor() as cursor:
            cursor.execute(READINGS_SQL, {"ids": ids, "start": lead_in, "end": end})
            rows = cursor.fetchall()
        frame = pl.DataFrame(
            rows,
            schema={
                "ts": pl.Datetime("us", "UTC"),
                "channel_id": pl.Int64,
                "state": pl.String,
                "raw_value": pl.String,
                "numeric": pl.Float64,
            },
            orient="row",
        )
        return frame, "оперативный контур"
    path = settings.ARTIFACTS_DIR / "archive" / f"journal_{start.astimezone(MSK).year}.parquet"
    if not path.exists():
        raise ReplayError(f"Нет архива за {start.year} год — загрузите журналы этого года")
    frame = (
        pl.scan_parquet(path)
        .filter(
            pl.col("channel_id").is_in(ids)
            & (pl.col("facet") == "primary")
            & (pl.col("ts") > lead_in)
            & (pl.col("ts") <= end)
        )
        .select("ts", "channel_id", "state", "raw_value", "numeric")
        .sort("ts")
        .collect()
    )
    return frame, f"архив {path.name}"


def _signal_type(state: str, domain: str) -> str:
    return _DOMAIN_TO_TYPE.get(domain, "equipment") if state == "alarm" else STATE_TYPE[state]


def replay(node: Node, start: datetime, end: datetime, with_forecast: bool = True) -> dict:
    if end <= start or end - start > MAX_SPAN:
        raise ReplayError("Интервал — от минуты до 24 часов")
    channels = {
        c.pk: c
        for c in Channel.objects.filter(node__path__startswith=node.path, is_active=True).select_related(
            "sensor_type", "node"
        )
    }
    if not channels:
        raise ReplayError("На объекте нет каналов")
    frame, source = _readings(list(channels), start, end)
    transitions = (
        frame.with_columns(pl.col("state").shift(1).over("channel_id").alias("prev"))
        .filter(
            (pl.col("ts") > start) & (pl.col("state") != pl.col("prev")) & pl.col("state").is_in(ABNORMAL)
        )
        .sort("ts")
    )

    # ---- сигналы и эпизоды (та же склейка, что в работающей системе) ----
    signals = []
    for row in transitions.iter_rows(named=True):
        ch = channels[row["channel_id"]]
        domain = ch.sensor_type.domain if ch.sensor_type else "process"
        kind = _signal_type(row["state"], domain)
        severity = (
            _ALARM_SEVERITY.get(kind, "medium") if row["state"] == "alarm" else STATE_SEVERITY[row["state"]]
        )
        signals.append(
            {
                "ts": row["ts"],
                "channel_id": ch.pk,
                "channel": ch.name,
                "node_id": ch.node_id,
                "node": ch.node.name,
                "sensor_type": ch.sensor_type.name if ch.sensor_type else "",
                "state": row["state"],
                "raw_value": row["raw_value"],
                "numeric": row["numeric"],
                "type": kind,
                "contour": contour(kind),
                "severity": severity,
                "picket": float(ch.picket) if ch.picket is not None else None,
            }
        )
    episodes = _episodes(signals, channels)

    # ---- лента: сигналы по интервалам ----
    minutes = max(1, int((end - start).total_seconds() // 60))
    bucket = 1 if minutes <= 120 else 5 if minutes <= 720 else 15
    timeline: dict[datetime, Counter] = defaultdict(Counter)
    for s in signals:
        ts = s["ts"].astimezone(MSK)
        key = ts.replace(minute=ts.minute - ts.minute % bucket, second=0, microsecond=0)
        timeline[key][s["contour"]] += 1
    series = [
        {"t": k.isoformat(), "physical": v["physical"], "technical": v["technical"]}
        for k, v in sorted(timeline.items())
    ]

    result = {
        "node": {"id": node.pk, "name": node.name},
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "source": source,
        "channels": len(channels),
        "readings": frame.filter(pl.col("ts") > start).height,
        "signals_total": len(signals),
        "signals": [s | {"ts": s["ts"].isoformat()} for s in signals[:500]],
        "bucket_minutes": bucket,
        "series": series,
        "episodes": episodes,
        "reduction": round(len(signals) / len(episodes), 1) if episodes else None,
        "decisions": _decisions(node, start, end),
    }
    if with_forecast:
        result["forecast"] = _forecast_before(node, start, {s["channel_id"]: s for s in signals})
    return result


def _episodes(signals: list[dict], channels: dict) -> list[dict]:
    per_node_count = Counter(c.node_id for c in channels.values())
    open_: dict[tuple, dict] = {}
    done: list[dict] = []
    for s in signals:
        key = (s["node_id"], s["type"] if s["contour"] != TECHNICAL else TECHNICAL)
        ep = open_.get(key)
        if ep and s["ts"] - ep["last"] > GAP:
            done.append(ep)
            ep = None
        if ep is None:
            ep = {"key": key, "node": s["node"], "node_id": s["node_id"], "items": [], "last": s["ts"]}
            open_[key] = ep
        ep["items"].append(s)
        ep["last"] = s["ts"]
    done.extend(open_.values())
    out = []
    for ep in sorted(done, key=lambda e: e["items"][0]["ts"]):
        items = ep["items"]
        sigs = [
            Signal(
                channel_id=i["channel_id"],
                state=i["state"],
                ts=i["ts"],
                sensor_type=i["sensor_type"],
                name=i["channel"],
                picket=i["picket"],
                numeric=i["numeric"],
            )
            for i in items
        ]
        first_type = items[0]["type"]
        kind = technical_type(sigs) if ep["key"][1] == TECHNICAL else first_type
        n_channels = len({i["channel_id"] for i in items})
        severity = max((i["severity"] for i in items), key=["low", "medium", "high", "critical"].index)
        if contour(kind) == TECHNICAL and n_channels >= 10:
            severity = "high" if severity in ("low", "medium") else severity
        ctx = Context(local_time=items[0]["ts"].astimezone(MSK), node_channels=per_node_count[ep["node_id"]])
        ranked = hypotheses(kind, sigs, ctx)
        out.append(
            {
                "node": ep["node"],
                "type": kind,
                "contour": contour(kind),
                "severity": severity,
                "signals": len(items),
                "channels": n_channels,
                "first": items[0]["ts"].isoformat(),
                "last": items[-1]["ts"].isoformat(),
                "states": dict(Counter(i["state"] for i in items)),
                "hypotheses": [h.as_dict() for h in ranked],
                "actions": [title for _, title in next_actions(kind, ranked[0].code if ranked else None)],
            }
        )
    return out


def _decisions(node: Node, start: datetime, end: datetime) -> list[dict]:
    from apps.incidents.models import Incident

    incidents = Incident.objects.filter(
        node__path__startswith=node.path, opened_at__gte=start, opened_at__lte=end
    ).prefetch_related("decisions__reason", "decisions__decided_by")
    return [
        {
            "id": i.pk,
            "title": i.title,
            "status": i.status,
            "decisions": [
                {
                    "outcome": d.get_outcome_display(),
                    "reason": d.reason.name if d.reason else "",
                    "by": d.decided_by.get_full_name() or d.decided_by.get_username(),
                    "at": d.decided_at.isoformat(),
                }
                for d in i.decisions.all()
            ],
        }
        for i in incidents
    ]


def _forecast_before(node: Node, start: datetime, happened: dict[int, dict]) -> dict:
    """Что прогнозные модели говорили на начало интервала и сбылось ли это внутри него."""
    from apps.forecasting.models import RiskPolicy
    from apps.forecasting.services import active_model, forecaster_for

    node_ids = list(Node.objects.filter(path__startswith=node.path).values_list("pk", flat=True))
    names = dict(Channel.objects.filter(node_id__in=node_ids).values_list("pk", "name"))
    event_states = {"sensor_failure": {"fault"}, "flood": {"alarm"}, "gas": {"alarm"}}
    out = {}
    for task in ("sensor_failure", "gas", "flood"):
        model = active_model(task)
        if model is None:
            continue
        policy = RiskPolicy.objects.filter(task=task).first()
        results = forecaster_for(model).predict(start, node_ids)
        top = sorted(results, key=lambda r: -r.probability)[:8]
        out[task] = {
            "model": model.version,
            "channels": len(results),
            "top": [
                {
                    "channel_id": r.channel_id,
                    "channel": names.get(r.channel_id, ""),
                    "probability": round(r.probability, 4),
                    "level": policy.level_for(r.probability) if policy else None,
                    "factors": [f.title for f in r.factors],
                    "happened": r.channel_id in happened
                    and happened[r.channel_id]["state"] in event_states[task],
                }
                for r in top
            ],
        }
    return out

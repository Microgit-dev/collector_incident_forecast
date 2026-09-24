"""
Карточка прогноза (ТЗ §10): вероятность и уровень, факторы, насколько можно доверять уровню
(качество модели на тесте и фактический итог журнала), качество данных канала, история канала,
связанные карточки инцидентов, рекомендации по ТО и следующие действия.
"""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Count

from apps.incidents.domain.actions import next_actions
from apps.incidents.models import Incident
from apps.telemetry.models import ChannelDaily, ChannelState

from .models import ChannelHealth, ChannelRisk, Prediction

HISTORY_DAYS = 30
INDICATORS = ("fire", "intrusion")


def _realized(task: str, level: str, backtest: bool) -> dict:
    counts = dict(
        Prediction.objects.filter(task=task, risk_level=level, is_backtest=backtest)
        .order_by()
        .values_list("outcome")
        .annotate(n=Count("pk"))
    )
    resolved = counts.get("confirmed", 0) + counts.get("not_confirmed", 0)
    return {
        "confirmed": counts.get("confirmed", 0),
        "resolved": resolved,
        "precision": round(counts.get("confirmed", 0) / resolved, 3) if resolved else None,
    }


def _model(prediction: Prediction) -> dict:
    if prediction.task in INDICATORS:
        return {
            "method": "rules",
            "note": "Индекс по правилам: сумма подтверждающих факторов с поправками. Не вероятность — калибровать его "
            "не на чем: подтверждённых событий в данных нет.",
        }
    model = prediction.model
    if model is None:
        return {"method": "model"}
    metrics = model.metrics or {}
    level = (metrics.get("levels_test") or {}).get(prediction.risk_level) or {}
    return {
        "method": "model",
        "version": model.version,
        "algorithm": model.algorithm,
        "status": model.status,
        "test_period": (model.train_period or {}).get("test"),
        "roc_auc": (metrics.get("test") or {}).get("roc_auc"),
        "pr_auc": (metrics.get("test") or {}).get("pr_auc"),
        "base_rate": (metrics.get("test") or {}).get("base_rate"),
        "level_test": {
            "precision": level.get("precision"),
            "recall": level.get("recall"),
            "alerts_per_day": level.get("alerts_per_day"),
            "lead_time_median_h": (level.get("lead_time_hours") or {}).get("median"),
        },
        "baseline": metrics.get("baseline_test"),
    }


def _channel(prediction: Prediction) -> dict | None:
    ch = prediction.channel
    if ch is None:
        return None
    state = ChannelState.objects.filter(channel=ch, facet="primary").first()
    health = ChannelHealth.objects.filter(channel=ch).first()
    since = prediction.issued_at.date() - timedelta(days=HISTORY_DAYS)
    daily = list(
        ChannelDaily.objects.filter(
            channel=ch, day__gt=since, day__lte=prediction.issued_at.date() + timedelta(days=2)
        )
        .order_by("day")
        .values(
            "day", "readings", "alarms", "faults", "power_losses", "unknowns", "numeric_max", "last_state"
        )
    )
    return {
        "id": ch.pk,
        "name": ch.name,
        "sensor_type": ch.sensor_type.name if ch.sensor_type else None,
        "picket": float(ch.picket) if ch.picket is not None else None,
        "location_hint": ch.location_hint,
        "state": {"state": state.state, "since": state.changed_at, "last_seen_at": state.last_seen_at}
        if state
        else None,
        "health": {
            "score": health.score,
            "components": health.components,
            "silent": health.silent,
            "silent_since": health.silent_since,
            "last_seen_at": health.last_seen_at,
            "periodic": health.periodic,
        }
        if health
        else None,
        "daily": daily,
        "risks": [
            {"task": t, "probability": round(p, 3), "risk_level": lvl, "as_of": as_of}
            for t, p, lvl, as_of in ChannelRisk.objects.filter(channel=ch).values_list(
                "task", "probability", "risk_level", "as_of"
            )
        ],
    }


def _history(prediction: Prediction) -> list[dict]:
    qs = Prediction.objects.filter(task=prediction.task, is_backtest=prediction.is_backtest).exclude(
        pk=prediction.pk
    )
    qs = qs.filter(channel=prediction.channel) if prediction.channel_id else qs.filter(node=prediction.node)
    return list(
        qs.order_by("-issued_at").values("id", "issued_at", "probability", "risk_level", "outcome")[:10]
    )


def _incidents(prediction: Prediction) -> list[dict]:
    incidents = Incident.objects.filter(alerts__prediction=prediction).distinct()
    if prediction.channel_id:
        # карточки-факты по тому же каналу в горизонте прогноза: чем закончилось
        incidents = (
            incidents
            | Incident.objects.filter(
                alerts__channel=prediction.channel,
                opened_at__gte=prediction.issued_at,
                opened_at__lte=prediction.valid_until,
            ).distinct()
        )
    return [
        {
            "id": i.pk,
            "title": i.title,
            "type": i.type,
            "severity": i.severity,
            "status": i.status,
            "is_forecast": i.is_forecast,
            "opened_at": i.opened_at,
            "hypothesis": i.hypotheses[0]["title"] if i.hypotheses else None,
            "decision": _last_decision(i),
        }
        for i in incidents.order_by("opened_at")[:10]
    ]


def _last_decision(incident: Incident) -> str | None:
    d = incident.decisions.select_related("reason").order_by("-decided_at").first()
    if d is None:
        return None
    return f"{d.get_outcome_display()}{': ' + d.reason.name if d.reason else ''}"


def _recommendations(prediction: Prediction) -> list[dict]:
    from apps.workorders.models import MaintenanceRecommendation, WorkOrder

    recs = MaintenanceRecommendation.objects.filter(prediction=prediction)
    if prediction.channel_id:
        recs = recs | MaintenanceRecommendation.objects.filter(
            channel=prediction.channel, status=MaintenanceRecommendation.Status.NEW
        )
    orders = {
        o.recommendation_id: o
        for o in WorkOrder.objects.filter(recommendation__in=recs).only(
            "id", "number", "status", "recommendation"
        )
    }
    return [
        {
            "id": r.pk,
            "work_type": r.get_work_type_display(),
            "priority": r.priority,
            "due_date": r.due_date,
            "status": r.status,
            "rationale": r.rationale,
            "work_order": {
                "id": orders[r.pk].pk,
                "number": orders[r.pk].number,
                "status": orders[r.pk].status,
            }
            if r.pk in orders
            else None,
        }
        for r in recs.distinct().order_by("-created_at")[:5]
    ]


def prediction_card(prediction: Prediction) -> dict:
    return {
        "model_info": _model(prediction),
        "realized": {
            "live": _realized(prediction.task, prediction.risk_level, backtest=False),
            "backtest": _realized(prediction.task, prediction.risk_level, backtest=True),
        },
        "channel_info": _channel(prediction),
        "history": _history(prediction),
        "incidents": _incidents(prediction),
        "recommendations": _recommendations(prediction),
        "actions": [
            {"code": code, "title": title}
            for code, title in next_actions(
                prediction.task, None, is_forecast=prediction.task not in INDICATORS
            )
        ],
    }

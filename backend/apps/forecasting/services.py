"""
Цикл прогноза: качество данных → молчание каналов → риск отказа → журнал прогнозов → алерты.

Прогноз строится на «время данных» (data_clock): в эксплуатации это текущий момент, на стенде
без живого потока — момент последних загруженных показаний. Так прогнозы и исходы остаются
согласованными с данными, а не с часами сервера.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timedelta

from django.db import connection, transaction
from django.utils import timezone

from apps.assets.models import Channel
from apps.topology.models import Node

from . import data, health
from .models import (
    ChannelHealth,
    ChannelRisk,
    ForecastTask,
    MLModel,
    Prediction,
    RiskLevel,
    RiskPolicy,
    RiskSnapshot,
)

logger = logging.getLogger(__name__)

LEVEL_ORDER = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
STREAM_STALE = timedelta(minutes=10)  # живой поток молчит дольше — системный алерт
LIVE_WINDOW = timedelta(hours=6)  # поток считается «живым», если данные были не раньше этого срока
# В журнал прогнозов попадают риски от высокого уровня; средний — список наблюдения (ChannelRisk)
JOURNAL_FROM = RiskLevel.HIGH


def _rank(level: str) -> int:
    return LEVEL_ORDER.index(level)


# ---------- модели ----------


def active_model(task: str = ForecastTask.SENSOR_FAILURE) -> MLModel | None:
    return MLModel.objects.filter(task=task, status=MLModel.Status.ACTIVE).first()


@transaction.atomic
def activate(model: MLModel) -> MLModel:
    """Делает версию активной; пороги уровней риска берутся из подбора на валидации."""
    MLModel.objects.filter(task=model.task, status=MLModel.Status.ACTIVE).exclude(pk=model.pk).update(
        status=MLModel.Status.ARCHIVED
    )
    model.status = MLModel.Status.ACTIVE
    model.save(update_fields=["status", "updated_at"])
    levels = model.metrics.get("levels")
    if levels:
        policy, _ = RiskPolicy.objects.get_or_create(task=model.task)
        policy.medium_threshold = levels["medium"]
        policy.high_threshold = levels["high"]
        policy.critical_threshold = levels["critical"]
        policy.save()
    return model


def forecaster_for(model: MLModel):
    from .sensor_failure import SensorFailureForecaster

    policy = RiskPolicy.objects.filter(task=model.task).first()
    return SensorFailureForecaster(model.artifact_path, policy.medium_threshold if policy else 0.3)


# ---------- цикл ----------


def run_cycle(as_of: datetime | None = None, node_ids: list[int] | None = None) -> dict:
    as_of = as_of or data.data_clock()
    if as_of is None:
        return {"status": "no data"}
    summary: dict = {"as_of": as_of.isoformat()}
    started = time.monotonic()
    if node_ids is None:
        summary["stream"] = check_stream(as_of)
        summary["health"] = update_health(as_of)
        summary["resolved"] = resolve_outcomes(as_of)
    model = active_model()
    if model is None:
        summary["forecast"] = "нет активной модели — обучите модель в разделе «Модели»"
        return summary
    results = forecaster_for(model).predict(as_of, node_ids)
    summary["forecast"] = store_forecast(model, as_of, results, full=node_ids is None)
    summary["seconds"] = round(time.monotonic() - started, 1)
    logger.info("forecast cycle %s", summary)
    return summary


def store_forecast(
    model: MLModel, as_of: datetime, results: list, full: bool = True, backtest: bool = False
) -> dict:
    policy = RiskPolicy.objects.get_or_create(task=model.task)[0]
    risks = [
        ChannelRisk(
            channel_id=r.channel_id,
            task=model.task,
            as_of=as_of,
            probability=round(r.probability, 5),
            risk_level=policy.level_for(r.probability),
            factors=[asdict(f) for f in r.factors],
            model=model,
        )
        for r in results
    ]
    ChannelRisk.objects.bulk_create(
        risks,
        batch_size=2000,
        update_conflicts=True,
        unique_fields=["channel", "task"],
        update_fields=["as_of", "probability", "risk_level", "factors", "model"],
    )
    if full:
        # Канал, выпавший из прогноза (уже неисправен или замолчал), не должен держать старый риск
        ChannelRisk.objects.filter(task=model.task).exclude(as_of=as_of).delete()
    by_node: dict[int, list] = defaultdict(list)
    for r, risk in zip(results, risks, strict=True):
        by_node[r.node_id].append((r, risk))
    if full:
        RiskSnapshot.objects.bulk_create(
            [
                RiskSnapshot(
                    node_id=node_id,
                    task=model.task,
                    as_of=as_of,
                    max_probability=max(r.probability for r, _ in items),
                    expected_failures=round(sum(r.probability for r, _ in items), 3),
                    channels_total=len(items),
                    channels_at_risk=sum(_rank(k.risk_level) >= 1 for _, k in items),
                    risk_level=max((k.risk_level for _, k in items), key=_rank),
                )
                for node_id, items in by_node.items()
            ],
            batch_size=2000,
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
    journal = [k for k in risks if _rank(k.risk_level) >= _rank(JOURNAL_FROM)]
    issued, alerts = _journal(model, policy, as_of, journal, backtest)
    levels = defaultdict(int)
    for k in risks:
        levels[k.risk_level] += 1
    return {"channels": len(risks), "levels": dict(levels), "predictions": issued, "alerts": alerts}


def _journal(
    model: MLModel, policy: RiskPolicy, as_of: datetime, risky: list[ChannelRisk], backtest: bool = False
) -> tuple[int, int]:
    """Журнал прогнозов: новая запись — только если по каналу нет действующего прогноза или риск вырос."""
    from apps.incidents.models import Alert, IncidentType
    from apps.incidents.services import raise_alert

    open_predictions = {
        p.channel_id: p
        for p in Prediction.objects.filter(
            task=model.task,
            outcome=Prediction.Outcome.PENDING,
            valid_until__gt=as_of,
            channel_id__in=[k.channel_id for k in risky],
        )
    }
    channels = Channel.objects.select_related("node").in_bulk([k.channel_id for k in risky])
    alert_rank = _rank(policy.alert_from_level)
    issued = alerts = 0
    for risk in sorted(risky, key=lambda k: -k.probability):
        channel = channels[risk.channel_id]
        current = open_predictions.get(risk.channel_id)
        if current and _rank(risk.risk_level) <= _rank(current.risk_level):
            continue
        summary = _summary(channel, risk)
        if current:
            crossed = _rank(current.risk_level) < alert_rank <= _rank(risk.risk_level)
            current.probability, current.risk_level = risk.probability, risk.risk_level
            current.factors, current.summary = risk.factors, summary
            current.save(update_fields=["probability", "risk_level", "factors", "summary"])
            prediction = current
        else:
            crossed = _rank(risk.risk_level) >= alert_rank
            prediction = Prediction.objects.create(
                task=model.task,
                model=model,
                node=channel.node,
                channel=channel,
                issued_at=as_of,
                horizon_hours=model.horizon_hours,
                valid_until=as_of + timedelta(hours=model.horizon_hours),
                probability=risk.probability,
                risk_level=risk.risk_level,
                factors=risk.factors,
                summary=summary,
                is_backtest=backtest,
            )
            issued += 1
        if crossed and policy.enabled and not backtest:
            raise_alert(
                type=IncidentType.SENSOR_FAILURE,
                severity=risk.risk_level,
                node=channel.node,
                channel=channel,
                prediction=prediction,
                title=f"Прогноз: риск отказа «{channel.name}» в ближайшие {model.horizon_hours} ч",
                source=Alert.Source.FORECAST,
                raised_at=as_of,
                probability=risk.probability,
                horizon_hours=model.horizon_hours,
                details={"factors": risk.factors},
            )
            alerts += 1
    return issued, alerts


def _summary(channel: Channel, risk: ChannelRisk) -> str:
    reasons = "; ".join(f["title"] for f in risk.factors) or "совокупность признаков"
    return (
        f"Вероятность начала неисправности канала «{channel.name}» в ближайшие 24 ч — "
        f"{risk.probability:.0%}. Основные факторы: {reasons}."
    )


RESOLVE_SQL = """
UPDATE forecasting_prediction p SET outcome = CASE WHEN EXISTS (
        SELECT 1 FROM telemetry_channeldaily d
        WHERE d.channel_id = p.channel_id
          AND d.day BETWEEN (p.issued_at AT TIME ZONE 'Europe/Moscow')::date
                        AND (p.valid_until AT TIME ZONE 'Europe/Moscow')::date
          AND d.first_fault_ts > p.issued_at AND d.first_fault_ts <= p.valid_until
    ) OR EXISTS (
        SELECT 1 FROM telemetry_reading r
        WHERE r.channel_id = p.channel_id AND r.state = 'fault'
          AND r.ts > p.issued_at AND r.ts <= p.valid_until
    ) THEN 'confirmed' ELSE 'not_confirmed' END,
    outcome_at = %(as_of)s
WHERE p.outcome = 'pending' AND p.task = 'sensor_failure' AND p.valid_until <= %(as_of)s
"""


def resolve_outcomes(as_of: datetime) -> int:
    """Исход прогноза по факту: была ли неисправность канала в горизонте. Решение диспетчера приоритетнее."""
    with connection.cursor() as cursor:
        cursor.execute(RESOLVE_SQL, {"as_of": as_of})
        return cursor.rowcount


def backtest(start: datetime, end: datetime, step: timedelta = timedelta(days=1), echo=None) -> dict:
    """
    Прогон активной модели по истории: прогноз на каждый шаг, журнал с пометкой «бэктест»
    и разметка исходов по факту. Инциденты не создаются. Показывает, как модель отработала бы
    на реальном периоде, — это и проверка, и наполнение журнала прогнозов для демонстрации.
    """
    model = active_model()
    if model is None:
        raise ValueError("Нет активной модели")
    forecaster = forecaster_for(model)
    moment, issued, steps = start, 0, 0
    while moment <= end:
        result = store_forecast(model, moment, forecaster.predict(moment), backtest=True)
        resolve_outcomes(moment)
        issued += result["predictions"]
        steps += 1
        if echo:
            echo(f"{moment:%Y-%m-%d %H:%M}  прогнозов: {result['predictions']}")
        moment += step
    resolved = resolve_outcomes(end + timedelta(hours=model.horizon_hours))
    qs = Prediction.objects.filter(is_backtest=True, model=model)
    confirmed = qs.filter(outcome=Prediction.Outcome.CONFIRMED).count()
    total = qs.exclude(outcome=Prediction.Outcome.PENDING).count()
    return {
        "steps": steps,
        "predictions": issued,
        "resolved": resolved,
        "precision": round(confirmed / total, 3) if total else None,
    }


# ---------- качество данных и молчание ----------


def update_health(as_of: datetime) -> dict:
    items = health.compute(as_of)
    if not items:
        return {"channels": 0}
    previous = dict(ChannelHealth.objects.values_list("channel_id", "silent"))
    silent_since = dict(ChannelHealth.objects.filter(silent=True).values_list("channel_id", "silent_since"))
    ChannelHealth.objects.bulk_create(
        [
            ChannelHealth(
                channel_id=h.channel_id,
                computed_at=as_of,
                score=h.score,
                components=h.components,
                periodic=h.periodic,
                expected_interval_s=h.expected_interval_s,
                last_seen_at=h.last_seen_at,
                silent=h.silent,
                silent_since=(silent_since.get(h.channel_id) or h.last_seen_at) if h.silent else None,
            )
            for h in items
        ],
        batch_size=2000,
        update_conflicts=True,
        unique_fields=["channel"],
        update_fields=[
            "computed_at",
            "score",
            "components",
            "periodic",
            "expected_interval_s",
            "last_seen_at",
            "silent",
            "silent_since",
        ],
    )
    newly = [
        h
        for h in items
        if h.silent
        and not previous.get(h.channel_id)
        and h.last_seen_at
        and as_of - h.last_seen_at < health.FRESH_OUTAGE
    ]
    alerts = _silence_alerts(as_of, newly, items)
    scores = [h.score for h in items]
    return {
        "channels": len(items),
        "silent": sum(h.silent for h in items),
        "newly_silent": len(newly),
        "alerts": alerts,
        "score_median": sorted(scores)[len(scores) // 2],
        "poor": sum(s < 50 for s in scores),
    }


def _silence_alerts(as_of: datetime, newly: list, items: list) -> int:
    """Массовое молчание каналов объекта — одна тревога «потеря связи с объектом», а не по каналу на каждый."""
    from apps.incidents.models import Alert, IncidentType
    from apps.incidents.services import raise_alert

    if not newly:
        return 0
    periodic_per_node = defaultdict(int)
    for h in items:
        periodic_per_node[h.node_id] += h.periodic
    by_node = defaultdict(list)
    for h in newly:
        by_node[h.node_id].append(h)
    nodes = Node.objects.in_bulk(list(by_node))
    channels = Channel.objects.in_bulk([h.channel_id for h in newly])
    alerts = 0
    for node_id, group in by_node.items():
        node = nodes[node_id]
        if len(group) >= 3 or len(group) >= periodic_per_node[node_id] / 2:
            raise_alert(
                type=IncidentType.COMMUNICATION,
                severity=RiskLevel.HIGH,
                node=node,
                title=f"Потеря связи: {len(group)} каналов объекта «{node.name}» не передают данные",
                source=Alert.Source.RULE,
                raised_at=as_of,
                details={"channels": [h.channel_id for h in group]},
            )
            alerts += 1
            continue
        for h in group:
            channel = channels[h.channel_id]
            raise_alert(
                type=IncidentType.COMMUNICATION,
                severity=RiskLevel.MEDIUM,
                node=node,
                channel=channel,
                title=f"Нет данных от канала «{channel.name}»",
                source=Alert.Source.RULE,
                raised_at=as_of,
                details={
                    "last_seen_at": h.last_seen_at.isoformat(),
                    "expected_interval_s": h.expected_interval_s,
                },
            )
            alerts += 1
    return alerts


def check_stream(as_of: datetime) -> str:
    """Поток СМВУ был живым и замолчал — системная тревога на корне дерева объектов."""
    from apps.incidents.models import Alert, IncidentType
    from apps.incidents.services import raise_alert

    now = timezone.now()
    lag = now - as_of
    if lag < STREAM_STALE:
        return "live"
    if lag > LIVE_WINDOW:
        return "historical"  # стенд на загруженной истории без живого потока
    from apps.incidents.models import Incident

    root = Node.objects.filter(depth=1, is_active=True).order_by("path").first()
    already = Incident.objects.filter(
        node=root,
        type=IncidentType.COMMUNICATION,
        status__in=Incident.OPEN_STATUSES,
        title__startswith="Нет потока",
    ).exists()
    if root and not already:
        raise_alert(
            type=IncidentType.COMMUNICATION,
            severity=RiskLevel.CRITICAL,
            node=root,
            title=f"Нет потока данных СМВУ {int(lag.total_seconds() // 60)} мин",
            source=Alert.Source.RULE,
            raised_at=now,
            details={"last_data_at": as_of.isoformat()},
        )
    return "stale"

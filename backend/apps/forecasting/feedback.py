"""
Обратная связь диспетчеров → метки обучения. Решение по инциденту порождает метки по каналам
инцидента согласно правилам разметки; аналитик проверяет их и управляет тем, что попадёт в модель.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta
from zoneinfo import ZoneInfo

import polars as pl
from django.db import transaction
from django.utils import timezone

from .domain.feedback import LABEL_SCHEMA, empty_labels
from .models import FeedbackEffect, FeedbackLabel, FeedbackRule, ForecastTask

MSK = ZoneInfo("Europe/Moscow")
MAX_CHANNELS = 500
PREVENTED = "prediction-prevented"

# Стартовые правила. Коды совпадают с DecisionReason (bootstrap), кроме служебного «предотвращён».
DEFAULT_RULES = [
    (
        "false-sensor-fault",
        FeedbackEffect.POSITIVE,
        3.0,
        True,
        "Диспетчер установил, что сработка — от неисправного датчика: это подтверждённый отказ.",
    ),
    (
        "brigade-equipment",
        FeedbackEffect.POSITIVE,
        3.0,
        True,
        "Бригада выехала на отказ оборудования: отказ подтверждён на месте.",
    ),
    (
        "resolved-onsite",
        FeedbackEffect.POSITIVE,
        2.0,
        False,
        "Устранено на месте: скорее всего был реальный отказ, но причина могла быть иной — стоит проверить.",
    ),
    (
        "resolved-remote",
        FeedbackEffect.POSITIVE,
        1.0,
        False,
        "Устранено дистанционно (перезапуск): сбой был, но мог быть программным.",
    ),
    ("confirmed", FeedbackEffect.POSITIVE, 2.0, False, "Инцидент подтверждён."),
    (
        "false-power-glitch",
        FeedbackEffect.NEGATIVE,
        2.0,
        True,
        "Кратковременный сбой питания или связи — не отказ датчика: «неисправен» в журнале здесь ложная метка.",
    ),
    (
        "false-maintenance",
        FeedbackEffect.EXCLUDE,
        1.0,
        True,
        "Плановые работы: состояния каналов в это время не отражают их исправность.",
    ),
    (
        "false-authorized-access",
        FeedbackEffect.EXCLUDE,
        1.0,
        True,
        "Санкционированный доступ: работы на объекте искажают состояния каналов.",
    ),
    (
        "false-environment",
        FeedbackEffect.IGNORE,
        1.0,
        True,
        "Внешнее воздействие на физический датчик — к отказу датчика не относится.",
    ),
    (
        "cause-sensor_fault",
        FeedbackEffect.POSITIVE,
        2.0,
        True,
        "Диспетчер указал «неисправность датчика»: подтверждённый отказ канала.",
    ),
    (
        "cause-communication",
        FeedbackEffect.NEGATIVE,
        1.5,
        True,
        "Причина — потеря связи: «неисправен» в журнале не означает отказ датчика.",
    ),
    (
        "cause-power",
        FeedbackEffect.NEGATIVE,
        1.5,
        True,
        "Причина — обесточивание: датчик исправен, отказа не было.",
    ),
    (
        "cause-works",
        FeedbackEffect.EXCLUDE,
        1.0,
        True,
        "Работы на объекте: состояния каналов в это время не отражают их исправность.",
    ),
    (
        "cause-false_alarm",
        FeedbackEffect.IGNORE,
        1.0,
        True,
        "Ложное срабатывание без уточнения: для отказа датчика неоднозначно — уточните причиной.",
    ),
    (
        "cause-external",
        FeedbackEffect.IGNORE,
        1.0,
        True,
        "Внешнее воздействие на физический датчик — к отказу датчика не относится.",
    ),
    (
        "cause-real_event",
        FeedbackEffect.IGNORE,
        1.0,
        True,
        "Реальное событие (пожар, газ, вода, доступ) — к отказу датчика не относится.",
    ),
    (
        "cause-insufficient_data",
        FeedbackEffect.IGNORE,
        1.0,
        True,
        "Недостаточно данных для вывода — метку не ставим.",
    ),
    (
        PREVENTED,
        FeedbackEffect.EXCLUDE,
        1.0,
        True,
        "По прогнозу успели устранить причину: отсутствие отказа — заслуга бригады, а не ошибка модели.",
    ),
]


def seed_rules() -> int:
    from apps.incidents.models import DecisionCause, DecisionReason

    titles = dict(DecisionReason.objects.values_list("code", "name"))
    titles |= {f"cause-{value}": f"Что произошло: {label.lower()}" for value, label in DecisionCause.choices}
    created = 0
    for code, effect, weight, auto, text in DEFAULT_RULES:
        _, new = FeedbackRule.objects.get_or_create(
            code=code,
            defaults={
                "title": titles.get(code, "Прогноз: отказ предотвращён"),
                "effect": effect,
                "weight": weight,
                "auto_accept": auto,
                "description": text,
            },
        )
        created += new
    return created


def _date(ts):
    return ts.astimezone(MSK).date()


@transaction.atomic
def labels_from_decision(decision) -> int:
    """Метки по каналам инцидента. Прогнозный инцидент, по которому отказ предотвратили, — исключение из обучения."""
    from apps.incidents.models import DecisionOutcome

    incident = decision.incident
    # Приоритет: предотвращённый прогноз, затем «что произошло», затем причина решения
    codes = [
        f"cause-{decision.cause}" if decision.cause else None,
        decision.reason.code if decision.reason else None,
    ]
    if incident.is_forecast and decision.outcome == DecisionOutcome.RESOLVED:
        codes.insert(0, PREVENTED)
    rules = {r.code: r for r in FeedbackRule.objects.filter(code__in=[c for c in codes if c], enabled=True)}
    rule = next(
        (rules[c] for c in codes if c in rules and rules[c].effect != FeedbackEffect.IGNORE),
        None,
    )
    if rule is None:
        return 0
    status = FeedbackLabel.Status.ACCEPTED if rule.auto_accept else FeedbackLabel.Status.PENDING
    first_seen: dict[int, tuple] = {}
    for alert in (
        incident.alerts.exclude(channel=None)
        .select_related("prediction")
        .order_by("raised_at")[: MAX_CHANNELS * 3]
    ):
        if alert.channel_id in first_seen:
            continue
        if alert.prediction:
            # прогноз на конец суток d говорит о сутках d+1
            day = _date(alert.prediction.issued_at) + timedelta(days=1)
        else:
            day = _date(alert.raised_at)
        first_seen[alert.channel_id] = (day, alert.prediction_id)
        if len(first_seen) >= MAX_CHANNELS:
            break
    labels = [
        FeedbackLabel(
            task=ForecastTask.SENSOR_FAILURE,
            channel_id=channel_id,
            label_date=day,
            effect=rule.effect,
            weight=rule.weight,
            status=status,
            rule=rule,
            decision=decision,
            incident=incident,
            prediction_id=prediction_id,
            decided_by=decision.decided_by,
        )
        for channel_id, (day, prediction_id) in first_seen.items()
    ]
    FeedbackLabel.objects.bulk_create(labels, ignore_conflicts=True)
    return len(labels)


def accepted_labels(task: str = ForecastTask.SENSOR_FAILURE) -> pl.DataFrame:
    rows = list(
        FeedbackLabel.objects.filter(task=task, status=FeedbackLabel.Status.ACCEPTED)
        .exclude(effect=FeedbackEffect.IGNORE)
        .values_list("id", "channel_id", "label_date", "effect", "weight")
    )
    if not rows:
        return empty_labels()
    return pl.DataFrame(rows, schema=LABEL_SCHEMA, orient="row")


def labels_fingerprint(labels: pl.DataFrame) -> str:
    """Ключ кеша выборки: другая разметка — другая выборка."""
    if labels.is_empty():
        return "nofb"
    digest = hashlib.sha1(labels.sort("label_id").write_csv().encode(), usedforsecurity=False).hexdigest()[
        :10
    ]
    return f"fb{digest}"


@transaction.atomic
def review(labels, user, status: str, comment: str = "") -> int:
    """Принять или отклонить метки. Отклонённая метка не попадёт в следующее обучение."""
    return labels.update(
        status=status, reviewed_by=user, reviewed_at=timezone.now(), review_comment=comment[:512]
    )


def record_usage(model, per_label: dict[int, int]) -> None:
    """После обучения: сколько строк изменила каждая метка и в какой версии она учтена."""
    by_rows: dict[int, list[int]] = {}
    for label_id, rows in per_label.items():
        by_rows.setdefault(rows, []).append(label_id)
    for rows, ids in by_rows.items():
        FeedbackLabel.objects.filter(pk__in=ids).update(rows_affected=rows, last_used_model=model)

"""
Эмуляция дежурных смен для демонстрации аналитики (ТЗ §8): на стенде нет истории работы
диспетчеров, поэтому реальные эпизоды из данных заказчика (та же склейка, что в работе)
превращаются в карточки, а демо-диспетчеры «отрабатывают» их со случайными, но правдоподобными
задержками. Решение выбирается по гипотезам карточки с учётом их весов.

Всё созданное помечено `is_emulated`: карточки видны с пометкой «эмуляция», из отчётов исключаются
флажком, метки для обучения по ним не создаются (решения пишутся напрямую, без services.decide).
"""

from __future__ import annotations

import hashlib
import math
import random
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction

from apps.accounts.models import User
from apps.audit.models import ActionLog
from apps.forecasting.models import Prediction
from apps.incidents.domain.actions import next_actions
from apps.incidents.domain.correlation import contour
from apps.incidents.domain.priority import PriorityInput, priority
from apps.incidents.models import (
    Alert,
    Decision,
    DecisionReason,
    EscalationPolicy,
    Incident,
    IncidentEvent,
    IncidentType,
)
from apps.topology.models import Node

MSK = ZoneInfo("Europe/Moscow")
DISPATCHER_ROLES = ("ods_dispatcher", "unit_dispatcher")
# Медиана «до просмотра», мин — по уровню; разброс логнормальный
VIEW_MEDIAN = {"critical": 1.5, "high": 4, "medium": 12, "low": 30}
DECIDE_MEDIAN = {"physical": 10, "technical": 25}

# Гипотеза → (что произошло, решение, код причины)
BY_HYPOTHESIS = {
    "power": ("power", "resolved", "resolved-remote"),
    "communication": ("communication", "resolved", "resolved-remote"),
    "module": ("sensor_fault", "brigade_dispatched", "brigade-equipment"),
    "sensor": ("sensor_fault", "false_alarm", "false-sensor-fault"),
    "works": ("works", "false_alarm", "false-maintenance"),
    "false": ("false_alarm", "false_alarm", "false-environment"),
    "unknown": ("insufficient_data", "check_requested", "check-patrol"),
    "fire": ("real_event", "brigade_dispatched", "brigade-fire"),
    "flood": ("real_event", "brigade_dispatched", "brigade-flood"),
    "intrusion": ("real_event", "brigade_dispatched", "brigade-intrusion"),
    "gas": ("real_event", "check_requested", "check-patrol"),
}


def _lognormal(rng: random.Random, med: float, sigma: float = 0.8) -> float:
    return med * math.exp(rng.gauss(0, sigma))


def _speed(user: User) -> float:
    """У каждого сотрудника свой темп — чтобы в метриках по сотрудникам была разница."""
    h = int(hashlib.md5(user.username.encode()).hexdigest()[:6], 16) / 0xFFFFFF
    return 0.6 + 0.9 * h


class Shift:
    def __init__(self, seed: int = 7):
        self.rng = random.Random(seed)
        users = list(
            User.objects.filter(groups__name__in=DISPATCHER_ROLES, is_active=True)
            .select_related("scope_node")
            .distinct()
        )
        self.ods = sorted(
            (u for u in users if u.groups.filter(name="ods_dispatcher").exists()), key=lambda u: u.pk
        )
        self.units = [u for u in users if u not in self.ods and u.scope_node]
        self.reasons = {r.code: r for r in DecisionReason.objects.all()}
        self.timeouts = dict(EscalationPolicy.objects.values_list("severity", "ack_timeout_minutes"))

    def dispatcher(self, node: Node, at: datetime) -> User | None:
        local = [u for u in self.units if node.path.startswith(u.scope_node.path)]
        if local and self.rng.random() < 0.75:
            return self.rng.choice(local)
        if not self.ods:
            return local[0] if local else None
        # дневная смена 08–20 у первого диспетчера ОДС, ночная — у второго
        day_shift = 8 <= at.astimezone(MSK).hour < 20
        return self.ods[0] if day_shift or len(self.ods) == 1 else self.ods[1]

    def work(
        self, incident: Incident, hypotheses: list[dict], events: list, views: list, is_forecast_ok=None
    ):
        """Действия диспетчера по карточке: просмотр, взять, решение; эскалация, если не успел."""
        rng = self.rng
        user = self.dispatcher(incident.node, incident.opened_at)
        if user is None:
            return None
        night = not (8 <= incident.opened_at.astimezone(MSK).hour < 20)
        pace = _speed(user) * (1.4 if night else 1.0)
        view = incident.opened_at + timedelta(minutes=_lognormal(rng, VIEW_MEDIAN[incident.severity] * pace))
        take = view + timedelta(minutes=_lognormal(rng, 1.5, 0.6))
        decide = take + timedelta(
            minutes=_lognormal(rng, DECIDE_MEDIAN[incident.contour or "technical"] * pace)
        )
        timeout = self.timeouts.get(incident.severity)
        if timeout and (view - incident.opened_at) > timedelta(minutes=timeout):
            incident.escalation_level = 1
            events.append(
                (
                    IncidentEvent.Kind.ESCALATED,
                    incident.opened_at + timedelta(minutes=timeout),
                    None,
                    "Эскалация на уровень выше (нет реакции)",
                )
            )
        views.append((user, view))
        events.append((IncidentEvent.Kind.ASSIGNED, take, user, f"Взят в работу: {user.get_full_name()}"))

        if incident.is_forecast:
            cause, outcome, code = is_forecast_ok
        else:
            weights = [max(h["weight"], 0.01) for h in hypotheses] or [1.0]
            pick = rng.choices(hypotheses, weights)[0]["code"] if hypotheses else "unknown"
            cause, outcome, code = BY_HYPOTHESIS.get(pick, BY_HYPOTHESIS["unknown"])
            if rng.random() < 0.08:  # не всегда причину удаётся установить
                cause, outcome, code = BY_HYPOTHESIS["unknown"]
        reason = self.reasons.get(code)
        decision = Decision(
            incident=incident,
            outcome=outcome,
            reason=reason if reason and reason.outcome == outcome else None,
            cause=cause,
            comment="эмуляция смены",
            decided_by=user,
        )
        if incident.is_forecast:
            decision.forecast_useful = {"yes": True, "no": False}.get(self._useful(cause))
        incident.status = Incident.Status.RESOLVED
        incident.assigned_to = user
        incident.acknowledged_at = view
        incident.resolved_at = decide
        events.append(
            (IncidentEvent.Kind.DECISION, decide, user, f"{decision.get_outcome_display()} · эмуляция")
        )
        return decision, decide

    def _useful(self, cause: str) -> str:
        r = self.rng.random()
        if cause in ("sensor_fault", "real_event"):
            return "yes" if r < 0.8 else "unknown"
        return "no" if r < 0.6 else "unknown"


def _incident_from_episode(ep: dict, node: Node, shift: Shift) -> tuple[Incident, list[dict]]:
    opened = datetime.fromisoformat(ep["first"])
    top = ep["hypotheses"][0]["code"] if ep["hypotheses"] else None
    real = next((h["weight"] for h in ep["hypotheses"] if h["code"] == ep["type"]), None)
    score, factors = priority(
        PriorityInput(
            severity=ep["severity"],
            contour=ep["contour"],
            criticality=node.criticality,
            health=None,
            channels=ep["channels"],
            opened_at=opened,
            ack_deadline=None,
            escalation_level=0,
            acknowledged=True,
            probability=None,
            now=opened,
            real_threat=real,
        )
    )
    incident = Incident(
        type=ep["type"],
        severity=ep["severity"],
        node=node,
        responsible_node=node,
        title=f"{IncidentType(ep['type']).label}: {node.name}",
        description=f"Эпизод {ep['signals']} сигналов по {ep['channels']} каналам (эмуляция смены)",
        opened_at=opened,
        contour=ep["contour"],
        signals_count=ep["signals"],
        channels_count=ep["channels"],
        first_signal_at=opened,
        last_signal_at=datetime.fromisoformat(ep["last"]),
        hypotheses=ep["hypotheses"],
        actions=[
            {"code": c, "title": t, "done": False, "done_by": None, "done_at": None}
            for c, t in next_actions(ep["type"], top)
        ],
        priority=score,
        priority_factors=factors,
        is_emulated=True,
    )
    return incident, ep["hypotheses"]


FORECAST_CAUSE = {
    "sensor_failure": ("sensor_fault", "brigade_dispatched", "brigade-equipment"),
    "gas": ("real_event", "check_requested", "check-patrol"),
    "flood": ("real_event", "brigade_dispatched", "brigade-flood"),
    "fire": ("real_event", "check_requested", "check-video"),
    "intrusion": ("real_event", "check_requested", "check-video"),
}
FORECAST_MISS = ("false_alarm", "monitoring", "monitor-trend")


def _incident_from_prediction(p: Prediction) -> Incident:
    return Incident(
        type=p.task,
        severity=p.risk_level,
        is_forecast=True,
        node=p.node,
        responsible_node=p.node,
        title=f"Прогноз: {IncidentType(p.task).label.lower()} — {p.channel.name if p.channel else p.node.name}",
        description=p.summary,
        probability=p.probability,
        horizon_hours=p.horizon_hours,
        opened_at=p.issued_at,
        contour=contour(p.task),
        signals_count=1,
        channels_count=1 if p.channel_id else 0,
        first_signal_at=p.issued_at,
        last_signal_at=p.issued_at,
        priority=round(100 * p.probability * (1.0 if p.risk_level == "critical" else 0.75), 1),
        is_emulated=True,
    )


def emulate(start: date, end: date, *, seed: int = 7, echo=None) -> dict:
    """Карточки и действия диспетчеров за сутки [start, end] по времени Москвы."""
    from apps.analytics.replay import ReplayError, replay

    shift = Shift(seed)
    complexes = list(Node.objects.filter(depth=2, is_active=True))
    stats = {"facts": 0, "forecasts": 0, "decisions": 0, "escalated": 0}
    day = start
    while day <= end:
        t0 = datetime.combine(day, time(), MSK)
        created: list[tuple[Incident, list[dict], tuple | None]] = []
        for node in complexes:
            try:
                result = replay(node, t0, t0 + timedelta(hours=24), with_forecast=False)
            except ReplayError:
                continue
            nodes = Node.objects.in_bulk({ep["node_id"] for ep in result["episodes"]})
            for ep in result["episodes"]:
                incident, hyps = _incident_from_episode(ep, nodes[ep["node_id"]], shift)
                created.append((incident, hyps, None))
        predictions = (
            Prediction.objects.filter(
                is_backtest=True,
                issued_at__gte=t0,
                issued_at__lt=t0 + timedelta(hours=24),
                risk_level__in=("high", "critical"),
            )
            .exclude(task="sensor_failure", risk_level="high")  # «высоких» по отказу десятки в сутки
            .select_related("node", "channel")
        )
        for p in predictions:
            ok = FORECAST_CAUSE[p.task] if p.outcome == "confirmed" else FORECAST_MISS
            created.append((_incident_from_prediction(p), [], (ok, p)))
        _save_day(shift, created, stats)
        if echo:
            echo(f"{day}: карточек {len(created)}")
        day += timedelta(days=1)
    return stats


@transaction.atomic
def _save_day(shift: Shift, created: list, stats: dict) -> None:
    incidents = Incident.objects.bulk_create([c[0] for c in created])
    events, views, decisions, alerts = [], [], [], []
    for incident, (_, hyps, forecast) in zip(incidents, created, strict=True):
        ev = [(IncidentEvent.Kind.OPENED, incident.opened_at, None, "Карточка открыта (эмуляция смены)")]
        vw = []
        result = shift.work(incident, hyps, ev, vw, is_forecast_ok=forecast[0] if forecast else None)
        if forecast:
            p = forecast[1]
            alerts.append(
                Alert(
                    incident=incident,
                    source=Alert.Source.FORECAST,
                    type=p.task,
                    severity=p.risk_level,
                    node=p.node,
                    channel=p.channel,
                    prediction=p,
                    raised_at=p.issued_at,
                    title=incident.title,
                )
            )
            stats["forecasts"] += 1
        else:
            stats["facts"] += 1
        if result:
            decisions.append((result[0], result[1]))
            stats["decisions"] += 1
        stats["escalated"] += incident.escalation_level > 0
        events += [(incident, *e) for e in ev]
        views += [(incident, *v) for v in vw]
    Incident.objects.bulk_update(
        incidents, ["status", "assigned_to", "acknowledged_at", "resolved_at", "escalation_level"]
    )
    Alert.objects.bulk_create(alerts)
    made = Decision.objects.bulk_create([d for d, _ in decisions])
    _backdate(Decision, "decided_at", [(d.pk, ts) for d, (_, ts) in zip(made, decisions, strict=True)])
    made = IncidentEvent.objects.bulk_create(
        [IncidentEvent(incident=i, kind=k, actor=a, text=t) for i, k, _, a, t in events]
    )
    _backdate(IncidentEvent, "ts", [(e.pk, ts) for e, (_, _, ts, _, _) in zip(made, events, strict=True)])
    made = ActionLog.objects.bulk_create(
        [
            ActionLog(
                user=u,
                username=u.username,
                action="incident.view",
                method="GET",
                object_type="incidents.incident",
                object_id=str(i.pk),
                object_repr=i.title[:255],
                payload={"emulated": True},
            )
            for i, u, _ in views
        ]
    )
    _backdate(ActionLog, "ts", [(v.pk, ts) for v, (_, _, ts) in zip(made, views, strict=True)])


def _backdate(model, field: str, rows: list[tuple[int, datetime]]) -> None:
    """auto_now_add не даёт задать время при создании — проставляем историческое отдельно."""
    for pk, ts in rows:
        model.objects.filter(pk=pk).update(**{field: ts})


def clear() -> int:
    ids = list(Incident.objects.filter(is_emulated=True).values_list("pk", flat=True))
    ActionLog.objects.filter(object_type="incidents.incident", object_id__in=[str(i) for i in ids]).delete()
    Incident.objects.filter(pk__in=ids).delete()
    return len(ids)

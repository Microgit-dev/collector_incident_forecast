"""
Эффективность работы диспетчеров (ТЗ §8): сколько карточек на смену, как быстро их открывают,
берут в работу и решают, сколько уходит в эскалацию по таймауту, у скольких закрытых указан
результат, во сколько раз поток сигналов сжат в карточки. По сотрудникам — та же картина.

Источники: карточки инцидентов, их события (взят, эскалация), решения, журнал просмотров.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from statistics import median

from django.utils import timezone

from apps.audit.models import ActionLog
from apps.incidents.models import Decision, DecisionCause, Incident, IncidentEvent
from apps.topology.selectors import scope_queryset

SHIFT_HOURS = 12
SEVERITIES = ("critical", "high", "medium", "low")


def _minutes(a: datetime | None, b: datetime | None) -> float | None:
    if a is None or b is None:
        return None
    return max((b - a).total_seconds() / 60, 0.0)


def _stats(values: list[float]) -> dict:
    values = sorted(v for v in values if v is not None)
    if not values:
        return {"n": 0, "median": None, "p90": None}
    return {
        "n": len(values),
        "median": round(median(values), 1),
        "p90": round(values[min(len(values) - 1, int(0.9 * len(values)))], 1),
    }


def _share(part: int, total: int) -> float | None:
    return round(part / total, 3) if total else None


def incidents_in(user, since: datetime, until: datetime, include_emulated: bool = True):
    qs = scope_queryset(Incident.objects.all(), user, "node").filter(
        opened_at__gte=since, opened_at__lt=until
    )
    return qs if include_emulated else qs.filter(is_emulated=False)


def efficiency(user, since: datetime, until: datetime, include_emulated: bool = True) -> dict:
    incidents = list(
        incidents_in(user, since, until, include_emulated).values(
            "id",
            "type",
            "severity",
            "status",
            "contour",
            "is_forecast",
            "is_emulated",
            "opened_at",
            "signals_count",
        )
    )
    ids = [i["id"] for i in incidents]
    views: dict[int, datetime] = {}
    for object_id, ts in (
        ActionLog.objects.filter(action="incident.view", object_id__in=[str(i) for i in ids])
        .order_by("ts")
        .values_list("object_id", "ts")
    ):
        views.setdefault(int(object_id), ts)
    taken: dict[int, tuple] = {}
    escalated: dict[int, int] = Counter()
    for incident_id, kind, ts, actor, text in (
        IncidentEvent.objects.filter(
            incident_id__in=ids, kind__in=(IncidentEvent.Kind.ASSIGNED, IncidentEvent.Kind.ESCALATED)
        )
        .order_by("ts")
        .values_list("incident_id", "kind", "ts", "actor_id", "text")
    ):
        if kind == IncidentEvent.Kind.ASSIGNED:
            taken.setdefault(incident_id, (ts, actor))
        elif "нет реакции" in text:
            escalated[incident_id] += 1
    decisions: dict[int, Decision] = {}
    for d in (
        Decision.objects.filter(incident_id__in=ids)
        .select_related("decided_by", "decided_by__team")
        .order_by("decided_at")
    ):
        decisions.setdefault(d.incident_id, d)

    rows = []
    for i in incidents:
        d = decisions.get(i["id"])
        first_view = views.get(i["id"])
        take = taken.get(i["id"])
        rows.append(
            {
                **i,
                "view_min": _minutes(i["opened_at"], first_view),
                "take_min": _minutes(i["opened_at"], take[0]) if take else None,
                "decision_min": _minutes(i["opened_at"], d.decided_at) if d else None,
                "escalated": escalated.get(i["id"], 0) > 0,
                "decision": d,
            }
        )

    closed = [r for r in rows if r["status"] in (Incident.Status.RESOLVED, Incident.Status.CLOSED)]
    with_result = [r for r in closed if r["decision"] and (r["decision"].cause or r["decision"].reason_id)]
    hours = max((until - since).total_seconds() / 3600, 1)
    signals = sum(r["signals_count"] for r in rows if not r["is_forecast"])
    facts = sum(1 for r in rows if not r["is_forecast"])
    forecast_decisions = [r["decision"] for r in rows if r["is_forecast"] and r["decision"]]
    useful = Counter(
        "yes" if d.forecast_useful else "no" if d.forecast_useful is False else "unknown"
        for d in forecast_decisions
    )

    by_severity = {}
    for sev in SEVERITIES:
        part = [r for r in rows if r["severity"] == sev]
        if part:
            by_severity[sev] = {
                "cards": len(part),
                "view": _stats([r["view_min"] for r in part]),
                "decision": _stats([r["decision_min"] for r in part]),
                "escalated_share": _share(sum(r["escalated"] for r in part), len(part)),
            }

    daily: dict[str, dict] = defaultdict(lambda: {"cards": 0, "decisions": [], "escalated": 0})
    for r in rows:
        day = timezone.localtime(r["opened_at"]).date().isoformat()
        daily[day]["cards"] += 1
        daily[day]["escalated"] += r["escalated"]
        if r["decision_min"] is not None:
            daily[day]["decisions"].append(r["decision_min"])

    return {
        "period": {"from": since, "to": until},
        "emulated": sum(r["is_emulated"] for r in rows),
        "summary": {
            "cards": len(rows),
            "cards_per_shift": round(len(rows) / (hours / SHIFT_HOURS), 1),
            "signals": signals,
            "reduction": round(signals / facts, 1) if facts else None,
            "view": _stats([r["view_min"] for r in rows]),
            "take": _stats([r["take_min"] for r in rows]),
            "decision": _stats([r["decision_min"] for r in rows]),
            "escalated_share": _share(sum(r["escalated"] for r in rows), len(rows)),
            "decided_share": _share(sum(1 for r in rows if r["decision"]), len(rows)),
            "closed": len(closed),
            "closed_with_result_share": _share(len(with_result), len(closed)),
            "forecast_useful": dict(useful),
        },
        "by_severity": by_severity,
        "causes": _causes(rows),
        "daily": [
            {
                "day": day,
                "cards": v["cards"],
                "escalated": v["escalated"],
                "decision_median": round(median(v["decisions"]), 1) if v["decisions"] else None,
            }
            for day, v in sorted(daily.items())
        ],
        "staff": _staff(rows),
    }


def _causes(rows: list[dict]) -> list[dict]:
    labels = dict(DecisionCause.choices)
    counts = Counter(r["decision"].cause or "none" for r in rows if r["decision"])
    return [{"cause": c, "title": labels.get(c, "не указано"), "count": n} for c, n in counts.most_common()]


def _staff(rows: list[dict]) -> list[dict]:
    per: dict[int, dict] = {}
    for r in rows:
        d = r["decision"]
        if d is None:
            continue
        u = d.decided_by
        item = per.setdefault(
            u.pk,
            {
                "user": u.pk,
                "name": u.get_full_name() or u.get_username(),
                "position": getattr(u, "position", ""),
                "team": u.team.name if getattr(u, "team", None) else None,
                "decisions": 0,
                "view": [],
                "decision": [],
                "escalated": 0,
                "with_cause": 0,
                "false_alarm": 0,
                "emulated": 0,
            },
        )
        item["decisions"] += 1
        item["view"].append(r["view_min"])
        item["decision"].append(r["decision_min"])
        item["escalated"] += r["escalated"]
        item["with_cause"] += bool(d.cause)
        item["false_alarm"] += d.outcome == "false_alarm"
        item["emulated"] += r["is_emulated"]
    out = []
    for item in per.values():
        n = item["decisions"]
        out.append(
            item
            | {
                "view": _stats(item["view"])["median"],
                "decision": _stats(item["decision"])["median"],
                "escalated_share": _share(item["escalated"], n),
                "with_cause_share": _share(item["with_cause"], n),
                "false_alarm_share": _share(item["false_alarm"], n),
            }
        )
    return sorted(out, key=lambda x: -x["decisions"])


def default_period(user) -> tuple[datetime, datetime]:
    """Последние 30 суток до самой свежей карточки в зоне ответственности (на стенде — не «сейчас»)."""
    last = (
        scope_queryset(Incident.objects.all(), user, "node")
        .order_by("-opened_at")
        .values_list("opened_at", flat=True)
        .first()
    )
    end = (last or timezone.now()) + timedelta(minutes=1)
    return end - timedelta(days=30), end

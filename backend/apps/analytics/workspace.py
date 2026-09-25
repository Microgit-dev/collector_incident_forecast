"""
Рабочее место роли (главная страница): что важно этой роли прямо сейчас — счётчики, короткие списки
и настройка схемы. Схема в центре у всех ролей, меняется её слой: диспетчеру — риски и карточки,
руководителю — ещё и заявки на утверждение, аналитику — качество данных, бригаде — свои заявки.

Все выборки ограничены зоной ответственности пользователя (scope_queryset), как и остальной API.
"""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from apps.accounts.roles import ROLES, Role
from apps.forecasting.models import ChannelHealth, ChannelRisk, FeedbackLabel
from apps.incidents.models import Incident
from apps.topology.selectors import scope_queryset
from apps.workorders.models import WorkOrder

# Порядок выбора рабочего места по умолчанию: самая «оперативная» роль пользователя
ROLE_ORDER = ["technician", "unit_dispatcher", "ods_dispatcher", "head", "analyst", "observer", "admin"]
OPEN = (Incident.Status.NEW, Incident.Status.ACKNOWLEDGED, Incident.Status.IN_PROGRESS)
CLOSED_ORDERS = (WorkOrder.Status.DONE, WorkOrder.Status.CANCELLED)
HIGH = ("high", "critical")
WEAK_HEALTH = 40


def roles_of(user) -> list[str]:
    codes = set(user.groups.values_list("name", flat=True))
    if user.is_superuser:
        codes.add("admin")
    return [r for r in ROLE_ORDER if r in codes] or ["observer"]


def _kpi(
    key: str, label: str, value: int, *, hint: str = "", color: str | None = None, to: str | None = None
):
    return {"key": key, "label": label, "value": value, "hint": hint, "color": color, "to": to}


def _incidents(user):
    return scope_queryset(Incident.objects.filter(status__in=OPEN), user, "node")


def _orders(user):
    return scope_queryset(WorkOrder.objects.exclude(status__in=CLOSED_ORDERS), user, "node")


def _high_risk(user) -> int:
    return scope_queryset(ChannelRisk.objects.filter(risk_level__in=HIGH), user, "channel__node").count()


def _health(user):
    return scope_queryset(ChannelHealth.objects.all(), user, "channel__node")


def _incident_row(i: Incident) -> dict:
    return {
        "id": i.pk,
        "title": i.title,
        "type": i.type,
        "severity": i.severity,
        "status": i.status,
        "priority": round(i.priority),
        "escalation_level": i.escalation_level,
        "opened_at": i.opened_at,
        "node": i.node.name,
    }


def _order_row(o: WorkOrder, now) -> dict:
    return {
        "id": o.pk,
        "number": o.number,
        "title": o.title,
        "status": o.status,
        "priority": o.priority,
        "work_type": o.work_type,
        "due_at": o.due_at,
        "overdue": o.due_at < now,
        "node": o.node.name,
        "created_by": o.created_by.get_full_name() if o.created_by else None,
        "external_status": o.external_status,
    }


def _dispatcher(user, now) -> dict:
    incidents = _incidents(user)
    new = incidents.filter(status=Incident.Status.NEW)
    return {
        "kpis": [
            _kpi(
                "new",
                "Ждут принятия",
                new.count(),
                hint="новые карточки в зоне",
                color="red",
                to="/incidents",
            ),
            _kpi(
                "overdue",
                "Просрочена реакция",
                new.filter(ack_deadline__lt=now).count(),
                hint="уже эскалируются вверх",
                color="red",
                to="/incidents",
            ),
            _kpi(
                "mine",
                "У меня в работе",
                incidents.filter(assigned_to=user).exclude(status=Incident.Status.NEW).count(),
                hint="принятые мной",
                color="blue",
                to="/incidents",
            ),
            _kpi(
                "drafts",
                "Черновики заявок",
                _orders(user).filter(status=WorkOrder.Status.DRAFT, created_by=user).count(),
                hint="ждут утверждения руководителем",
                to="/workorders",
            ),
            _kpi(
                "risk",
                "Высокий риск",
                _high_risk(user),
                hint="каналы по прогнозу",
                color="orange",
                to="/forecasts",
            ),
        ],
        "lists": {},
        "map": {"color_by": "risk", "incidents": True, "workorders": False},
    }


def _head(user, now) -> dict:
    incidents = _incidents(user).select_related("node")
    orders = _orders(user).select_related("node", "created_by")
    escalated = incidents.filter(escalation_level__gt=0).order_by("-escalation_level", "-priority")
    approvals = orders.filter(status=WorkOrder.Status.DRAFT).order_by("due_at")
    return {
        "kpis": [
            _kpi(
                "escalated",
                "Эскалированы",
                escalated.count(),
                hint="смена не отреагировала в срок",
                color="grape",
                to="/incidents",
            ),
            _kpi(
                "approvals",
                "Заявки на утверждение",
                approvals.count(),
                hint="черновики диспетчеров",
                color="blue",
                to="/workorders",
            ),
            _kpi(
                "open", "Открытые карточки", incidents.count(), hint="в зоне ответственности", to="/incidents"
            ),
            _kpi(
                "orders_overdue",
                "Заявки с просроченным сроком",
                orders.filter(due_at__lt=now).count(),
                color="red",
                to="/workorders",
            ),
        ],
        "lists": {
            "escalated": [_incident_row(i) for i in escalated[:6]],
            "approvals": [_order_row(o, now) for o in approvals[:6]],
        },
        "map": {"color_by": "risk", "incidents": True, "workorders": True},
    }


def _analyst(user, now) -> dict:
    health = _health(user)
    weak = (
        health.filter(Q(score__lt=WEAK_HEALTH) | Q(silent=True))
        .select_related("channel__node")
        .order_by("score")
    )
    return {
        "kpis": [
            _kpi(
                "labels",
                "Метки на проверке",
                scope_queryset(
                    FeedbackLabel.objects.filter(status=FeedbackLabel.Status.PENDING), user, "channel__node"
                ).count(),
                hint="из решений диспетчеров",
                color="blue",
                to="/learning",
            ),
            _kpi(
                "silent",
                "Молчат",
                health.filter(silent=True).count(),
                hint="каналы без сообщений",
                color="dark",
                to="/data-health",
            ),
            _kpi(
                "weak",
                "Низкий Data Health",
                health.filter(score__lt=WEAK_HEALTH).count(),
                hint=f"балл ниже {WEAK_HEALTH}",
                color="orange",
                to="/data-health",
            ),
            _kpi(
                "risk",
                "Высокий риск",
                _high_risk(user),
                hint="каналы по прогнозу",
                color="red",
                to="/forecasts",
            ),
        ],
        "lists": {
            "weak_channels": [
                {
                    "channel": h.channel_id,
                    "name": h.channel.name,
                    "node": h.channel.node.name,
                    "score": h.score,
                    "silent": h.silent,
                    "last_seen_at": h.last_seen_at,
                }
                for h in weak[:8]
            ]
        },
        "map": {"color_by": "health", "incidents": False, "workorders": False},
    }


def _technician(user, now) -> dict:
    mine = _orders(user).filter(assignee=user).select_related("node", "created_by").order_by("due_at")
    today_end = timezone.localtime(now).replace(hour=23, minute=59, second=59)
    return {
        "kpis": [
            _kpi(
                "mine",
                "Мои заявки",
                mine.count(),
                hint="назначены мне и не закрыты",
                color="blue",
                to="/workorders",
            ),
            _kpi(
                "in_progress",
                "В работе",
                mine.filter(status=WorkOrder.Status.IN_PROGRESS).count(),
                color="teal",
                to="/workorders",
            ),
            _kpi(
                "today",
                "Срок сегодня",
                mine.filter(due_at__gte=now, due_at__lte=today_end).count(),
                color="orange",
            ),
            _kpi("overdue", "Просрочены", mine.filter(due_at__lt=now).count(), color="red"),
        ],
        "lists": {"my_orders": [_order_row(o, now) for o in mine[:20]]},
        "map": {"color_by": "state", "incidents": False, "workorders": True},
    }


def _observer(user, now) -> dict:
    incidents = _incidents(user)
    health = _health(user)
    return {
        "kpis": [
            _kpi("open", "Открытые карточки", incidents.count(), to="/incidents"),
            _kpi(
                "critical",
                "Высокий и критический",
                incidents.filter(severity__in=HIGH).count(),
                color="red",
                to="/incidents",
            ),
            _kpi(
                "risk",
                "Высокий риск",
                _high_risk(user),
                hint="каналы по прогнозу",
                color="orange",
                to="/forecasts",
            ),
            _kpi(
                "silent",
                "Молчат",
                health.filter(silent=True).count(),
                hint="каналы без сообщений",
                color="dark",
            ),
        ],
        "lists": {},
        "map": {"color_by": "risk", "incidents": True, "workorders": False},
    }


def _admin(user, now) -> dict:
    from apps.accounts.models import User
    from apps.ingestion.models import ImportJob

    week = now - timedelta(days=7)
    jobs = ImportJob.objects.filter(created_at__gte=week)
    data = _observer(user, now)
    data["kpis"] = [
        _kpi("users", "Активные учётные записи", User.objects.filter(is_active=True).count(), to="/teams"),
        _kpi(
            "jobs_running",
            "Загрузки в работе",
            jobs.filter(status__in=[ImportJob.Status.PENDING, ImportJob.Status.RUNNING]).count(),
            color="blue",
            to="/data-import",
        ),
        _kpi(
            "jobs_failed",
            "Ошибки загрузки за неделю",
            jobs.filter(status=ImportJob.Status.FAILED).count(),
            color="red",
            to="/data-import",
        ),
        *data["kpis"][:2],
    ]
    return data


BUILDERS = {
    "technician": _technician,
    "unit_dispatcher": _dispatcher,
    "ods_dispatcher": _dispatcher,
    "head": _head,
    "analyst": _analyst,
    "observer": _observer,
    "admin": _admin,
}


def workspace(user, role: str | None = None) -> dict:
    roles = roles_of(user)
    role = role if role in roles else roles[0]
    now = timezone.now()
    spec = ROLES[Role(role)]
    return {
        "role": role,
        "title": spec.title,
        "description": spec.description,
        "roles": [{"code": r, "title": ROLES[Role(r)].title} for r in roles],
        **BUILDERS[role](user, now),
    }

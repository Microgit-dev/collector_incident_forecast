"""
Учения: отработка всей цепочки на полигоне учебного контура.

Руководитель выбирает сценарий, объект, темп и осложнение, назначает участников — им сразу приходит
уведомление «будут учения» (сценарий не раскрывается). Старт — по кнопке или по времени (celery beat
проверяет назначенные раз в 15 с), досрочная остановка возвращает объект в норму. Карточки, заявки,
эскалации и уведомления во время учений — настоящие, поэтому разбор строится по тем же журналам,
что и рабочая аналитика: кто заметил, кто откликнулся, какое решение, сработала ли эскалация.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.analytics.workspace import roles_of
from apps.audit.models import ActionLog
from apps.incidents.models import Decision, DecisionOutcome, Incident, IncidentEvent
from apps.notifications.services import notify
from apps.topology.models import Node
from apps.topology.selectors import has_global_scope, object_of, objects_under

from .models import Exercise, ExerciseParticipant
from .services import BOT_USERNAME, _picket, reset_object, send_simulator

logger = logging.getLogger(__name__)
REMIND_BEFORE = timedelta(minutes=15)


class ExerciseError(Exception):
    pass


@dataclass(frozen=True)
class ScenarioSpec:
    code: str
    title: str
    description: str
    types: tuple[str, ...]  # какие карточки должны появиться
    brigade: bool  # правильный ответ — выезд или проверка на месте


SCENARIOS: dict[str, ScenarioSpec] = {
    s.code: s
    for s in (
        ScenarioSpec(
            "fire",
            "Пожар",
            "Рост температуры, дым, тепловой извещатель, дым у соседнего пикета",
            ("fire",),
            True,
        ),
        ScenarioSpec(
            "gas", "Загазованность", "Метан у пикета растёт до 0,7 %, затем выше 1 %", ("gas",), True
        ),
        ScenarioSpec(
            "flood",
            "Подтопление",
            "Насосы АНС, датчик затопления, насос затоплен, пропало питание",
            ("flood", "power"),
            True,
        ),
        ScenarioSpec(
            "intrusion",
            "Проникновение",
            "Объект на охране, вскрыт люк, движение, открыта дверь",
            ("intrusion",),
            True,
        ),
        ScenarioSpec(
            "power",
            "Обесточивание",
            "ИБП на батареях, затем все каналы пожарной части разом",
            ("power", "communication", "sensor_failure"),
            False,
        ),
        ScenarioSpec(
            "sensor",
            "Отказ датчика",
            "Дребезг с учащением, служебный код −100, отказ",
            ("sensor_failure", "equipment", "gas"),
            False,
        ),
    )
}

# Осложнение — второй сценарий через заданное время: отказ связи посреди пожара и т. п.
COMPLICATIONS = {
    "comm": "Отказ связи с контроллером (каналы молчат 5 мин)",
    "power": "Обесточивание шкафа пожарной части",
    "sensor": "Отказ соседнего датчика",
}


# ---------- кто может участвовать ----------


def managed_nodes(head) -> Node | None:
    """Зона руководителя; None — весь район. Если руководитель закреплён за частью объекта — весь объект."""
    if has_global_scope(head):
        return None
    scope = head.scope_node
    return (object_of(scope) or scope) if scope is not None else None


def polygon_objects(head) -> list[Node]:
    return list(objects_under(managed_nodes(head)).order_by("name"))


def _sees(user, node: Node) -> bool:
    """Увидит ли сотрудник карточки объекта: глобальная зона или зона — предок объекта или сам объект."""
    if has_global_scope(user):
        return True
    scope = user.scope_node
    return scope is not None and (node.path.startswith(scope.path) or scope.path.startswith(node.path))


def candidates(head, node: Node) -> list[dict]:
    scope = managed_nodes(head)
    qs = (
        User.objects.filter(is_active=True)
        .exclude(username=BOT_USERNAME)
        .select_related("scope_node", "team")
    )
    rows = []
    for user in qs.order_by("last_name", "username"):
        if scope is not None and not (
            (user.scope_node and user.scope_node.path.startswith(scope.path)) or _sees(user, node)
        ):
            continue
        roles = roles_of(user)
        if roles == ["observer"] and not user.groups.exists():
            continue
        rows.append(
            {
                "id": user.pk,
                "name": user.get_full_name() or user.username,
                "username": user.username,
                "roles": roles,
                "team": user.team.name if user.team_id else None,
                "zone": user.scope_node.name if user.scope_node_id else "Все объекты",
                "sees": _sees(user, node),
            }
        )
    return rows


# ---------- жизненный цикл ----------


def _name(user) -> str:
    return (user.get_full_name() or user.username) if user else "—"


def _notify_participants(
    exercise: Exercise, *, title: str, body: str, level: str = "medium", silent_body: str = ""
):
    for p in exercise.participants.select_related("user"):
        text = body + (f"\n\n{silent_body}" if p.silent and silent_body else "")
        notify([p.user], title=title, body=text, level=level, link=f"/exercises/{exercise.pk}")


def _when(exercise: Exercise) -> str:
    if exercise.scheduled_at is None:
        return "по сигналу руководителя"
    return timezone.localtime(exercise.scheduled_at).strftime("%d.%m в %H:%M")


@transaction.atomic
def create(head, data: dict) -> Exercise:
    if settings.CONTOUR != "training":
        raise ExerciseError("Учения проходят в учебном контуре — откройте его")
    scenario = data.get("scenario")
    if scenario not in SCENARIOS:
        raise ExerciseError("Выберите сценарий")
    complication = data.get("complication") or ""
    if complication and complication not in COMPLICATIONS:
        raise ExerciseError("Неизвестное осложнение")
    node = Node.objects.filter(pk=data.get("node")).first()
    if node is None or node not in polygon_objects(head):
        raise ExerciseError("Объект не в вашей зоне")
    ids = {int(i) for i in data.get("participants") or []}
    allowed = {c["id"] for c in candidates(head, node)}
    if not ids:
        raise ExerciseError("Выберите участников")
    if ids - allowed:
        raise ExerciseError("Среди участников есть сотрудники не из вашей зоны")
    silent = {int(i) for i in data.get("silent") or []} & ids
    scheduled_at = data.get("scheduled_at") or None
    if scheduled_at is not None and scheduled_at <= timezone.now():
        raise ExerciseError("Время начала уже прошло")
    speed = float(data.get("speed") or 2)
    if not 0.5 <= speed <= 10:
        raise ExerciseError("Темп — от 0,5 до 10")

    exercise = Exercise.objects.create(
        title=(data.get("title") or "").strip()
        or f"Учения: {SCENARIOS[scenario].title.lower()}, {node.name}",
        scenario=scenario,
        node=node,
        speed=speed,
        complication=complication,
        complication_after_min=int(data.get("complication_after_min") or 3),
        duration_min=max(5, min(int(data.get("duration_min") or 30), 240)),
        briefing=(data.get("briefing") or "").strip(),
        scheduled_at=scheduled_at,
        created_by=head,
    )
    now = timezone.now()
    for user in User.objects.filter(pk__in=ids):
        ExerciseParticipant.objects.create(
            exercise=exercise, user=user, role=roles_of(user)[0], silent=user.pk in silent, notified_at=now
        )
    _notify_participants(
        exercise,
        title=f"Будут учения: {exercise.title}",
        body=f"Начало — {_when(exercise)}. Объект полигона: {node.name}, учебный контур. "
        f"Сценарий заранее не сообщается: работайте с карточками как в обычную смену."
        + (f"\n\nВводная: {exercise.briefing}" if exercise.briefing else ""),
        silent_body="Ваша роль на учениях: не реагируйте на карточки — проверяется, как сработает эскалация "
        "и подхватят ли карточку коллеги.",
    )
    return exercise


def _running_on(node: Node) -> Exercise | None:
    return Exercise.objects.filter(node=node, status=Exercise.Status.RUNNING).first()


@transaction.atomic
def start(exercise: Exercise, by=None) -> Exercise:
    exercise = Exercise.objects.select_for_update().get(pk=exercise.pk)
    if exercise.status != Exercise.Status.SCHEDULED:
        raise ExerciseError("Учения уже начались или закончились")
    busy = _running_on(exercise.node)
    if busy:
        raise ExerciseError(f"На объекте уже идут учения «{busy.title}»")
    node = exercise.node
    exercise.context.update(reset_object(node))
    exercise.status = Exercise.Status.RUNNING
    exercise.started_at = timezone.now()
    exercise.context["started_by"] = by.pk if by else None
    exercise.save()
    if node.external_id:
        send_simulator({"op": "restore", "object": node.external_id, "exercise": exercise.pk})
        send_simulator(
            {
                "op": "scenario",
                "scenario": exercise.scenario,
                "object": node.external_id,
                "picket": _picket(node),
                "speed": exercise.speed,
                "exercise": exercise.pk,
            }
        )
    if exercise.complication:
        from .tasks import exercise_complication

        transaction.on_commit(
            lambda: exercise_complication.apply_async(
                (exercise.pk,), countdown=exercise.complication_after_min * 60
            )
        )
    _notify_participants(
        exercise,
        title=f"Учения начались: {exercise.title}",
        body=f"Объект полигона: {node.name}. Работайте в учебном контуре; карточки появятся в очереди и на схеме.",
        level="high",
    )
    return exercise


def complicate(exercise_id: int) -> bool:
    exercise = Exercise.objects.select_related("node").filter(pk=exercise_id).first()
    if exercise is None or exercise.status != Exercise.Status.RUNNING or not exercise.complication:
        return False
    node = exercise.node
    if node.external_id:
        send_simulator(
            {
                "op": "scenario",
                "scenario": exercise.complication,
                "object": node.external_id,
                "picket": _picket(node),
                "speed": exercise.speed,
                "exercise": exercise.pk,
            }
        )
    exercise.context["complication_at"] = timezone.now().isoformat()
    exercise.save(update_fields=["context"])
    return True


@transaction.atomic
def finish(exercise: Exercise, by=None, *, early: bool = False, reason: str = "") -> Exercise:
    """Завершить (по плану или по кнопке) или прекратить досрочно; назначенные — отменить."""
    exercise = Exercise.objects.select_for_update().select_related("node").get(pk=exercise.pk)
    if exercise.status == Exercise.Status.SCHEDULED:
        exercise.status = Exercise.Status.CANCELLED
        exercise.finished_at = timezone.now()
        exercise.stopped_by = by
        exercise.stop_reason = reason
        exercise.save()
        _notify_participants(
            exercise,
            title=f"Учения отменены: {exercise.title}",
            body=reason or "Руководитель отменил учения.",
        )
        return exercise
    if exercise.status != Exercise.Status.RUNNING:
        raise ExerciseError("Учения не идут")
    exercise.status = Exercise.Status.STOPPED if early else Exercise.Status.FINISHED
    exercise.finished_at = timezone.now()
    exercise.stopped_by = by
    exercise.stop_reason = reason
    exercise.report = build_report(exercise)
    exercise.save()
    if exercise.node.external_id:
        send_simulator({"op": "restore", "object": exercise.node.external_id, "exercise": exercise.pk})
    word = "прекращены досрочно" if early else "завершены"
    _notify_participants(
        exercise,
        title=f"Учения {word}: {exercise.title}",
        body=(f"Причина: {reason}. " if reason else "")
        + f"Объект возвращён в норму. Итог: {exercise.report['score']['passed']} из "
        f"{exercise.report['score']['total']} проверок. Разбор открыт участникам.",
        level="medium",
    )
    return exercise


def tick(now=None) -> dict:
    """Раз в 15 с: старт по таймеру, напоминание за 15 минут, завершение по длительности."""
    now = now or timezone.now()
    started = finished = reminded = 0
    for exercise in Exercise.objects.filter(status=Exercise.Status.SCHEDULED, scheduled_at__lte=now):
        try:
            start(exercise)
            started += 1
        except ExerciseError as exc:
            logger.warning("exercise %s not started: %s", exercise.pk, exc)
    for exercise in Exercise.objects.filter(
        status=Exercise.Status.SCHEDULED, scheduled_at__lte=now + REMIND_BEFORE, scheduled_at__gt=now
    ):
        if not exercise.context.get("reminded"):
            exercise.context["reminded"] = now.isoformat()
            exercise.save(update_fields=["context"])
            _notify_participants(
                exercise,
                title=f"Учения через {max(1, round((exercise.scheduled_at - now).total_seconds() / 60))} мин",
                body=f"{exercise.title}. Начало — {_when(exercise)}, учебный контур.",
            )
            reminded += 1
    for exercise in Exercise.objects.filter(status=Exercise.Status.RUNNING, started_at__isnull=False):
        if exercise.started_at + timedelta(minutes=exercise.duration_min) <= now:
            finish(exercise)
            finished += 1
    return {"started": started, "finished": finished, "reminded": reminded}


# ---------- разбор ----------


def _offset(exercise: Exercise, ts) -> int | None:
    return int((ts - exercise.started_at).total_seconds()) if ts and exercise.started_at else None


def _check(code: str, title: str, ok: bool | None, detail: str = "") -> dict:
    return {"code": code, "title": title, "ok": ok, "detail": detail}


def _mmss(seconds: int | None) -> str:
    if seconds is None:
        return "—"
    return f"{seconds // 60}:{seconds % 60:02d}"


def build_report(exercise: Exercise) -> dict:
    """Хронология, проверки и вклад каждого участника — по карточкам объекта за время учений."""
    if exercise.started_at is None:
        return {}
    spec = SCENARIOS[exercise.scenario]
    end = exercise.finished_at or timezone.now()
    node = exercise.node
    incidents = list(
        Incident.objects.filter(
            node__path__startswith=node.path, opened_at__gte=exercise.started_at, opened_at__lte=end
        )
        .exclude(pk__in=exercise.context.get("closed", []))
        .select_related("first_seen_by", "responder", "assigned_to")
        .order_by("opened_at")
    )
    ids = [i.pk for i in incidents]
    participants = list(exercise.participants.select_related("user"))
    members = {p.user_id: p for p in participants}
    silent = {p.user_id for p in participants if p.silent}

    timeline = [
        {
            "t": 0,
            "kind": "start",
            "text": f"Старт: сценарий «{spec.title}», темп ×{exercise.speed:g}",
            "who": None,
        }
    ]
    if exercise.context.get("complication_at"):
        from datetime import datetime

        at = datetime.fromisoformat(exercise.context["complication_at"])
        timeline.append(
            {
                "t": _offset(exercise, at),
                "kind": "complication",
                "text": f"Осложнение: {COMPLICATIONS.get(exercise.complication, exercise.complication)}",
                "who": None,
            }
        )
    for incident in incidents:
        timeline.append(
            {
                "t": _offset(exercise, incident.opened_at),
                "kind": "opened",
                "text": f"Карточка #{incident.pk}: {incident.get_type_display()} — {incident.title}",
                "who": None,
                "incident": incident.pk,
            }
        )
        if incident.first_seen_at:
            timeline.append(
                {
                    "t": _offset(exercise, incident.first_seen_at),
                    "kind": "seen",
                    "text": f"Первым заметил карточку #{incident.pk}",
                    "who": _name(incident.first_seen_by),
                    "user": incident.first_seen_by_id,
                    "incident": incident.pk,
                }
            )
    events = IncidentEvent.objects.filter(
        incident_id__in=ids,
        kind__in=[
            IncidentEvent.Kind.ACKNOWLEDGED,
            IncidentEvent.Kind.ASSIGNED,
            IncidentEvent.Kind.RELEASED,
            IncidentEvent.Kind.ESCALATED,
            IncidentEvent.Kind.DECISION,
            IncidentEvent.Kind.WORKORDER,
            IncidentEvent.Kind.ACTION_DONE,
        ],
    ).select_related("actor")
    for e in events:
        label = e.get_kind_display()
        # текст события часто уже начинается с его вида («Взят в работу: …») — не повторять
        text = e.text if e.text and e.text.startswith(label) else label + (f" — {e.text}" if e.text else "")
        timeline.append(
            {
                "t": _offset(exercise, e.ts),
                "kind": e.kind,
                "text": f"#{e.incident_id}: {text}",
                "who": _name(e.actor) if e.actor_id else None,
                "user": e.actor_id,
                "incident": e.incident_id,
            }
        )
    from apps.workorders.models import WorkOrder

    orders = list(WorkOrder.objects.filter(incident_id__in=ids).select_related("created_by", "approved_by"))
    order_logs = ActionLog.objects.filter(
        action="workorder.transition",
        object_id__in=[str(o.pk) for o in orders],
        ts__gte=exercise.started_at,
        ts__lte=end,
    ).select_related("user")
    for log in order_logs:
        timeline.append(
            {
                "t": _offset(exercise, log.ts),
                "kind": "workorder",
                "text": f"Заявка: {log.payload.get('status', '')}",
                "who": _name(log.user),
                "user": log.user_id,
            }
        )
    timeline.append(
        {
            "t": _offset(exercise, end),
            "kind": "stop" if exercise.status == Exercise.Status.STOPPED else "end",
            "text": "Прекращены досрочно" + (f": {exercise.stop_reason}" if exercise.stop_reason else "")
            if exercise.status == Exercise.Status.STOPPED
            else "Конец учений",
            "who": _name(exercise.stopped_by) if exercise.stopped_by_id else None,
        }
    )
    timeline.sort(key=lambda r: r["t"] if r["t"] is not None else 0)

    # ---- проверки по главной карточке (первая карточка ожидаемого типа) ----
    main = next((i for i in incidents if i.type in spec.types), incidents[0] if incidents else None)
    decisions = list(
        Decision.objects.filter(incident_id__in=ids).select_related("decided_by").order_by("decided_at")
    )
    checks = [
        _check(
            "detected",
            "Система подняла карточку",
            main is not None,
            f"через {_mmss(_offset(exercise, main.opened_at))}: {main.get_type_display()}"
            if main
            else "карточки нет",
        )
    ]
    if main is not None:
        responded = main.responded_at or main.acknowledged_at
        in_time = responded is not None and (main.ack_deadline is None or responded <= main.ack_deadline)
        checks.append(
            _check(
                "response",
                "Отклик в норматив",
                in_time,
                f"через {_mmss(_offset(exercise, responded))} после старта"
                + (
                    f", норматив — до {_mmss(_offset(exercise, main.ack_deadline))}"
                    if main.ack_deadline
                    else ""
                )
                if responded
                else "никто не откликнулся",
            )
        )
        checks.append(
            _check(
                "participant",
                "Откликнулся участник учений",
                main.responder_id in members and main.responder_id not in silent
                if main.responder_id
                else False,
                _name(main.responder) if main.responder_id else "—",
            )
        )
        main_decisions = [d for d in decisions if d.incident_id == main.pk]
        first_decision = main_decisions[0] if main_decisions else None
        checks.append(
            _check(
                "decision",
                "Принято решение",
                first_decision is not None,
                f"{first_decision.get_outcome_display()} через {_mmss(_offset(exercise, first_decision.decided_at))}"
                if first_decision
                else "решения нет",
            )
        )
        if spec.brigade:
            right = next(
                (
                    d
                    for d in main_decisions
                    if d.outcome in (DecisionOutcome.BRIGADE_DISPATCHED, DecisionOutcome.CHECK_REQUESTED)
                ),
                None,
            )
            checks.append(
                _check(
                    "dispatch",
                    "Направлены бригада или проверка",
                    right is not None,
                    f"{right.get_outcome_display()}, {_name(right.decided_by)}"
                    if right
                    else "физическая угроза требует проверки на месте",
                )
            )
            order = next((o for o in orders if o.incident_id == main.pk), None)
            checks.append(
                _check(
                    "workorder",
                    "Составлена заявка",
                    order is not None,
                    f"№ {order.number}, {order.get_status_display().lower()}" if order else "заявки нет",
                )
            )
            if order is not None and any(p.role == "head" for p in participants):
                checks.append(
                    _check(
                        "approved",
                        "Заявка утверждена руководителем",
                        order.approved_by_id is not None,
                        _name(order.approved_by) if order.approved_by_id else "не утверждена",
                    )
                )
        if silent:
            escalated = any(
                e.kind == IncidentEvent.Kind.ESCALATED and e.incident_id == main.pk for e in events
            )
            picked = main.responder_id is not None and main.responder_id not in silent
            checks.append(
                _check(
                    "silent",
                    "Молчание не осталось без ответа",
                    escalated or picked,
                    ("сработала эскалация" if escalated else "")
                    + (" и " if escalated and picked else "")
                    + (f"карточку подхватил(а) {_name(main.responder)}" if picked else "")
                    or "ни эскалации, ни отклика коллег",
                )
            )

    # ---- участники ----
    views = ActionLog.objects.filter(
        action="incident.view",
        object_id__in=[str(i) for i in ids],
        ts__gte=exercise.started_at,
        ts__lte=end,
    )
    first_view: dict[int, int] = {}
    for log in views.order_by("ts"):
        if log.user_id and log.user_id not in first_view:
            first_view[log.user_id] = _offset(exercise, log.ts)
    people = []
    for p in participants:
        uid = p.user_id
        acts = [r for r in timeline if r.get("user") == uid]
        mine = [d for d in decisions if d.decided_by_id == uid]
        responded = [i for i in incidents if i.responder_id == uid]
        did = bool(acts or mine or responded)
        people.append(
            {
                "user": uid,
                "name": _name(p.user),
                "role": p.role,
                "silent": p.silent,
                "confirmed": p.confirmed_at is not None,
                "first_view": first_view.get(uid),
                "responded": len(responded),
                "first_response": min((_offset(exercise, i.responded_at) for i in responded), default=None),
                "decisions": len(mine),
                "actions": len(acts),
                "workorders": sum(1 for o in orders if o.created_by_id == uid or o.approved_by_id == uid),
                "verdict": (
                    ("выполнил вводную: не вмешивался" if not did else "вмешался, хотя должен был молчать")
                    if p.silent
                    else ("участвовал" if did else "не участвовал")
                ),
            }
        )
    passed = sum(1 for c in checks if c["ok"])
    return {
        "scenario": spec.title,
        "complication": COMPLICATIONS.get(exercise.complication) if exercise.complication else None,
        "duration_s": _offset(exercise, end),
        "incidents": [
            {
                "id": i.pk,
                "type": i.type,
                "type_display": i.get_type_display(),
                "title": i.title,
                "status": i.get_status_display(),
                "opened": _offset(exercise, i.opened_at),
                "responder": _name(i.responder) if i.responder_id else None,
                "responded": _offset(exercise, i.responded_at),
                "escalation_level": i.escalation_level,
            }
            for i in incidents
        ],
        "checks": checks,
        "score": {"passed": passed, "total": len(checks)},
        "people": people,
        "timeline": timeline,
    }


# ---------- выдача ----------


def can_manage(user, exercise: Exercise | None = None) -> bool:
    if not user.has_perm("training.add_exercise"):
        return False
    if exercise is None:
        return True
    scope = managed_nodes(user)
    return scope is None or exercise.node.path.startswith(scope.path)


def serialize(exercise: Exercise, user) -> dict:
    manager = can_manage(user, exercise)
    me = next((p for p in exercise.participants.all() if p.user_id == user.pk), None)
    over = exercise.status in (Exercise.Status.FINISHED, Exercise.Status.STOPPED)
    # сценарий и осложнение — секрет для участников до конца учений
    reveal = manager or over
    data = {
        "id": exercise.pk,
        "title": exercise.title,
        "status": exercise.status,
        "status_display": exercise.get_status_display(),
        "object": exercise.node.name,
        "node": exercise.node_id,
        "scenario": exercise.scenario if reveal else None,
        "scenario_display": SCENARIOS[exercise.scenario].title if reveal else None,
        "complication": exercise.complication if reveal else None,
        "complication_display": COMPLICATIONS.get(exercise.complication)
        if reveal and exercise.complication
        else None,
        "complication_after_min": exercise.complication_after_min if reveal else None,
        "speed": exercise.speed if reveal else None,
        "duration_min": exercise.duration_min,
        "briefing": exercise.briefing,
        "scheduled_at": exercise.scheduled_at,
        "started_at": exercise.started_at,
        "finished_at": exercise.finished_at,
        "ends_at": exercise.started_at + timedelta(minutes=exercise.duration_min)
        if exercise.started_at
        else None,
        "created_by": _name(exercise.created_by),
        "stopped_by": _name(exercise.stopped_by) if exercise.stopped_by_id else None,
        "stop_reason": exercise.stop_reason,
        "manager": manager,
        "me": {"silent": me.silent, "confirmed_at": me.confirmed_at} if me else None,
        "participants": [
            {
                "user": p.user_id,
                "name": _name(p.user),
                "role": p.role,
                "silent": p.silent if manager or over or p.user_id == user.pk else False,
                "confirmed_at": p.confirmed_at,
            }
            for p in exercise.participants.all()
        ],
    }
    if over:
        data["report"] = exercise.report
    elif manager and exercise.status == Exercise.Status.RUNNING:
        data["report"] = build_report(exercise)  # ход учений — руководителю в реальном времени
    return data

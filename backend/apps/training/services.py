"""
Учебные задания: старт урока на объекте полигона, проверка шагов по действиям ученика, итог.

Перед уроком объект полигона приводится в исходное состояние: открытые карточки закрываются, заявки
отменяются, симулятор возвращает каналы в норму и запускает сценарий урока. Команды симулятору идут
через Kafka — единственный канал, общий с полевым контуром.
"""

from __future__ import annotations

import logging
from statistics import median

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.analytics.workspace import roles_of
from apps.assets.models import Channel
from apps.incidents.models import Incident, IncidentEvent
from apps.topology.models import Node

from .lessons import LESSONS, Lesson, lessons_for, visible_steps
from .models import TrainingSession

logger = logging.getLogger(__name__)
BOT_USERNAME = "training.bot"
OPEN = (Incident.Status.NEW, Incident.Status.ACKNOWLEDGED, Incident.Status.IN_PROGRESS)


class TrainingError(Exception):
    pass


def training_bot() -> User:
    """Учебный диспетчер — «вторая сторона» урока (составляет заявку, принимает решение). Войти им нельзя."""
    bot, created = User.objects.get_or_create(
        username=BOT_USERNAME,
        defaults={
            "first_name": "Учебный",
            "last_name": "диспетчер",
            "is_active": False,
            "position": "Бот обучения",
        },
    )
    if created:
        bot.set_unusable_password()
        bot.save(update_fields=["password"])
    return bot


def lesson_node(user) -> Node | None:
    """Объект полигона для урока: объект зоны ответственности ученика, а у районных ролей — первый по алфавиту."""
    step = Node.steplen
    scope = user.scope_node or Node.objects.filter(depth=1).order_by("name").first()
    if scope is None:
        return None
    if scope.depth >= 2:
        return Node.objects.get(path=scope.path[: 2 * step])
    return Node.objects.filter(path__startswith=scope.path, depth=2).order_by("name").first()


def _picket(node: Node) -> float | None:
    pickets = [
        float(p)
        for p in Channel.objects.filter(node__path__startswith=node.path, picket__isnull=False).values_list(
            "picket", flat=True
        )
    ]
    return round(median(pickets)) if pickets else None


def send_simulator(command: dict) -> None:
    """Команда симулятору через Kafka; сбой брокера не должен ронять урок — ученик увидит, что карточки нет."""
    from apps.ingestion.kafka import encode, make_producer

    try:
        producer = make_producer()
        producer.produce(settings.KAFKA["TOPIC_SIM_COMMANDS"], value=encode(command))
        producer.flush(5)
    except Exception:
        logger.exception("simulator command failed: %s", command)


@transaction.atomic
def reset_object(node: Node) -> dict:
    """Исходное состояние объекта: открытые карточки закрыты, незавершённые заявки отменены."""
    from apps.workorders.models import WorkOrder

    now = timezone.now()
    incidents = list(Incident.objects.filter(node__path__startswith=node.path, status__in=OPEN))
    for incident in incidents:
        incident.status = Incident.Status.CLOSED
        incident.resolved_at = incident.resolved_at or now
        incident.save(update_fields=["status", "resolved_at", "updated_at"])
        IncidentEvent.objects.create(
            incident=incident, kind=IncidentEvent.Kind.STATUS, text="Закрыта перед учебным заданием"
        )
    orders = WorkOrder.objects.filter(node__path__startswith=node.path).exclude(
        status__in=[WorkOrder.Status.DONE, WorkOrder.Status.CANCELLED]
    )
    return {
        "closed": [i.pk for i in incidents],
        "workorders": orders.update(status=WorkOrder.Status.CANCELLED),
    }


def start(user, code: str) -> TrainingSession:
    lesson = LESSONS.get(code)
    if lesson is None:
        raise TrainingError("Нет такого урока")
    roles = roles_of(user)
    if not set(lesson.roles) & set(roles):
        raise TrainingError("Урок не для вашей роли")
    if lesson.polygon and settings.CONTOUR != "training":
        raise TrainingError("Задание проходит на полигоне — откройте учебный контур")
    node = lesson_node(user) if lesson.polygon else None
    if lesson.polygon and node is None:
        raise TrainingError("В зоне ответственности нет объекта полигона")

    for active in TrainingSession.objects.filter(user=user, status=TrainingSession.Status.ACTIVE):
        abandon(active)
    role = next((r for r in roles if r in lesson.roles), roles[0])
    session = TrainingSession.objects.create(user=user, lesson=code, role=role, node=node)
    if node is not None:
        session.context.update(reset_object(node))
        if lesson.setup:
            lesson.setup(session)
        if node.external_id and lesson.scenario:
            send_simulator({"op": "restore", "object": node.external_id, "session": session.pk})
            send_simulator(
                {
                    "op": "scenario",
                    "scenario": lesson.scenario,
                    "object": node.external_id,
                    "picket": _picket(node),
                    "speed": lesson.speed,
                    "session": session.pk,
                }
            )
        session.save(update_fields=["context"])
    return session


def evaluate(session: TrainingSession) -> TrainingSession:
    """Шаги по порядку: засчитывается первый невыполненный, если его проверка прошла."""
    if session.status != TrainingSession.Status.ACTIVE:
        return session
    lesson = LESSONS[session.lesson]
    for step in visible_steps(lesson, session.user):
        if step.code in session.steps:
            continue
        if step.check is None or not step.check(session):
            break
        session.steps[step.code] = timezone.now().isoformat()
        if step.on_done:
            step.on_done(session)
    _finish_if_done(session, lesson)
    # проверки могли записать в контекст карточку, заявку или ошибку
    session.save()
    return session


def _finish_if_done(session: TrainingSession, lesson: Lesson) -> bool:
    if all(s.code in session.steps for s in visible_steps(lesson, session.user)):
        session.status = TrainingSession.Status.DONE
        session.finished_at = timezone.now()
        session.context.pop("note", None)
        return True
    return False


def current_step(session: TrainingSession):
    lesson = LESSONS[session.lesson]
    return next((s for s in visible_steps(lesson, session.user) if s.code not in session.steps), None)


def confirm(session: TrainingSession, code: str) -> TrainingSession:
    step = current_step(session)
    if session.status != TrainingSession.Status.ACTIVE or step is None or step.code != code:
        raise TrainingError("Этот шаг сейчас не текущий")
    if step.check is not None:
        raise TrainingError("Шаг засчитывается по действию в системе")
    session.steps[code] = timezone.now().isoformat()
    if step.on_done:
        step.on_done(session)
    _finish_if_done(session, LESSONS[session.lesson])
    session.save()
    return evaluate(session)


def abandon(session: TrainingSession) -> TrainingSession:
    if session.status == TrainingSession.Status.ACTIVE:
        session.status = TrainingSession.Status.ABANDONED
        session.finished_at = timezone.now()
        session.save(update_fields=["status", "finished_at"])
        if session.node and session.node.external_id and LESSONS[session.lesson].scenario:
            send_simulator({"op": "restore", "object": session.node.external_id, "session": session.pk})
    return session


def _route(route: str | None, context: dict) -> str | None:
    if not route:
        return None
    try:
        return route.format(**context)
    except (KeyError, IndexError):
        return None


def serialize(session: TrainingSession) -> dict:
    lesson = LESSONS[session.lesson]
    current = current_step(session) if session.status == TrainingSession.Status.ACTIVE else None
    end = session.finished_at or timezone.now()
    return {
        "id": session.pk,
        "lesson": lesson.code,
        "title": lesson.title,
        "summary": lesson.summary,
        "role": session.role,
        "status": session.status,
        "object": session.node.name if session.node else None,
        "started_at": session.started_at,
        "finished_at": session.finished_at,
        "elapsed_s": int((end - session.started_at).total_seconds()),
        "hints": session.hints,
        "mistakes": session.mistakes,
        "note": session.context.get("note"),
        "steps": [
            {
                "code": s.code,
                "title": s.title,
                "hint": s.hint,
                "route": _route(s.route, session.context),
                "target": s.target,
                "manual": s.check is None,
                "status": "done"
                if s.code in session.steps
                else "current"
                if current and s.code == current.code
                else "pending",
                "done_at": session.steps.get(s.code),
            }
            for s in visible_steps(lesson, session.user)
        ],
    }


def catalog(user) -> list[dict]:
    roles = roles_of(user)
    best: dict[str, TrainingSession] = {}
    for s in TrainingSession.objects.filter(user=user, status=TrainingSession.Status.DONE).order_by(
        "started_at"
    ):
        duration = (s.finished_at - s.started_at).total_seconds()
        if (
            s.lesson not in best
            or duration < (best[s.lesson].finished_at - best[s.lesson].started_at).total_seconds()
        ):
            best[s.lesson] = s
    return [
        {
            "code": lesson.code,
            "title": lesson.title,
            "summary": lesson.summary,
            "minutes": lesson.minutes,
            "steps": len(visible_steps(lesson, user)),
            "polygon": lesson.polygon,
            "available": not lesson.polygon or settings.CONTOUR == "training",
            "best": {
                "finished_at": best[lesson.code].finished_at,
                "elapsed_s": int(
                    (best[lesson.code].finished_at - best[lesson.code].started_at).total_seconds()
                ),
                "mistakes": best[lesson.code].mistakes,
            }
            if lesson.code in best
            else None,
        }
        for lesson in lessons_for(roles)
    ]

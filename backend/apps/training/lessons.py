"""
Уроки по ролям. Урок — сценарий на полигоне (его запускает симулятор) и шаги; шаг засчитывается,
когда в системе появилось нужное действие ученика: открыл карточку, принял её, выбрал причину,
утвердил заявку. Шаг без проверки (check=None) подтверждает сам ученик — это подсказки-экскурсии.

Проверки получают сессию и могут записать в её контекст найденные объекты (карточку, заявку):
следующие шаги работают уже с ними, а маршрут шага подставляет их номера («/incidents/{incident}»).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from django.utils import timezone

from apps.audit.models import ActionLog
from apps.incidents.models import Decision, DecisionCause, DecisionOutcome, Incident, IncidentEvent

DISPATCHERS = ("unit_dispatcher", "ods_dispatcher")
ALL_ROLES = ("unit_dispatcher", "ods_dispatcher", "head", "analyst", "technician", "observer", "admin")


@dataclass(frozen=True)
class Step:
    code: str
    title: str
    hint: str
    route: str | None = None  # куда перейти; {incident}, {workorder} — из контекста
    target: str | None = None  # элемент интерфейса для подсветки (data-tour)
    check: Callable | None = None  # None — подтверждает сам ученик
    on_done: Callable | None = None  # что сделать системе после шага (например, «диспетчер» создаёт заявку)
    perm: str | None = None  # шаг показывается, только если у ученика есть право


@dataclass(frozen=True)
class Lesson:
    code: str
    title: str
    summary: str
    roles: tuple[str, ...]
    minutes: int
    steps: tuple[Step, ...]
    scenario: str | None = None  # сценарий симулятора на объекте урока
    speed: float = 5.0
    polygon: bool = True  # нужен учебный контур; экскурсия проходит и в рабочем
    setup: Callable | None = None  # подготовка объекта (кроме сценария)
    picket: str = "middle"  # где на трассе разыграть сценарий: middle | pump


def _since(session):
    return session.started_at


def _incident(session) -> Incident | None:
    pk = session.context.get("incident")
    return Incident.objects.filter(pk=pk).first() if pk else None


def incident_appeared(*types: str) -> Callable:
    """Карточка нужного типа открылась на объекте урока после его начала."""

    def check(session) -> bool:
        qs = Incident.objects.filter(
            node__path__startswith=session.node.path, opened_at__gte=_since(session)
        ).exclude(pk__in=session.context.get("closed", []))
        if types:
            qs = qs.filter(type__in=types)
        incident = qs.order_by("opened_at").first()
        if incident:
            session.context["incident"] = incident.pk
        return incident is not None

    return check


def incident_viewed(session) -> bool:
    return ActionLog.objects.filter(
        user=session.user,
        action="incident.view",
        object_id=str(session.context.get("incident")),
        ts__gte=_since(session),
    ).exists()


def incident_taken(session) -> bool:
    incident = _incident(session)
    if incident is None:
        return False
    return (
        incident.assigned_to_id == session.user_id
        or IncidentEvent.objects.filter(
            incident=incident,
            kind__in=[IncidentEvent.Kind.ACKNOWLEDGED, IncidentEvent.Kind.ASSIGNED],
            actor=session.user,
        ).exists()
    )


def decided(*, outcomes: tuple[str, ...] = (), cause: str | None = None, why: str = "") -> Callable:
    """
    Решение ученика по карточке урока. Если решение есть, но не то — шаг не засчитывается,
    а ученик видит, что выбрано и почему здесь правильно другое (ошибка учитывается в результате).
    """

    def check(session) -> bool:
        decisions = list(
            Decision.objects.filter(
                incident_id=session.context.get("incident"), decided_by=session.user
            ).order_by("decided_at")
        )
        if not decisions:
            return False
        last = decisions[-1]
        ok = (not outcomes or last.outcome in outcomes) and (cause is None or last.cause == cause)
        if not ok:
            seen = session.context.setdefault("wrong_decisions", [])
            if last.pk not in seen:
                seen.append(last.pk)
                session.mistakes += 1
            chosen = last.get_outcome_display() + (f", «{last.get_cause_display()}»" if last.cause else "")
            session.context["note"] = f"Выбрано: {chosen}. {why} Примите решение ещё раз."
        else:
            session.context.pop("note", None)
        return ok

    return check


def workorder_drafted(session) -> bool:
    from apps.workorders.models import WorkOrder

    order = (
        WorkOrder.objects.filter(incident_id=session.context.get("incident"), created_by=session.user)
        .order_by("created_at")
        .first()
    )
    if order:
        session.context["workorder"] = order.pk
    return order is not None


def workorder_status(*statuses: str, by_approver: bool = False) -> Callable:
    def check(session) -> bool:
        from apps.workorders.models import WorkOrder

        order = WorkOrder.objects.filter(pk=session.context.get("workorder")).first()
        if order is None:
            return False
        if by_approver and order.approved_by_id != session.user_id:
            return False
        return order.status in statuses

    return check


def label_reviewed(session) -> bool:
    from apps.forecasting.models import FeedbackLabel

    return FeedbackLabel.objects.filter(
        incident_id=session.context.get("incident"), reviewed_by=session.user
    ).exists()


# ---------- действия «второй стороны», которых в уроке нет ----------


def bot_drafts_workorder(session) -> None:
    """Для руководителя: учебный диспетчер составил черновик заявки по карточке."""
    from apps.workorders.services import draft_from_incident

    from .services import training_bot

    order = draft_from_incident(_incident(session), training_bot())
    session.context["workorder"] = order.pk


def bot_resolves_incident(session) -> None:
    """Для аналитика: учебный диспетчер устранил отказ дистанционно — метка уходит на проверку."""
    from apps.incidents.models import DecisionReason
    from apps.incidents.services import decide, take

    from .services import training_bot

    bot = training_bot()
    incident = take(_incident(session), bot)
    decide(
        incident,
        bot,
        outcome=DecisionOutcome.RESOLVED,
        reason=DecisionReason.objects.filter(code="resolved-remote").first(),
        comment="Учебное задание: перезапуск контроллера канала",
    )


def assign_order_to_trainee(session) -> None:
    """Для бригады: заявка на насос назначена ученику и передана бригаде (без внешнего help desk)."""
    from datetime import timedelta

    from apps.assets.models import Equipment, EquipmentKind
    from apps.workorders.models import WorkOrder, WorkType
    from apps.workorders.services import next_number

    from .services import training_bot

    pump = (
        Equipment.objects.filter(node__path__startswith=session.node.path, kind=EquipmentKind.PUMP)
        .select_related("node")
        .first()
    )
    order = WorkOrder.objects.create(
        number=next_number(),
        status=WorkOrder.Status.SUBMITTED,
        node=pump.node if pump else session.node,
        equipment=pump,
        work_type=WorkType.PUMP_SERVICE,
        priority="high",
        title=f"Проверка после срабатывания при затоплении: {pump.name if pump else 'насос АНС'}",
        description="Учебная заявка: насос включался при подтоплении, датчик затопления сработал. "
        "Проверить насос и датчик, отметить выполнение.",
        due_at=timezone.now() + timedelta(hours=4),
        assignee=session.user,
        created_by=training_bot(),
    )
    session.context["workorder"] = order.pk


# ---------- уроки ----------

FIRE = Lesson(
    code="dispatcher-fire",
    title="Пожар: от сигнала до решения",
    summary="Симулятор поднимает температуру и дым на трассе. Найти карточку, принять её, решить и составить заявку.",
    roles=DISPATCHERS,
    minutes=7,
    scenario="fire",
    steps=(
        Step(
            "incident",
            "Дождитесь карточки пожара",
            "Через полминуты растёт температура, затем срабатывают дымовые и тепловой извещатели. Карточка "
            "появится в очереди «Требуют действия» и красным треугольником на схеме.",
            route="/workspace",
            target="side",
            check=incident_appeared("fire"),
        ),
        Step(
            "view",
            "Откройте карточку",
            "Щёлкните карточку в очереди или треугольник на схеме: там сигналы, каналы и рекомендованные шаги.",
            route="/workspace",
            target="side",
            check=incident_viewed,
        ),
        Step(
            "take",
            "Возьмите карточку в работу",
            "Кнопка «Взять в работу» закрепляет карточку за вами: коллеги увидят, что ею занимаются, "
            "а эскалация по таймауту остановится.",
            route="/incidents/{incident}",
            target="incident-take",
            check=incident_taken,
        ),
        Step(
            "decide",
            "Примите решение: выезд бригады, что произошло — «Реальное событие»",
            "Дым и тепло подтверждают друг друга у соседних пикетов — это не сбой одного датчика. Выберите "
            "«Выезд бригады» и в поле «Что произошло» — «Реальное событие».",
            route="/incidents/{incident}",
            target="decision",
            check=decided(
                outcomes=(DecisionOutcome.BRIGADE_DISPATCHED,),
                cause=DecisionCause.REAL_EVENT,
                why="Здесь сработали несколько разных извещателей подряд — это реальное событие, нужен выезд.",
            ),
        ),
        Step(
            "workorder",
            "Составьте черновик заявки из карточки",
            "Кнопка «Черновик заявки» заполнит объект, вид работ и срок. Черновик уйдёт руководителю на утверждение.",
            route="/incidents/{incident}",
            target="incident-workorder",
            check=workorder_drafted,
        ),
    ),
)

SENSOR = Lesson(
    code="dispatcher-sensor",
    title="Неисправный датчик — не событие",
    summary="Газовый датчик дребезжит и выдаёт служебный код. Отличить отказ датчика от загазованности и отметить причину.",
    roles=DISPATCHERS,
    minutes=6,
    scenario="sensor",
    steps=(
        Step(
            "incident",
            "Дождитесь карточки по датчику",
            "Датчик несколько раз уходит в «Неисправен» и возвращается, затем присылает код −100.",
            route="/workspace",
            target="side",
            check=incident_appeared(),
        ),
        Step(
            "take",
            "Откройте карточку и возьмите её в работу",
            "Посмотрите сигналы: состояние «неисправность», а не «тревога»; показаний метана выше нормы нет.",
            route="/incidents/{incident}",
            target="incident-take",
            check=incident_taken,
        ),
        Step(
            "decide",
            "Укажите «Что произошло — Неисправность датчика»",
            "Это главная обратная связь для модели: подтверждённый отказ канала попадёт в обучение прогноза "
            "отказов. Решение — выезд бригады или направление проверки.",
            route="/incidents/{incident}",
            target="decision",
            check=decided(
                outcomes=(DecisionOutcome.BRIGADE_DISPATCHED, DecisionOutcome.CHECK_REQUESTED),
                cause=DecisionCause.SENSOR_FAULT,
                why="Сигналы — неисправность и служебный код, метан в норме: это отказ датчика, а не газ.",
            ),
        ),
        Step(
            "workorder",
            "Составьте заявку на замену датчика",
            "Черновик заявки из карточки подставит вид работ «замена датчика».",
            route="/incidents/{incident}",
            target="incident-workorder",
            check=workorder_drafted,
        ),
    ),
)

INTRUSION = Lesson(
    code="dispatcher-intrusion",
    title="Проникновение на объект под охраной",
    summary="Объект на охране, вскрыт люк, движение внутри. Принять карточку и направить проверку.",
    roles=DISPATCHERS,
    minutes=5,
    scenario="intrusion",
    steps=(
        Step(
            "incident",
            "Дождитесь карточки НСД",
            "Объект ставится на охрану, затем открывается люк и срабатывают датчики движения.",
            route="/workspace",
            target="side",
            check=incident_appeared("intrusion"),
        ),
        Step(
            "take",
            "Возьмите карточку в работу",
            "Проверьте в карточке, что контакты сработали при включённой охране — это не работы по наряду.",
            route="/incidents/{incident}",
            target="incident-take",
            check=incident_taken,
        ),
        Step(
            "decide",
            "Направьте проверку",
            "Выберите решение «Направлена проверка» (камеры или обходчик). Причину уточните после проверки.",
            route="/incidents/{incident}",
            target="decision",
            check=decided(
                outcomes=(DecisionOutcome.CHECK_REQUESTED, DecisionOutcome.BRIGADE_DISPATCHED),
                why="При проникновении сначала нужна проверка на месте или по камерам.",
            ),
        ),
    ),
)

HEAD = Lesson(
    code="head-approve",
    title="Заявка по карточке: утвердить и передать",
    summary="Метан растёт выше 1 %. Диспетчер составил заявку — утвердить её и передать в систему заявок.",
    roles=("head",),
    minutes=6,
    scenario="gas",
    steps=(
        Step(
            "incident",
            "Дождитесь карточки загазованности",
            "Метан у пикета растёт до 0,7 %, затем выше 1 %. Карточка появится на схеме, а учебный диспетчер "
            "сразу составит по ней черновик заявки.",
            route="/workspace",
            target="scheme",
            check=incident_appeared("gas"),
            on_done=bot_drafts_workorder,
        ),
        Step(
            "find",
            "Найдите заявку в панели «Заявки на утверждение»",
            "Панель — под схемой рабочего места. Там все черновики диспетчеров вашей зоны.",
            route="/workspace",
            target="approvals",
        ),
        Step(
            "approve",
            "Утвердите заявку",
            "В «Заявки и ТО» → «Заявки» нажмите «Утвердить». Исполнителем автоматически станет бригадир бригады "
            "той зоны, где объект.",
            route="/workorders",
            target="wo-action",
            check=workorder_status("approved", "submitted", "in_progress", "done", by_approver=True),
        ),
        Step(
            "submit",
            "Передайте заявку в систему заявок",
            "Кнопка «Передать в систему заявок» отправит её в help desk; дальше статусы приходят оттуда.",
            route="/workorders",
            target="wo-action",
            check=workorder_status("submitted", "in_progress", "done"),
        ),
    ),
)

ANALYST = Lesson(
    code="analyst-labels",
    title="Метка из решения диспетчера",
    summary="Отказ датчика устранён дистанционно. Проверить метку обучения, которую дало решение, и найти канал в Data Health.",
    roles=("analyst",),
    minutes=5,
    scenario="sensor",
    steps=(
        Step(
            "incident",
            "Дождитесь карточки отказа датчика",
            "Учебный диспетчер сам примет решение «Устранено дистанционно» — из него получится метка на проверку.",
            route="/workspace",
            target="side",
            check=incident_appeared(),
            on_done=bot_resolves_incident,
        ),
        Step(
            "label",
            "Проверьте метку: примите или отклоните",
            "«Обучение и обратная связь» → очередь меток. Метка говорит модели «здесь был отказ канала». "
            "Примите, если решение диспетчера подтверждает отказ.",
            route="/learning",
            target="labels",
            check=label_reviewed,
        ),
        Step(
            "health",
            "Найдите канал в «Здоровье каналов»",
            "Дребезг и служебный код снижают Data Health: так видно, каким каналам нельзя доверять.",
            route="/data-health",
            target="health",
        ),
    ),
)

TECHNICIAN = Lesson(
    code="technician-order",
    title="Исполнение заявки",
    summary="Насосы АНС включились при подтоплении. Найти свою заявку на схеме, взять в работу и отметить выполнение.",
    roles=("technician",),
    minutes=4,
    scenario="flood",
    setup=assign_order_to_trainee,
    steps=(
        Step(
            "find",
            "Найдите свою заявку на схеме",
            "Ромб с синей рамкой на трассе — ваша заявка; наведите на него, чтобы увидеть срок.",
            route="/workspace",
            target="scheme",
        ),
        Step(
            "start",
            "Возьмите заявку в работу",
            "Кнопка «Взять в работу» в панели «Мои заявки» рабочего места или в карточке объекта на карте мониторинга.",
            route="/workspace",
            target="side",
            check=workorder_status("in_progress", "done"),
        ),
        Step(
            "done",
            "Отметьте выполнение",
            "После проверки насоса нажмите «Выполнена».",
            route="/workspace",
            target="side",
            check=workorder_status("done"),
        ),
    ),
)

TOUR = Lesson(
    code="tour",
    title="Знакомство с интерфейсом",
    summary="Короткая экскурсия по рабочему месту вашей роли: счётчики, схема, очередь, меню, уведомления.",
    roles=ALL_ROLES,
    minutes=3,
    polygon=False,
    steps=(
        Step(
            "monitoring",
            "Мониторинг — главный экран",
            "Карта зоны ответственности: ваши объекты цветом режима, чужие — серым. Сверху переключаются режимы "
            "(обстановка, прогноз, датчики, данные, заявки), щелчок по зданию — датчики, карточки и заявки объекта.",
            route="/",
            target="monitoring-map",
        ),
        Step(
            "kpis",
            "Счётчики рабочего места",
            "Что важно вашей роли прямо сейчас. Щелчок по счётчику открывает список.",
            route="/workspace",
            target="kpis",
        ),
        Step(
            "scheme",
            "Схема зоны ответственности",
            "Трасса по пикетам. Цвет участка — риск, качество данных или состояние каналов (зависит от роли); "
            "треугольники — карточки, ромбы — заявки. Щелчок по участку — подробности.",
            route="/workspace",
            target="scheme",
        ),
        Step(
            "side",
            "Ваша очередь",
            "Справа — то, с чем работать первым: очередь карточек, эскалации, проблемные каналы или свои заявки.",
            route="/workspace",
            target="side",
        ),
        Step(
            "nav",
            "Меню разделов",
            "В меню только разделы, доступные вашей роли.",
            route="/workspace",
            target="nav",
        ),
        Step(
            "notifications",
            "Уведомления",
            "Колокольчик: новые карточки, эскалации и изменения заявок в вашей зоне.",
            route="/workspace",
            target="notifications",
        ),
    ),
)

LESSONS: dict[str, Lesson] = {
    lesson.code: lesson for lesson in (TOUR, FIRE, SENSOR, INTRUSION, HEAD, ANALYST, TECHNICIAN)
}


def lessons_for(roles: list[str]) -> list[Lesson]:
    return [lesson for lesson in LESSONS.values() if set(lesson.roles) & set(roles)]


def visible_steps(lesson: Lesson, user) -> list[Step]:
    return [s for s in lesson.steps if not s.perm or user.has_perm(s.perm)]

from django.conf import settings
from django.db import models

from apps.core.models import Catalog, TimeStampedModel
from apps.forecasting.models import RiskLevel


class IncidentType(models.TextChoices):
    SENSOR_FAILURE = "sensor_failure", "Отказ датчика"
    FIRE = "fire", "Пожар / задымление"
    GAS = "gas", "Загазованность"
    FLOOD = "flood", "Подтопление"
    INTRUSION = "intrusion", "Несанкционированный доступ"
    POWER = "power", "Потеря питания"
    EQUIPMENT = "equipment", "Отказ оборудования"
    COMMUNICATION = "communication", "Потеря связи"


class DecisionOutcome(models.TextChoices):
    BRIGADE_DISPATCHED = "brigade_dispatched", "Выезд бригады"
    CHECK_REQUESTED = "check_requested", "Направлена проверка"
    MONITORING = "monitoring", "Мониторинг ситуации"
    FALSE_ALARM = "false_alarm", "Ложное срабатывание"
    CONFIRMED = "confirmed", "Инцидент подтверждён"
    RESOLVED = "resolved", "Устранено"


class DecisionCause(models.TextChoices):
    """Что произошло по мнению диспетчера (ТЗ §12) — главная обратная связь для моделей и аналитики."""

    SENSOR_FAULT = "sensor_fault", "Неисправность датчика"
    COMMUNICATION = "communication", "Потеря связи"
    POWER = "power", "Обесточивание"
    FALSE_ALARM = "false_alarm", "Ложное срабатывание"
    EXTERNAL = "external", "Внешнее воздействие"
    WORKS = "works", "Работы на объекте"
    REAL_EVENT = "real_event", "Реальное событие"
    INSUFFICIENT_DATA = "insufficient_data", "Недостаточно данных"


class DecisionReason(Catalog):
    """Справочник причин решения диспетчера (ТЗ §12, шаг 5)."""

    outcome = models.CharField("вид решения", max_length=32, choices=DecisionOutcome.choices)
    incident_types = models.JSONField("применимо к типам", default=list, blank=True)

    class Meta(Catalog.Meta):
        verbose_name = "причина решения"
        verbose_name_plural = "справочник причин решений"


class EscalationPolicy(TimeStampedModel):
    """Сколько ждать реакции на инцидент данного уровня, прежде чем поднять его выше по вертикали."""

    severity = models.CharField("уровень", max_length=16, choices=RiskLevel.choices, unique=True)
    ack_timeout_minutes = models.PositiveIntegerField("время на реакцию, мин")
    max_level = models.PositiveSmallIntegerField("макс. уровней эскалации", default=3)
    repeat_notify_minutes = models.PositiveIntegerField("повтор уведомления, мин", default=5)

    class Meta:
        verbose_name = "политика эскалации"
        verbose_name_plural = "политики эскалации"

    def __str__(self):
        return f"{self.get_severity_display()}: {self.ack_timeout_minutes} мин"


class Incident(TimeStampedModel):
    """
    Карточка, с которой работает диспетчер. Группирует алерты (каскад «десятки каналов
    объекта ушли в Неисправен за одну секунду» = один инцидент), имеет владельца
    (закрепление = блокировка от параллельной работы) и уровень эскалации.
    """

    class Status(models.TextChoices):
        NEW = "new", "Новый"
        ACKNOWLEDGED = "acknowledged", "Принят"
        IN_PROGRESS = "in_progress", "В работе"
        RESOLVED = "resolved", "Решён"
        CLOSED = "closed", "Закрыт"

    OPEN_STATUSES = (Status.NEW, Status.ACKNOWLEDGED, Status.IN_PROGRESS)

    type = models.CharField("тип", max_length=32, choices=IncidentType.choices, db_index=True)
    severity = models.CharField("уровень", max_length=16, choices=RiskLevel.choices, db_index=True)
    status = models.CharField(
        "статус", max_length=16, choices=Status.choices, default=Status.NEW, db_index=True
    )
    is_forecast = models.BooleanField(
        "прогнозный", default=False, help_text="Предупреждение о риске, а не факт"
    )
    node = models.ForeignKey(
        "topology.Node", verbose_name="объект", on_delete=models.PROTECT, related_name="incidents"
    )
    responsible_node = models.ForeignKey(
        "topology.Node",
        verbose_name="ответственный уровень",
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Узел вертикали, который сейчас отвечает за реакцию; поднимается при эскалации",
    )
    title = models.CharField("заголовок", max_length=255)
    description = models.TextField("описание", blank=True)
    probability = models.FloatField("вероятность", null=True, blank=True)
    horizon_hours = models.PositiveSmallIntegerField("горизонт, ч", null=True, blank=True)
    opened_at = models.DateTimeField("открыт", db_index=True)
    ack_deadline = models.DateTimeField("реакция до", null=True, blank=True)
    acknowledged_at = models.DateTimeField("принят", null=True, blank=True)
    resolved_at = models.DateTimeField("решён", null=True, blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="в работе у",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_incidents",
    )
    escalation_level = models.PositiveSmallIntegerField("уровень эскалации", default=0)

    # Эпизод: сколько сигналов и каналов склеено в карточку, первый и последний сигнал
    contour = models.CharField(
        "контур риска",
        max_length=16,
        choices=[("physical", "Физический"), ("technical", "Технический")],
        default="technical",
        db_index=True,
    )
    signals_count = models.PositiveIntegerField("сигналов", default=0)
    channels_count = models.PositiveIntegerField("каналов", default=0)
    first_signal_at = models.DateTimeField("первый сигнал", null=True, blank=True)
    last_signal_at = models.DateTimeField("последний сигнал", null=True, blank=True, db_index=True)
    # [{"code", "title", "weight", "evidence": [...]}] — первые три, веса в сумме 1
    hypotheses = models.JSONField("гипотезы первопричины", default=list, blank=True)
    # [{"code", "title", "done", "done_by", "done_at"}]
    actions = models.JSONField("следующие действия", default=list, blank=True)
    priority = models.FloatField("операционный приоритет", default=0, db_index=True)
    priority_factors = models.JSONField("составляющие приоритета", default=dict, blank=True)
    data_confidence = models.FloatField("уверенность данных (средний балл)", null=True, blank=True)
    # Карточка из эмуляции смены (демонстрация аналитики): в метки обучения не попадает
    is_emulated = models.BooleanField("эмуляция", default=False, db_index=True)

    class Meta:
        verbose_name = "инцидент"
        verbose_name_plural = "инциденты"
        ordering = ("-opened_at",)
        permissions = [
            ("decide_incident", "Принимать решение по инциденту"),
            ("escalate_incident", "Эскалировать инцидент"),
            ("takeover_incident", "Забирать инцидент у другого диспетчера"),
        ]

    def __str__(self):
        return f"#{self.pk} {self.title}"


class Alert(models.Model):
    """Отдельный сигнал: прогноз выше порога, правило по телеметрии или ручной ввод."""

    class Source(models.TextChoices):
        FORECAST = "forecast", "Прогноз"
        RULE = "rule", "Правило"
        MANUAL = "manual", "Вручную"
        EXTERNAL = "external", "Внешняя система"

    incident = models.ForeignKey(
        Incident,
        verbose_name="инцидент",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="alerts",
    )
    source = models.CharField("источник", max_length=16, choices=Source.choices)
    type = models.CharField("тип", max_length=32, choices=IncidentType.choices)
    severity = models.CharField("уровень", max_length=16, choices=RiskLevel.choices)
    node = models.ForeignKey(
        "topology.Node", verbose_name="объект", on_delete=models.PROTECT, related_name="alerts"
    )
    channel = models.ForeignKey(
        "assets.Channel",
        verbose_name="канал",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="alerts",
    )
    prediction = models.ForeignKey(
        "forecasting.Prediction",
        verbose_name="прогноз",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="alerts",
    )
    raised_at = models.DateTimeField("время", db_index=True)
    title = models.CharField("заголовок", max_length=255)
    details = models.JSONField("детали", default=dict, blank=True)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    acknowledged_at = models.DateTimeField("квитирован", null=True, blank=True)

    class Meta:
        verbose_name = "алерт"
        verbose_name_plural = "алерты"
        ordering = ("-raised_at",)
        permissions = [("acknowledge_alert", "Квитировать алерты")]

    def __str__(self):
        return self.title


class Decision(models.Model):
    """Решение диспетчера — источник обратной связи для оценки прогнозов и дообучения."""

    incident = models.ForeignKey(
        Incident, verbose_name="инцидент", on_delete=models.CASCADE, related_name="decisions"
    )
    outcome = models.CharField("решение", max_length=32, choices=DecisionOutcome.choices)
    reason = models.ForeignKey(
        DecisionReason, verbose_name="причина", null=True, blank=True, on_delete=models.PROTECT
    )
    comment = models.TextField("комментарий", blank=True)
    cause = models.CharField("что произошло", max_length=32, choices=DecisionCause.choices, blank=True)
    forecast_useful = models.BooleanField("прогноз помог", null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="кто", on_delete=models.PROTECT, related_name="+"
    )
    decided_at = models.DateTimeField("когда", auto_now_add=True)

    class Meta:
        verbose_name = "решение"
        verbose_name_plural = "решения"
        ordering = ("-decided_at",)

    def __str__(self):
        return f"{self.get_outcome_display()} по #{self.incident_id}"


class IncidentEvent(models.Model):
    """Хронология карточки: кто и что делал — видна всей цепочке командования."""

    class Kind(models.TextChoices):
        OPENED = "opened", "Открыт"
        ALERT_ATTACHED = "alert_attached", "Добавлен сигнал"
        TYPE_CHANGED = "type_changed", "Уточнён тип"
        ACTION_DONE = "action_done", "Выполнен шаг"
        ACKNOWLEDGED = "acknowledged", "Принят"
        ASSIGNED = "assigned", "Взят в работу"
        RELEASED = "released", "Освобождён"
        ESCALATED = "escalated", "Эскалирован"
        DECISION = "decision", "Решение"
        WORKORDER = "workorder", "Заявка"
        STATUS = "status", "Смена статуса"
        COMMENT = "comment", "Комментарий"

    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name="events")
    ts = models.DateTimeField(auto_now_add=True, db_index=True)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    text = models.CharField(max_length=512, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("ts",)

    def __str__(self):
        return f"{self.get_kind_display()}: {self.text}"

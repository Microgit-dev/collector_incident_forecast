from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class ForecastTask(models.TextChoices):
    SENSOR_FAILURE = "sensor_failure", "Отказ датчика"
    GAS = "gas", "Загазованность"
    FLOOD = "flood", "Подтопление"
    FIRE = "fire", "Пожар"
    INTRUSION = "intrusion", "Несанкционированный доступ"


class RiskLevel(models.TextChoices):
    LOW = "low", "Низкий"
    MEDIUM = "medium", "Средний"
    HIGH = "high", "Высокий"
    CRITICAL = "critical", "Критический"


class MLModel(TimeStampedModel):
    """Версия прогнозной модели в реестре. Активна одна версия на задачу."""

    class Status(models.TextChoices):
        TRAINING = "training", "Обучается"
        READY = "ready", "Готова"
        ACTIVE = "active", "Активна"
        ARCHIVED = "archived", "В архиве"
        FAILED = "failed", "Ошибка"

    task = models.CharField("задача", max_length=32, choices=ForecastTask.choices)
    version = models.CharField("версия", max_length=32)
    algorithm = models.CharField("алгоритм", max_length=64, default="lightgbm")
    horizon_hours = models.PositiveSmallIntegerField("горизонт, ч", default=24)
    status = models.CharField("статус", max_length=16, choices=Status.choices, default=Status.TRAINING)
    artifact_path = models.CharField("артефакт", max_length=512, blank=True)
    features = models.JSONField("признаки", default=list, blank=True)
    params = models.JSONField("гиперпараметры", default=dict, blank=True)
    # precision, recall, f1, pr_auc, порог, период валидации — для экспертной проверки
    metrics = models.JSONField("метрики на валидации", default=dict, blank=True)
    train_period = models.JSONField("период обучения", default=dict, blank=True)
    notes = models.TextField("методика / комментарий", blank=True)

    class Meta:
        verbose_name = "модель"
        verbose_name_plural = "реестр моделей"
        constraints = [
            models.UniqueConstraint(fields=["task", "version"], name="uniq_model_version"),
            models.UniqueConstraint(
                fields=["task"], condition=models.Q(status="active"), name="one_active_model_per_task"
            ),
        ]
        permissions = [("retrain_model", "Запускать дообучение моделей")]

    def __str__(self):
        return f"{self.get_task_display()} v{self.version}"


class RiskPolicy(TimeStampedModel):
    """Настраиваемые пороги перевода вероятности в уровень риска и в алерт — по задаче."""

    task = models.CharField("задача", max_length=32, choices=ForecastTask.choices, unique=True)
    medium_threshold = models.FloatField("порог «средний»", default=0.3)
    high_threshold = models.FloatField("порог «высокий»", default=0.6)
    critical_threshold = models.FloatField("порог «критический»", default=0.85)
    alert_from_level = models.CharField(
        "создавать алерт от уровня", max_length=16, choices=RiskLevel.choices, default=RiskLevel.HIGH
    )
    horizon_hours = models.PositiveSmallIntegerField("горизонт прогноза, ч", default=24)
    enabled = models.BooleanField("включено", default=True)

    class Meta:
        verbose_name = "политика риска"
        verbose_name_plural = "политики риска"

    def __str__(self):
        return self.get_task_display()

    def level_for(self, probability: float) -> str:
        if probability >= self.critical_threshold:
            return RiskLevel.CRITICAL
        if probability >= self.high_threshold:
            return RiskLevel.HIGH
        if probability >= self.medium_threshold:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW


class Prediction(models.Model):
    """
    Журнал прогнозов (ТЗ §10): что, где, с какой вероятностью и на какой горизонт предсказано,
    чем объясняется и чем закончилось (outcome заполняется по решению диспетчера или по факту).
    """

    class Outcome(models.TextChoices):
        PENDING = "pending", "Ожидает"
        CONFIRMED = "confirmed", "Подтвердился"
        NOT_CONFIRMED = "not_confirmed", "Не подтвердился"
        PREVENTED = "prevented", "Предотвращён"

    task = models.CharField("задача", max_length=32, choices=ForecastTask.choices, db_index=True)
    model = models.ForeignKey(MLModel, verbose_name="модель", null=True, on_delete=models.SET_NULL)
    node = models.ForeignKey(
        "topology.Node", verbose_name="объект", on_delete=models.CASCADE, related_name="predictions"
    )
    channel = models.ForeignKey(
        "assets.Channel",
        verbose_name="канал",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="predictions",
    )
    issued_at = models.DateTimeField("сформирован", db_index=True)
    horizon_hours = models.PositiveSmallIntegerField("горизонт, ч")
    valid_until = models.DateTimeField("действует до")
    probability = models.FloatField("вероятность")
    risk_level = models.CharField("уровень риска", max_length=16, choices=RiskLevel.choices, db_index=True)
    # [{"feature": "...", "title": "...", "value": ..., "contribution": ...}] + описательные факторы
    factors = models.JSONField("факторы риска", default=list, blank=True)
    summary = models.TextField("пояснение", blank=True)
    outcome = models.CharField("результат", max_length=16, choices=Outcome.choices, default=Outcome.PENDING)
    outcome_at = models.DateTimeField("результат зафиксирован", null=True, blank=True)
    # Бэктест — прогноз, выпущенный задним числом по истории (проверка модели, демо журнала):
    # по нему не создаются инциденты
    is_backtest = models.BooleanField("бэктест", default=False, db_index=True)

    class Meta:
        verbose_name = "прогноз"
        verbose_name_plural = "журнал прогнозов"
        ordering = ("-issued_at",)
        indexes = [models.Index(fields=["task", "risk_level", "-issued_at"])]

    def __str__(self):
        return f"{self.get_task_display()} {self.probability:.0%} ({self.issued_at:%Y-%m-%d %H:%M})"


class TrainingRun(TimeStampedModel):
    """Запуск обучения/дообучения (ТЗ §8: модуль дообучения на новых данных)."""

    class Status(models.TextChoices):
        PENDING = "pending", "В очереди"
        RUNNING = "running", "Выполняется"
        DONE = "done", "Завершён"
        FAILED = "failed", "Ошибка"

    task = models.CharField("задача", max_length=32, choices=ForecastTask.choices)
    status = models.CharField("статус", max_length=16, choices=Status.choices, default=Status.PENDING)
    params = models.JSONField("параметры", default=dict, blank=True)
    result_model = models.ForeignKey(
        MLModel, verbose_name="результат", null=True, blank=True, on_delete=models.SET_NULL
    )
    log = models.TextField("журнал", blank=True)
    progress = models.FloatField("прогресс, %", default=0)
    stage = models.CharField("этап", max_length=128, blank=True)
    started_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    finished_at = models.DateTimeField("завершён", null=True, blank=True)

    class Meta:
        verbose_name = "запуск обучения"
        verbose_name_plural = "запуски обучения"
        ordering = ("-created_at",)


class ChannelRisk(models.Model):
    """Текущий прогноз по каналу (перезаписывается каждым циклом): схема, карточка объекта, приоритет."""

    channel = models.ForeignKey("assets.Channel", on_delete=models.CASCADE, related_name="risks")
    task = models.CharField("задача", max_length=32, choices=ForecastTask.choices)
    as_of = models.DateTimeField("на момент")
    probability = models.FloatField("вероятность")
    risk_level = models.CharField("уровень риска", max_length=16, choices=RiskLevel.choices, db_index=True)
    factors = models.JSONField("факторы риска", default=list, blank=True)
    model = models.ForeignKey(MLModel, verbose_name="модель", null=True, on_delete=models.SET_NULL)

    class Meta:
        verbose_name = "риск канала"
        verbose_name_plural = "риски каналов"
        constraints = [models.UniqueConstraint(fields=["channel", "task"], name="uniq_channel_risk")]

    def __str__(self):
        return f"{self.channel_id}: {self.probability:.0%}"


class RiskSnapshot(models.Model):
    """Снимок риска объекта за цикл прогноза — ряд для графика и динамики риска на схеме."""

    node = models.ForeignKey("topology.Node", on_delete=models.CASCADE, related_name="risk_snapshots")
    task = models.CharField("задача", max_length=32, choices=ForecastTask.choices)
    as_of = models.DateTimeField("на момент", db_index=True)
    max_probability = models.FloatField("максимальная вероятность по каналам")
    expected_failures = models.FloatField("ожидаемое число отказов за горизонт")
    channels_total = models.PositiveIntegerField("каналов оценено")
    channels_at_risk = models.PositiveIntegerField("каналов с риском от среднего")
    risk_level = models.CharField("уровень риска", max_length=16, choices=RiskLevel.choices)

    class Meta:
        verbose_name = "снимок риска объекта"
        verbose_name_plural = "снимки риска объектов"
        ordering = ("-as_of",)
        indexes = [models.Index(fields=["node", "task", "-as_of"])]
        constraints = [models.UniqueConstraint(fields=["node", "task", "as_of"], name="uniq_risk_snapshot")]

    def __str__(self):
        return f"{self.node_id}@{self.as_of:%Y-%m-%d %H:%M}: {self.risk_level}"


class ChannelHealth(models.Model):
    """
    Data Health Score канала (0–100): насколько данным канала можно доверять.
    Низкий балл снижает уверенность прогноза и сам по себе — повод для проверки канала.
    """

    channel = models.OneToOneField(
        "assets.Channel", primary_key=True, on_delete=models.CASCADE, related_name="health"
    )
    computed_at = models.DateTimeField("рассчитан")
    score = models.PositiveSmallIntegerField("балл", db_index=True)
    # completeness, freshness, technical, stability, consistency — каждый 0..1
    components = models.JSONField("составляющие", default=dict)
    periodic = models.BooleanField("периодический канал", default=False)
    expected_interval_s = models.PositiveIntegerField("ожидаемый интервал, с", null=True, blank=True)
    last_seen_at = models.DateTimeField("последнее сообщение", null=True, blank=True)
    silent = models.BooleanField("молчит", default=False, db_index=True)
    silent_since = models.DateTimeField("молчит с", null=True, blank=True)

    class Meta:
        verbose_name = "качество данных канала"
        verbose_name_plural = "качество данных каналов"

    def __str__(self):
        return f"{self.channel_id}: {self.score}"


# ---------- обратная связь диспетчеров и управление обучением ----------


class FeedbackEffect(models.TextChoices):
    POSITIVE = "positive", "Подтверждает отказ датчика"
    NEGATIVE = "negative", "Не отказ датчика"
    EXCLUDE = "exclude", "Исключить из обучения"
    IGNORE = "ignore", "Не влияет на обучение"


class FeedbackRule(TimeStampedModel):
    """
    Как причина решения диспетчера превращается в метку для обучения. Настраивает аналитик:
    правило можно выключить, поменять эффект и вес, включить ручную проверку каждой метки.
    """

    code = models.CharField("код причины", max_length=64, unique=True)
    title = models.CharField("причина", max_length=255)
    effect = models.CharField("эффект для обучения", max_length=16, choices=FeedbackEffect.choices)
    weight = models.FloatField("вес метки", default=1.0, help_text="во сколько раз пример важнее обычного")
    auto_accept = models.BooleanField("принимать без проверки", default=False)
    enabled = models.BooleanField("включено", default=True)
    description = models.TextField("обоснование", blank=True)

    class Meta:
        verbose_name = "правило разметки"
        verbose_name_plural = "правила разметки"
        ordering = ("code",)

    def __str__(self):
        return self.title


class FeedbackLabel(TimeStampedModel):
    """Метка обучения из решения диспетчера: канал, дата отказа, эффект, статус проверки аналитиком."""

    class Status(models.TextChoices):
        PENDING = "pending", "На проверке"
        ACCEPTED = "accepted", "Принята"
        REJECTED = "rejected", "Отклонена"

    task = models.CharField(
        "задача", max_length=32, choices=ForecastTask.choices, default=ForecastTask.SENSOR_FAILURE
    )

    class Source(models.TextChoices):
        DECISION = "decision", "Решение диспетчера"
        EMULATED = "emulated", "Эмуляция для демонстрации"

    source = models.CharField("источник", max_length=16, choices=Source.choices, default=Source.DECISION)
    channel = models.ForeignKey(
        "assets.Channel", verbose_name="канал", on_delete=models.CASCADE, related_name="+"
    )
    label_date = models.DateField("дата события", db_index=True)
    effect = models.CharField("эффект", max_length=16, choices=FeedbackEffect.choices)
    weight = models.FloatField("вес", default=1.0)
    status = models.CharField(
        "статус", max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    rule = models.ForeignKey(
        FeedbackRule, verbose_name="правило", null=True, blank=True, on_delete=models.SET_NULL
    )
    decision = models.ForeignKey(
        "incidents.Decision",
        verbose_name="решение",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="labels",
    )
    incident = models.ForeignKey(
        "incidents.Incident",
        verbose_name="инцидент",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="+",
    )
    prediction = models.ForeignKey(
        Prediction, verbose_name="прогноз", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="диспетчер",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="проверил",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    reviewed_at = models.DateTimeField("проверено", null=True, blank=True)
    review_comment = models.CharField("комментарий аналитика", max_length=512, blank=True)
    # Заполняется при обучении: сколько строк выборки изменила метка и в какой версии модели
    rows_affected = models.PositiveIntegerField("строк выборки изменено", default=0)
    last_used_model = models.ForeignKey(
        MLModel,
        verbose_name="учтена в модели",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        verbose_name = "метка обратной связи"
        verbose_name_plural = "метки обратной связи"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=["decision", "channel"], name="uniq_label_per_decision_channel")
        ]
        permissions = [("review_feedback", "Проверять разметку диспетчеров и управлять обучением")]

    def __str__(self):
        return f"{self.channel_id}@{self.label_date}: {self.effect}"


class LearningSettings(models.Model):
    """Настройки дообучения (одна запись): что учитывать и когда переобучать."""

    use_feedback = models.BooleanField("учитывать разметку диспетчеров", default=True)
    retrain_weekly = models.BooleanField("переобучать раз в неделю", default=True)
    auto_activate = models.BooleanField(
        "автоматически активировать лучшую версию",
        default=True,
        help_text="новая версия заменяет действующую, только если не хуже неё на той же валидации",
    )
    retrain_on_degradation = models.BooleanField("переобучать при деградации", default=False)
    degradation_ratio = models.FloatField(
        "порог деградации",
        default=0.6,
        help_text="реализованная точность ниже этой доли от ожидаемой — тревога",
    )
    degradation_window_days = models.PositiveSmallIntegerField("окно контроля, сут", default=14)
    degradation_min_resolved = models.PositiveSmallIntegerField("минимум прогнозов с исходом", default=30)
    horizon_hours = models.PositiveSmallIntegerField("горизонт планового переобучения, ч", default=24)
    last_check = models.JSONField("последняя проверка деградации", default=dict, blank=True)

    class Meta:
        verbose_name = "настройки дообучения"
        verbose_name_plural = "настройки дообучения"

    def __str__(self):
        return "Настройки дообучения"

    @classmethod
    def load(cls) -> "LearningSettings":
        return cls.objects.get_or_create(pk=1)[0]

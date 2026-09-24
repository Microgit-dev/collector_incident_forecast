from django.db import models

from apps.core.models import TimeStampedModel

from .domain.engine import State, ValueKind


class SensorProfile(TimeStampedModel):
    """
    Профиль датчика: как интерпретировать сырые значения данного класса устройств.
    Новый производитель/формат = новый профиль в админке, без изменения кода.
    """

    code = models.SlugField("код", max_length=64, unique=True)
    name = models.CharField("название", max_length=255)
    value_kind = models.CharField("тип значений", max_length=16, choices=[(v, v) for v in ValueKind])
    unit = models.CharField("единица измерения", max_length=32, blank=True)
    valid_min = models.FloatField("мин. допустимое", null=True, blank=True)
    valid_max = models.FloatField("макс. допустимое", null=True, blank=True)
    drift_tolerance = models.FloatField(
        "допуск дрейфа нуля",
        null=True,
        blank=True,
        help_text="Значения чуть ниже минимума считаются дрейфом (нужна калибровка), а не отказом",
    )
    warn_threshold = models.FloatField("порог предупреждения", null=True, blank=True)
    alarm_threshold = models.FloatField("порог тревоги", null=True, blank=True)
    direction = models.CharField(
        "направление порога",
        max_length=8,
        default="above",
        choices=[("above", "рост"), ("below", "падение")],
    )
    sentinels = models.JSONField("служебные значения (= неисправность)", default=list, blank=True)
    expected_interval_s = models.PositiveIntegerField(
        "ожидаемый интервал между сообщениями, с",
        default=3600,
        help_text="Для выявления «молчания» канала: отсутствие данных дольше N интервалов = подозрение на отказ",
    )
    silence_factor = models.PositiveSmallIntegerField("множитель молчания", default=24)
    description = models.TextField("описание", blank=True)

    class Meta:
        verbose_name = "профиль датчика"
        verbose_name_plural = "профили датчиков"
        ordering = ("name",)

    def __str__(self):
        return self.name


class StateRule(TimeStampedModel):
    """Правило сопоставления текстового значения каноническому состоянию. profile=NULL — глобальное."""

    profile = models.ForeignKey(
        SensorProfile,
        verbose_name="профиль",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="rules",
    )
    pattern = models.CharField("значение / регулярное выражение", max_length=255)
    is_regex = models.BooleanField("регулярное выражение", default=False)
    state = models.CharField("каноническое состояние", max_length=16, choices=[(s, s) for s in State])
    facet = models.CharField(
        "аспект",
        max_length=32,
        default="primary",
        help_text="Составные устройства пишут несколько аспектов одновременно: основной, питание, охрана…",
    )
    guarded = models.BooleanField(
        "тревога только под охраной",
        default=False,
        help_text="Если источник не пометил событие тревожным, это рабочая активность, а не тревога",
    )
    priority = models.PositiveSmallIntegerField("приоритет", default=100)

    class Meta:
        verbose_name = "правило состояния"
        verbose_name_plural = "правила состояний"
        ordering = ("priority", "id")

    def __str__(self):
        return f"{self.pattern} → {self.state}"

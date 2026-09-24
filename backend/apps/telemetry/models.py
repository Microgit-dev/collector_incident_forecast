from django.db import models

from apps.normalization.domain.engine import Quality, State

STATE_CHOICES = [(s.value, s.value) for s in State]
QUALITY_CHOICES = [(q.value, q.value) for q in Quality]


class Reading(models.Model):
    """
    Нормализованное показание канала — оперативный контур (ТЗ §13).

    Физически это hypertable TimescaleDB, секционированная по ts (миграция 0002), со сжатием
    старых чанков. Первичный ключ составной и включает ts — этого требует TimescaleDB.
    FK без ограничения в БД: вставка идёт батчами из консьюмера Kafka, и проверка FK на
    каждую строку дороже, чем её польза.
    """

    pk = models.CompositePrimaryKey("ts", "event_id")
    ts = models.DateTimeField("время")
    event_id = models.BigIntegerField("ид_события")
    channel = models.ForeignKey(
        "assets.Channel",
        verbose_name="канал",
        on_delete=models.DO_NOTHING,
        db_constraint=False,
        related_name="+",
    )
    raw_value = models.CharField("сырое значение", max_length=255, blank=True)
    raw_alarm = models.BooleanField("тревожное (по источнику)", null=True)
    numeric = models.FloatField("числовое значение", null=True)
    state = models.CharField("состояние", max_length=16, choices=STATE_CHOICES)
    facet = models.CharField("аспект", max_length=32, default="primary")
    quality = models.CharField("качество", max_length=24, choices=QUALITY_CHOICES, default=Quality.OK.value)

    class Meta:
        verbose_name = "показание"
        verbose_name_plural = "показания"
        indexes = [models.Index(fields=["channel", "-ts"], name="reading_channel_ts")]

    def __str__(self):
        return f"{self.channel_id}@{self.ts:%Y-%m-%d %H:%M:%S}: {self.state}"


class ChannelState(models.Model):
    """Последнее известное состояние каждого аспекта канала — для дашборда и правил."""

    channel = models.ForeignKey("assets.Channel", on_delete=models.CASCADE, related_name="states")
    facet = models.CharField("аспект", max_length=32, default="primary")
    state = models.CharField("состояние", max_length=16, choices=STATE_CHOICES)
    numeric = models.FloatField("числовое значение", null=True, blank=True)
    raw_value = models.CharField("сырое значение", max_length=255, blank=True)
    changed_at = models.DateTimeField("состояние с")
    last_seen_at = models.DateTimeField("последнее сообщение", db_index=True)

    class Meta:
        verbose_name = "состояние канала"
        verbose_name_plural = "состояния каналов"
        constraints = [models.UniqueConstraint(fields=["channel", "facet"], name="uniq_channel_facet")]

    def __str__(self):
        return f"{self.channel_id}/{self.facet}: {self.state}"


class ChannelDaily(models.Model):
    """
    Суточная витрина по каналу за всю историю (ТЗ §13, аналитический контур).

    Сырые показания всех лет в БД не держим — это сотни миллионов строк; они лежат в Parquet
    (архив для обучения). Витрина заполняется из архива при импорте и ежесуточно из hypertable.
    """

    pk = models.CompositePrimaryKey("day", "channel")
    day = models.DateField("сутки")
    channel = models.ForeignKey(
        "assets.Channel",
        verbose_name="канал",
        on_delete=models.DO_NOTHING,
        db_constraint=False,
        related_name="+",
    )
    readings = models.PositiveIntegerField("показаний")
    normal = models.PositiveIntegerField("норма", default=0)
    warnings = models.PositiveIntegerField("предупреждений", default=0)
    alarms = models.PositiveIntegerField("тревог", default=0)
    faults = models.PositiveIntegerField("неисправностей", default=0)
    power_losses = models.PositiveIntegerField("потерь питания", default=0)
    unknowns = models.PositiveIntegerField("неопределённых", default=0)
    events = models.PositiveIntegerField("рабочих событий", default=0)
    invalid = models.PositiveIntegerField("невалидных значений", default=0)
    numeric_avg = models.FloatField("среднее", null=True)
    numeric_min = models.FloatField("минимум", null=True)
    numeric_max = models.FloatField("максимум", null=True)
    first_ts = models.DateTimeField("первое сообщение")
    last_ts = models.DateTimeField("последнее сообщение")

    class Meta:
        verbose_name = "суточная сводка канала"
        verbose_name_plural = "суточные сводки каналов"
        indexes = [models.Index(fields=["channel", "-day"], name="channeldaily_channel_day")]

    def __str__(self):
        return f"{self.channel_id}@{self.day}"

from django.db import models

from apps.core.models import TimeStampedModel


class IncidentDomain(models.TextChoices):
    """Направление риска, к которому относится сигнал датчика."""

    FIRE = "fire", "Пожар"
    GAS = "gas", "Загазованность"
    FLOOD = "flood", "Подтопление"
    INTRUSION = "intrusion", "Несанкционированный доступ"
    POWER = "power", "Электропитание"
    PROCESS = "process", "Технологическое оборудование"
    CLIMATE = "climate", "Микроклимат"


class SensorType(TimeStampedModel):
    """Тип датчика (тип_датчика + тип_инж_системы из справочника каналов)."""

    name = models.CharField("тип датчика", max_length=128, unique=True)
    system_type = models.CharField("инженерная подсистема", max_length=128, blank=True)
    domain = models.CharField("направление риска", max_length=16, choices=IncidentDomain.choices)
    profile = models.ForeignKey(
        "normalization.SensorProfile",
        verbose_name="профиль нормализации",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sensor_types",
    )

    class Meta:
        verbose_name = "тип датчика"
        verbose_name_plural = "типы датчиков"
        ordering = ("name",)

    def __str__(self):
        return self.name


class Channel(TimeStampedModel):
    """Канал данных — параметр/сигнал устройства со своим ид_канала_данных и историей значений."""

    external_id = models.BigIntegerField("ид_канала_данных", unique=True)
    node = models.ForeignKey(
        "topology.Node", verbose_name="объект", on_delete=models.PROTECT, related_name="channels"
    )
    sensor_type = models.ForeignKey(
        SensorType,
        verbose_name="тип датчика",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="channels",
    )
    profile_override = models.ForeignKey(
        "normalization.SensorProfile",
        verbose_name="индивидуальный профиль",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    tag = models.CharField("тег инженерной системы", max_length=128, blank=True)
    name = models.CharField("название датчика", max_length=255)
    # Пикет разбирается из названия («ТД ПК86-85», «Темп. ВШ ПК88,5») — основа схемы коллектора
    picket = models.DecimalField("пикет", max_digits=8, decimal_places=2, null=True, blank=True)
    location_hint = models.CharField("место (ВШ, камера…)", max_length=64, blank=True)
    is_active = models.BooleanField("активен", default=True)
    in_catalog = models.BooleanField(
        "есть в справочнике",
        default=True,
        help_text="False — канал встречен в журнале, но отсутствует в справочнике заказчика",
    )

    class Meta:
        verbose_name = "канал данных"
        verbose_name_plural = "каналы данных"
        indexes = [models.Index(fields=["node", "sensor_type"])]

    def __str__(self):
        return f"{self.name} [{self.external_id}]"

    @property
    def profile(self):
        return self.profile_override or (self.sensor_type.profile if self.sensor_type else None)


class EquipmentKind(models.TextChoices):
    HATCH = "hatch", "Люк"
    VENT_SHAFT = "vent_shaft", "Вентшахта"
    CHAMBER = "chamber", "Камера"
    PUMP = "pump", "Насос"
    FAN = "fan", "Вентилятор"
    UPS = "ups", "ИБП"
    CABINET = "cabinet", "Шкаф автоматики"
    SENSOR = "sensor", "Датчик"


class Equipment(TimeStampedModel):
    """
    Реестр оборудования. У заказчика его нет — заполняется эмуляцией на основе каналов
    и средних значений наработки на отказ из открытых источников (source=emulated).
    """

    kind = models.CharField("вид", max_length=16, choices=EquipmentKind.choices)
    node = models.ForeignKey(
        "topology.Node", verbose_name="объект", on_delete=models.PROTECT, related_name="equipment"
    )
    name = models.CharField("наименование", max_length=255)
    inventory_number = models.CharField("инвентарный номер", max_length=64, blank=True)
    picket = models.DecimalField("пикет", max_digits=8, decimal_places=2, null=True, blank=True)
    channels = models.ManyToManyField(Channel, verbose_name="каналы", blank=True, related_name="equipment")
    commissioned_at = models.DateField("ввод в эксплуатацию", null=True, blank=True)
    last_maintenance_at = models.DateField("последнее ТО", null=True, blank=True)
    maintenance_interval_days = models.PositiveIntegerField(
        "регламентный интервал ТО, дн", null=True, blank=True
    )
    mtbf_hours = models.PositiveIntegerField("средняя наработка на отказ, ч", null=True, blank=True)
    source = models.CharField(
        "источник записи",
        max_length=16,
        default="emulated",
        choices=[("emulated", "эмуляция"), ("imported", "импорт"), ("manual", "вручную")],
    )

    class Meta:
        verbose_name = "единица оборудования"
        verbose_name_plural = "реестр оборудования"

    def __str__(self):
        return self.name

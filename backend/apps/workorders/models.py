from django.conf import settings
from django.db import models

from apps.assets.models import EquipmentCondition
from apps.core.models import TimeStampedModel
from apps.forecasting.models import RiskLevel


class WorkType(models.TextChoices):
    INSPECTION = "inspection", "Осмотр / проверка"
    SENSOR_REPLACEMENT = "sensor_replacement", "Замена датчика"
    CALIBRATION = "calibration", "Калибровка / поверка"
    POWER_CHECK = "power_check", "Проверка электропитания"
    PUMP_SERVICE = "pump_service", "Обслуживание насосов"
    VENTILATION = "ventilation", "Обслуживание вентиляции"
    CLEANING = "cleaning", "Очистка / откачка"
    SECURITY = "security", "Проверка охраны периметра"


class MaintenanceRecommendation(TimeStampedModel):
    """Рекомендация по ТО на основе состояния оборудования и прогнозов (ТЗ §6, §8)."""

    class Status(models.TextChoices):
        NEW = "new", "Новая"
        ACCEPTED = "accepted", "Принята"
        REJECTED = "rejected", "Отклонена"
        DONE = "done", "Выполнена"

    node = models.ForeignKey(
        "topology.Node", verbose_name="объект", on_delete=models.CASCADE, related_name="recommendations"
    )
    equipment = models.ForeignKey(
        "assets.Equipment", verbose_name="оборудование", null=True, blank=True, on_delete=models.SET_NULL
    )
    channel = models.ForeignKey(
        "assets.Channel", verbose_name="канал", null=True, blank=True, on_delete=models.SET_NULL
    )
    prediction = models.ForeignKey(
        "forecasting.Prediction", verbose_name="прогноз", null=True, blank=True, on_delete=models.SET_NULL
    )
    work_type = models.CharField("вид работ", max_length=32, choices=WorkType.choices)
    priority = models.CharField("приоритет", max_length=16, choices=RiskLevel.choices)
    due_date = models.DateField("рекомендуемый срок")
    rationale = models.TextField("обоснование")
    status = models.CharField("статус", max_length=16, choices=Status.choices, default=Status.NEW)

    class Meta:
        verbose_name = "рекомендация по ТО"
        verbose_name_plural = "рекомендации по ТО"
        ordering = ("due_date",)


class WorkOrder(TimeStampedModel):
    """
    Заявка на работы. Система формирует черновик; отправка во внешний help desk (Django,
    у заказчика) эмулируется mock-сервисом, откуда в режиме чтения забираются статусы.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        APPROVED = "approved", "Утверждена"
        SUBMITTED = "submitted", "Передана в систему заявок"
        IN_PROGRESS = "in_progress", "В работе"
        DONE = "done", "Выполнена"
        CANCELLED = "cancelled", "Отменена"

    number = models.CharField("номер", max_length=32, unique=True)
    status = models.CharField(
        "статус", max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    node = models.ForeignKey(
        "topology.Node", verbose_name="объект", on_delete=models.PROTECT, related_name="workorders"
    )
    incident = models.ForeignKey(
        "incidents.Incident",
        verbose_name="инцидент",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="workorders",
    )
    recommendation = models.ForeignKey(
        MaintenanceRecommendation,
        verbose_name="рекомендация",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="workorders",
    )
    equipment = models.ForeignKey(
        "assets.Equipment", verbose_name="оборудование", null=True, blank=True, on_delete=models.SET_NULL
    )
    work_type = models.CharField("вид работ", max_length=32, choices=WorkType.choices)
    priority = models.CharField("приоритет", max_length=16, choices=RiskLevel.choices)
    title = models.CharField("заголовок", max_length=255)
    description = models.TextField("описание и обоснование")
    due_at = models.DateTimeField("срок выполнения")
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="исполнитель",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="workorders",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="автор",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="утвердил",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    external_id = models.CharField("ID во внешней системе", max_length=64, blank=True)
    external_status = models.CharField("статус во внешней системе", max_length=64, blank=True)
    external_synced_at = models.DateTimeField("синхронизировано", null=True, blank=True)
    external_assignee = models.CharField("исполнитель во внешней системе", max_length=128, blank=True)
    # [{"status", "label", "at"}] — путь заявки в help desk, как его видит внешняя система
    external_history = models.JSONField("история во внешней системе", default=list, blank=True)
    report = models.TextField("отчёт исполнителя", blank=True)
    # Работа по утверждённому графику ТО и ТР / ППР: строка графика считается исполненной по заявке
    schedule_line = models.ForeignKey(
        "ScheduleLine",
        verbose_name="строка графика",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="workorders",
    )

    class Meta:
        verbose_name = "заявка"
        verbose_name_plural = "заявки"
        ordering = ("-created_at",)
        permissions = [
            ("approve_workorder", "Утверждать заявки"),
            ("execute_workorder", "Исполнять заявки (бригада)"),
            ("plan_maintenance", "Планировать ТО: план работ, реестр оборудования, фактическое состояние"),
        ]

    def __str__(self):
        return f"{self.number} {self.title}"


class EquipmentInspection(TimeStampedModel):
    """
    Осмотр или ТО единицы оборудования с оценкой фактического состояния. Записывает бригада при
    выполнении заявки или инженер ТО при обходе; последнее состояние копируется в реестр
    (Equipment.condition), ТО обновляет дату последнего обслуживания.
    """

    equipment = models.ForeignKey(
        "assets.Equipment", verbose_name="оборудование", on_delete=models.CASCADE, related_name="inspections"
    )
    inspected_at = models.DateTimeField("когда")
    inspector = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="кто",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    condition = models.CharField("фактическое состояние", max_length=16, choices=EquipmentCondition.choices)
    maintenance = models.BooleanField("выполнено ТО", default=False)
    notes = models.TextField("замечания", blank=True)
    workorder = models.ForeignKey(
        WorkOrder,
        verbose_name="заявка",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="inspections",
    )

    class Meta:
        verbose_name = "осмотр оборудования"
        verbose_name_plural = "осмотры оборудования"
        ordering = ("-inspected_at",)


class MaintenanceNorm(TimeStampedModel):
    """
    Регламент ТО по виду оборудования: сколько раз в год ТО и сколько из них с текущим ремонтом (ТР),
    нужен ли ежегодный ППР с поверкой в метрологической службе. Начальные значения выведены из графика
    ТО и ТР систем АКМ и ДУ заказчика на 2026 год (workorders.regulation), правятся инженером ТО.
    """

    type_name = models.CharField("вид оборудования", max_length=128, unique=True)
    system = models.CharField("система", max_length=32, blank=True)
    unit = models.CharField("ед. изм.", max_length=16, default="шт.")
    visits_per_year = models.PositiveSmallIntegerField("ТО в год", default=4)
    repairs_per_year = models.PositiveSmallIntegerField("из них ТО+ТР", default=1)
    ppr = models.BooleanField("ежегодный ППР и поверка", default=False)
    source = models.CharField("источник", max_length=255, blank=True)

    class Meta:
        verbose_name = "регламент ТО"
        verbose_name_plural = "регламент ТО"
        ordering = ("system", "type_name")

    def __str__(self):
        return f"{self.type_name}: {self.visits_per_year} ТО в год"


class MaintenanceSchedule(TimeStampedModel):
    """
    График работ на год в форме заказчика: годовой график ТО и ТР (to_tr) или план-график ППР
    аппаратуры контроля метана (ppr). Строится системой по реестру и регламенту или загружается
    из файла заказчика; утверждённый график превращается в заявки по месяцам.
    """

    class Kind(models.TextChoices):
        TO_TR = "to_tr", "График ТО и ТР"
        PPR = "ppr", "План-график ППР АКМ"

    class Source(models.TextChoices):
        GENERATED = "generated", "Сформирован системой"
        CUSTOMER = "customer", "Загружен из файла заказчика"

    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        APPROVED = "approved", "Утверждён"

    kind = models.CharField("вид", max_length=8, choices=Kind.choices)
    year = models.PositiveSmallIntegerField("год")
    title = models.CharField("название", max_length=255)
    source = models.CharField("источник", max_length=16, choices=Source.choices)
    status = models.CharField("статус", max_length=16, choices=Status.choices, default=Status.DRAFT)
    zone = models.ForeignKey(
        "topology.Node",
        verbose_name="зона",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="автор",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="утвердил",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    file_name = models.CharField("файл", max_length=255, blank=True)
    # нагрузка по месяцам, число объектов и строк, итоги сверки
    stats = models.JSONField("сводка", default=dict, blank=True)

    class Meta:
        verbose_name = "график работ"
        verbose_name_plural = "графики работ"
        ordering = ("-year", "-created_at")

    def __str__(self):
        return self.title


class ScheduleLine(models.Model):
    """
    Строка графика. ТО и ТР: объект × вид оборудования, количество и отметки по месяцам
    ({"1": "ТО", "5": "ТО+ТР"}). ППР: объект, количество датчиков метана, месяц и даты цикла
    демонтаж → сдача в ОМ на ППР и поверку → вывоз из ОМ → сдача работ комиссии (партия — batch).
    """

    schedule = models.ForeignKey(MaintenanceSchedule, on_delete=models.CASCADE, related_name="lines")
    order = models.PositiveIntegerField("порядок", default=0)
    node = models.ForeignKey(
        "topology.Node",
        verbose_name="объект",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    object_label = models.CharField("объект (как в графике)", max_length=255)
    type_name = models.CharField("вид оборудования", max_length=128, blank=True)
    brand = models.CharField("марка", max_length=128, blank=True)
    quantity = models.FloatField("количество", default=0)
    unit = models.CharField("ед. изм.", max_length=16, default="шт.")
    months = models.JSONField("отметки по месяцам", default=dict, blank=True)
    month = models.PositiveSmallIntegerField("месяц ППР", null=True, blank=True)
    batch = models.PositiveSmallIntegerField("партия ППР", null=True, blank=True)
    dismantle_on = models.DateField("начало демонтажа", null=True, blank=True)
    delivery_on = models.DateField("сдача в ОМ на ППР и поверку", null=True, blank=True)
    pickup_on = models.DateField("вывоз из ОМ", null=True, blank=True)
    acceptance_on = models.DateField("сдача работ комиссии", null=True, blank=True)
    note = models.CharField("примечание", max_length=255, blank=True)

    class Meta:
        verbose_name = "строка графика"
        verbose_name_plural = "строки графика"
        ordering = ("schedule", "order")

    def __str__(self):
        return f"{self.object_label}: {self.type_name}"

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class DataSource(TimeStampedModel):
    """
    Подключённый источник данных. adapter — ключ из adapters.REGISTRY: так в экосистему
    добавляется любой датчик/система с любым форматом (новый адаптер + профиль нормализации).
    """

    class Kind(models.TextChoices):
        FILE = "file", "Файл (CSV/XLSX)"
        STREAM = "stream", "Поток (Kafka)"
        API = "api", "REST API"

    code = models.SlugField("код", max_length=64, unique=True)
    name = models.CharField("название", max_length=255)
    kind = models.CharField("вид", max_length=16, choices=Kind.choices)
    adapter = models.CharField("адаптер", max_length=64)
    config = models.JSONField("настройки адаптера", default=dict, blank=True)
    is_active = models.BooleanField("активен", default=True)
    read_only = models.BooleanField(
        "только чтение",
        default=True,
        editable=False,
        help_text="ТЗ §13: интеграция с системами заказчика исключительно в режиме read-only",
    )

    class Meta:
        verbose_name = "источник данных"
        verbose_name_plural = "источники данных"

    def __str__(self):
        return self.name


class ImportJob(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "В очереди"
        RUNNING = "running", "Выполняется"
        DONE = "done", "Завершён"
        FAILED = "failed", "Ошибка"

    source = models.ForeignKey(
        DataSource, verbose_name="источник", on_delete=models.PROTECT, related_name="jobs"
    )
    file = models.FileField("файл", upload_to="imports/%Y/%m/", blank=True)
    file_path = models.CharField("путь к файлу на сервере", max_length=512, blank=True)
    params = models.JSONField("параметры", default=dict, blank=True)
    status = models.CharField("статус", max_length=16, choices=Status.choices, default=Status.PENDING)
    rows_total = models.BigIntegerField("строк прочитано", default=0)
    rows_ok = models.BigIntegerField("строк загружено", default=0)
    rows_skipped = models.BigIntegerField("строк пропущено", default=0)
    started_at = models.DateTimeField("начат", null=True, blank=True)
    finished_at = models.DateTimeField("завершён", null=True, blank=True)
    error = models.TextField("ошибка", blank=True)
    # Отчёт о качестве загрузки: корректные / технические / невалидные / ошибки времени / дубли
    quality = models.JSONField("качество данных", default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="инициатор", null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        verbose_name = "задание импорта"
        verbose_name_plural = "задания импорта"
        ordering = ("-created_at",)

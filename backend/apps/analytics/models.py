from django.conf import settings
from django.db import models


class ReportExport(models.Model):
    """Сформированные отчёты для руководства (PDF/XLSX, ТЗ §8)."""

    class Format(models.TextChoices):
        PDF = "pdf", "PDF"
        XLSX = "xlsx", "XLSX"
        CSV = "csv", "CSV"

    kind = models.CharField("отчёт", max_length=64)
    format = models.CharField("формат", max_length=8, choices=Format.choices)
    params = models.JSONField("параметры", default=dict, blank=True)
    file = models.FileField("файл", upload_to="reports/%Y/%m/", blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "отчёт"
        verbose_name_plural = "отчёты"
        ordering = ("-created_at",)
        permissions = [("export_report", "Выгружать отчёты")]

    def __str__(self):
        return f"{self.kind}.{self.format} ({self.created_at:%Y-%m-%d %H:%M})"

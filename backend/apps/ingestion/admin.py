from django.contrib import admin

from .models import DataSource, ImportJob


@admin.register(DataSource)
class DataSourceAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "kind", "adapter", "is_active")
    list_filter = ("kind", "is_active")


@admin.register(ImportJob)
class ImportJobAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "source",
        "status",
        "rows_total",
        "rows_ok",
        "rows_skipped",
        "started_at",
        "finished_at",
    )
    list_filter = ("status", "source")
    readonly_fields = ("rows_total", "rows_ok", "rows_skipped", "started_at", "finished_at", "error")

from django.contrib import admin

from .models import TrainingSession


@admin.register(TrainingSession)
class TrainingSessionAdmin(admin.ModelAdmin):
    list_display = (
        "started_at",
        "user",
        "lesson",
        "role",
        "node",
        "status",
        "mistakes",
        "hints",
        "finished_at",
    )
    list_filter = ("status", "lesson", "role")
    search_fields = ("user__username", "user__last_name")
    readonly_fields = ("started_at",)

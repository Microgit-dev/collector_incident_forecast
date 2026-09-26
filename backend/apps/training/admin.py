from django.contrib import admin

from .models import Exercise, ExerciseParticipant, TrainingSession


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


class ExerciseParticipantInline(admin.TabularInline):
    model = ExerciseParticipant
    extra = 0
    raw_id_fields = ("user",)


@admin.register(Exercise)
class ExerciseAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "title",
        "scenario",
        "node",
        "status",
        "scheduled_at",
        "started_at",
        "created_by",
    )
    list_filter = ("status", "scenario")
    search_fields = ("title",)
    readonly_fields = ("created_at", "report", "context")
    inlines = [ExerciseParticipantInline]

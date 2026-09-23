from django.contrib import admin

from .models import MLModel, Prediction, RiskPolicy, TrainingRun


@admin.register(MLModel)
class MLModelAdmin(admin.ModelAdmin):
    list_display = ("task", "version", "algorithm", "horizon_hours", "status", "created_at")
    list_filter = ("task", "status")


@admin.register(RiskPolicy)
class RiskPolicyAdmin(admin.ModelAdmin):
    list_display = (
        "task",
        "medium_threshold",
        "high_threshold",
        "critical_threshold",
        "alert_from_level",
        "horizon_hours",
        "enabled",
    )
    list_editable = (
        "medium_threshold",
        "high_threshold",
        "critical_threshold",
        "alert_from_level",
        "enabled",
    )


@admin.register(Prediction)
class PredictionAdmin(admin.ModelAdmin):
    list_display = ("issued_at", "task", "node", "channel", "probability", "risk_level", "outcome")
    list_filter = ("task", "risk_level", "outcome")
    date_hierarchy = "issued_at"
    raw_id_fields = ("node", "channel", "model")


@admin.register(TrainingRun)
class TrainingRunAdmin(admin.ModelAdmin):
    list_display = ("id", "task", "status", "result_model", "created_at", "finished_at")
    list_filter = ("task", "status")

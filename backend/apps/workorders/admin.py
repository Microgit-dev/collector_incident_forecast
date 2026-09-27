from django.contrib import admin

from .models import EquipmentInspection, MaintenanceRecommendation, WorkOrder


@admin.register(WorkOrder)
class WorkOrderAdmin(admin.ModelAdmin):
    list_display = (
        "number",
        "status",
        "work_type",
        "priority",
        "node",
        "assignee",
        "due_at",
        "external_status",
    )
    list_filter = ("status", "work_type", "priority")
    search_fields = ("number", "title")
    raw_id_fields = (
        "node",
        "incident",
        "recommendation",
        "equipment",
        "assignee",
        "created_by",
        "approved_by",
    )


@admin.register(MaintenanceRecommendation)
class MaintenanceRecommendationAdmin(admin.ModelAdmin):
    list_display = ("node", "work_type", "priority", "due_date", "status")
    list_filter = ("status", "work_type", "priority")
    raw_id_fields = ("node", "equipment", "channel", "prediction")


@admin.register(EquipmentInspection)
class EquipmentInspectionAdmin(admin.ModelAdmin):
    list_display = ("equipment", "inspected_at", "condition", "maintenance", "inspector", "workorder")
    list_filter = ("condition", "maintenance")
    search_fields = ("equipment__name", "equipment__inventory_number")
    autocomplete_fields = ("equipment",)
    raw_id_fields = ("workorder",)

from django.contrib import admin

from .models import (
    EquipmentInspection,
    MaintenanceNorm,
    MaintenanceRecommendation,
    MaintenanceSchedule,
    ScheduleLine,
    WorkOrder,
)


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


@admin.register(MaintenanceNorm)
class MaintenanceNormAdmin(admin.ModelAdmin):
    list_display = ("type_name", "system", "unit", "visits_per_year", "repairs_per_year", "ppr", "source")
    list_filter = ("system", "ppr")
    list_editable = ("visits_per_year", "repairs_per_year", "ppr")
    search_fields = ("type_name",)


class ScheduleLineInline(admin.TabularInline):
    model = ScheduleLine
    extra = 0
    fields = (
        "object_label",
        "type_name",
        "quantity",
        "unit",
        "months",
        "month",
        "dismantle_on",
        "acceptance_on",
    )


@admin.register(MaintenanceSchedule)
class MaintenanceScheduleAdmin(admin.ModelAdmin):
    list_display = ("title", "kind", "year", "source", "status", "created_at")
    list_filter = ("kind", "source", "status", "year")
    inlines = [ScheduleLineInline]

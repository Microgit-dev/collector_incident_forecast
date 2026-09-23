from django.contrib import admin

from .models import Channel, Equipment, SensorType


@admin.register(SensorType)
class SensorTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "system_type", "domain", "profile")
    list_filter = ("domain", "system_type", "profile")
    list_editable = ("domain", "profile")
    search_fields = ("name",)


@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    list_display = ("external_id", "name", "sensor_type", "node", "picket", "is_active", "in_catalog")
    list_filter = ("sensor_type", "is_active", "in_catalog")
    search_fields = ("name", "external_id", "tag")
    autocomplete_fields = ("node",)
    list_select_related = ("sensor_type", "node")


@admin.register(Equipment)
class EquipmentAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "node", "picket", "last_maintenance_at", "mtbf_hours", "source")
    list_filter = ("kind", "source")
    search_fields = ("name", "inventory_number")
    autocomplete_fields = ("node", "channels")

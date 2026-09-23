from django.contrib import admin

from .models import SensorProfile, StateRule


class StateRuleInline(admin.TabularInline):
    model = StateRule
    extra = 0
    fields = ("pattern", "is_regex", "state", "facet", "priority")


@admin.register(SensorProfile)
class SensorProfileAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "value_kind",
        "unit",
        "warn_threshold",
        "alarm_threshold",
        "expected_interval_s",
    )
    search_fields = ("name", "code")
    inlines = [StateRuleInline]


@admin.register(StateRule)
class StateRuleAdmin(admin.ModelAdmin):
    list_display = ("pattern", "state", "facet", "profile", "is_regex", "priority")
    list_filter = ("state", "facet", "profile")
    list_editable = ("state", "facet", "priority")
    search_fields = ("pattern",)

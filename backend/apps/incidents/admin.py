from django.contrib import admin

from .models import Alert, Decision, DecisionReason, EscalationPolicy, Incident, IncidentEvent


class AlertInline(admin.TabularInline):
    model = Alert
    extra = 0
    fields = ("raised_at", "source", "severity", "title", "channel", "acknowledged_at")
    readonly_fields = fields
    show_change_link = True


class DecisionInline(admin.TabularInline):
    model = Decision
    extra = 0
    fields = ("decided_at", "decided_by", "outcome", "reason", "comment")
    readonly_fields = fields


class EventInline(admin.TabularInline):
    model = IncidentEvent
    extra = 0
    fields = ("ts", "kind", "actor", "text")
    readonly_fields = fields


@admin.register(Incident)
class IncidentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "opened_at",
        "type",
        "severity",
        "status",
        "node",
        "responsible_node",
        "assigned_to",
        "escalation_level",
    )
    list_filter = ("type", "severity", "status", "is_forecast")
    search_fields = ("title", "node__name")
    date_hierarchy = "opened_at"
    raw_id_fields = ("node", "responsible_node", "assigned_to")
    inlines = [AlertInline, DecisionInline, EventInline]


@admin.register(DecisionReason)
class DecisionReasonAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "outcome", "is_active")
    list_filter = ("outcome", "is_active")


@admin.register(EscalationPolicy)
class EscalationPolicyAdmin(admin.ModelAdmin):
    list_display = ("severity", "ack_timeout_minutes", "max_level", "repeat_notify_minutes")
    list_editable = ("ack_timeout_minutes", "max_level", "repeat_notify_minutes")

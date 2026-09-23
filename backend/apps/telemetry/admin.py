from django.contrib import admin

from .models import ChannelState


@admin.register(ChannelState)
class ChannelStateAdmin(admin.ModelAdmin):
    list_display = ("channel", "facet", "state", "numeric", "changed_at", "last_seen_at")
    list_filter = ("state", "facet")
    search_fields = ("channel__name", "channel__external_id")
    list_select_related = ("channel",)
    readonly_fields = [f.name for f in ChannelState._meta.fields]

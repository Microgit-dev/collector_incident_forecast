from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Team, User
from .services import sync_team_scopes


class MemberInline(admin.TabularInline):
    model = User
    fk_name = "team"
    fields = ("username", "last_name", "first_name", "position", "is_active")
    readonly_fields = fields
    extra = 0
    can_delete = False
    show_change_link = True
    verbose_name_plural = "участники (состав меняется в карточке пользователя)"

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "scope_node", "parent", "lead", "is_active")
    list_filter = ("kind", "is_active")
    search_fields = ("name", "code")
    autocomplete_fields = ("scope_node", "parent", "lead")
    inlines = [MemberInline]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        sync_team_scopes()  # участники получают новую зону команды


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "last_name", "first_name", "team", "scope_node", "is_active", "is_staff")
    list_filter = ("groups", "team", "is_active", "is_staff")
    autocomplete_fields = ("scope_node", "team")
    fieldsets = (
        *BaseUserAdmin.fieldsets,
        (
            "Команда и зона ответственности",
            {
                "fields": ("team", "scope_node", "position", "phone"),
                "description": "При выборе команды зона ответственности берётся из команды.",
            },
        ),
    )

    def save_model(self, request, obj, form, change):
        if obj.team_id and obj.team.scope_node_id:
            obj.scope_node = obj.team.scope_node
        super().save_model(request, obj, form, change)

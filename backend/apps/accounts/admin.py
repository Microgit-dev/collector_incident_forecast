from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "last_name", "first_name", "scope_node", "is_active", "is_staff")
    list_filter = ("groups", "is_active", "is_staff")
    autocomplete_fields = ("scope_node",)
    fieldsets = (
        *BaseUserAdmin.fieldsets,
        ("Зона ответственности", {"fields": ("scope_node", "position", "phone")}),
    )

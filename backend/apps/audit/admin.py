from django.contrib import admin

from .models import ActionLog


@admin.register(ActionLog)
class ActionLogAdmin(admin.ModelAdmin):
    list_display = ("ts", "username", "action", "method", "path", "status_code", "ip")
    list_filter = ("action", "method", "status_code")
    search_fields = ("username", "path", "object_repr")
    date_hierarchy = "ts"

    # Журнал неизменяем даже для администратора
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

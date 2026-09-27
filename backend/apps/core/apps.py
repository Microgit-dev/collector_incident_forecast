from django.apps import AppConfig
from django.contrib.admin import apps as admin_apps


class CoreConfig(AppConfig):
    default = True
    name = "apps.core"
    label = "core"
    verbose_name = "Ядро"

    def ready(self):
        from . import checks  # noqa: F401 — регистрация проверок безопасности


class PlatformAdminConfig(admin_apps.AdminConfig):
    """Админка по разделам ответственности (admin_site.py); служебные модели скрыты."""

    default = False
    default_site = "apps.core.admin_site.PlatformAdminSite"

    def ready(self):
        super().ready()
        from django.apps import apps
        from django.contrib import admin

        from .admin_site import HIDDEN

        for key in HIDDEN:
            app_label, name = key.split(".")
            try:
                model = apps.get_model(app_label, name)
            except LookupError:
                continue
            if admin.site.is_registered(model):
                admin.site.unregister(model)

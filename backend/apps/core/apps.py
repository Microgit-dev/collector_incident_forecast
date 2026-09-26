from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "apps.core"
    label = "core"
    verbose_name = "Ядро"

    def ready(self):
        from . import checks  # noqa: F401 — регистрация проверок безопасности

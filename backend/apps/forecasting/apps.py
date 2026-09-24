from django.apps import AppConfig


class ForecastingConfig(AppConfig):
    name = "apps.forecasting"
    label = "forecasting"
    verbose_name = "Прогнозирование"

    def ready(self):
        from . import signals  # noqa: F401

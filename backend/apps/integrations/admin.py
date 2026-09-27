from django.contrib import admin

from .models import IntegrationState, WeatherObservation


@admin.register(WeatherObservation)
class WeatherObservationAdmin(admin.ModelAdmin):
    list_display = ("ts", "temperature_c", "precipitation_mm", "snowfall_cm", "humidity_pct", "is_forecast")
    list_filter = ("is_forecast",)
    date_hierarchy = "ts"


@admin.register(IntegrationState)
class IntegrationStateAdmin(admin.ModelAdmin):
    list_display = ("code", "last_ok_at", "last_error_at", "updated_at")
    readonly_fields = ("code", "last_ok_at", "last_error_at", "last_error", "last_result", "updated_at")

from django.contrib import admin

from .models import WeatherObservation


@admin.register(WeatherObservation)
class WeatherObservationAdmin(admin.ModelAdmin):
    list_display = ("ts", "temperature_c", "precipitation_mm", "snowfall_cm", "humidity_pct", "is_forecast")
    list_filter = ("is_forecast",)
    date_hierarchy = "ts"

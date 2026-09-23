from django.db import models


class WeatherObservation(models.Model):
    """
    Метеоданные по Москве (Open-Meteo archive/forecast, открытый API без ключа) —
    внешний источник из ТЗ §13 для прогноза подтоплений и сезонности.
    """

    ts = models.DateTimeField("время", unique=True)
    temperature_c = models.FloatField("температура, °C", null=True)
    humidity_pct = models.FloatField("влажность, %", null=True)
    precipitation_mm = models.FloatField("осадки, мм", null=True)
    snowfall_cm = models.FloatField("снег, см", null=True)
    pressure_hpa = models.FloatField("давление, гПа", null=True)
    is_forecast = models.BooleanField("прогноз", default=False)

    class Meta:
        verbose_name = "метеонаблюдение"
        verbose_name_plural = "метеоданные"
        ordering = ("-ts",)

    def __str__(self):
        return f"{self.ts:%Y-%m-%d %H:%M}"

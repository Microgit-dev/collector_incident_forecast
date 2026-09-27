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


class WeatherDaily(models.Model):
    """
    Суточная погода по Москве (Open-Meteo): архив ERA5 для истории, прогноз — на ближайшие сутки.
    Источник признаков модели подтопления: осадки, оттепель, таяние снежного покрова.
    """

    day = models.DateField("сутки", unique=True)
    precipitation_mm = models.FloatField("осадки, мм", null=True)
    rain_mm = models.FloatField("дождь, мм", null=True)
    snowfall_cm = models.FloatField("снег, см", null=True)
    temperature_mean_c = models.FloatField("средняя температура, °C", null=True)
    temperature_max_c = models.FloatField("максимальная температура, °C", null=True)
    snow_depth_cm = models.FloatField("снежный покров, см", null=True)
    is_forecast = models.BooleanField("прогноз", default=False)
    source = models.CharField("источник", max_length=32, default="open-meteo")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "погода за сутки"
        verbose_name_plural = "погода по суткам"
        ordering = ("-day",)

    def __str__(self):
        return f"{self.day:%Y-%m-%d}"


class IntegrationState(models.Model):
    """
    Состояние обмена с внешней системой для страницы «Интеграции»: последний успех, последняя ошибка
    и итог последней синхронизации. Настройки подключения — в .env (apps/integrations/registry.py).
    """

    code = models.SlugField("интеграция", max_length=32, unique=True)
    last_ok_at = models.DateTimeField("последний успешный обмен", null=True, blank=True)
    last_error_at = models.DateTimeField("последняя ошибка", null=True, blank=True)
    last_error = models.TextField("текст ошибки", blank=True)
    last_result = models.JSONField("итог последнего обмена", default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "состояние интеграции"
        verbose_name_plural = "состояния интеграций"
        permissions = [
            ("manage_integrations", "Проверять связь и запускать синхронизацию с внешними системами")
        ]

    def __str__(self):
        return self.code

from django.conf import settings
from django.db import models


class TrainingSession(models.Model):
    """
    Прохождение учебного задания: какой урок, кто, на каком объекте полигона, какие шаги
    и когда выполнены. Шаги засчитываются по реальным действиям в системе, а не по нажатию «далее».
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Идёт"
        DONE = "done", "Пройдено"
        ABANDONED = "abandoned", "Прервано"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="сотрудник", on_delete=models.CASCADE, related_name="training"
    )
    lesson = models.CharField("урок", max_length=64)
    role = models.CharField("роль", max_length=32, blank=True)
    node = models.ForeignKey(
        "topology.Node", verbose_name="объект полигона", null=True, blank=True, on_delete=models.SET_NULL
    )
    status = models.CharField("статус", max_length=16, choices=Status.choices, default=Status.ACTIVE)
    started_at = models.DateTimeField("начато", auto_now_add=True)
    finished_at = models.DateTimeField("завершено", null=True, blank=True)
    steps = models.JSONField("выполненные шаги", default=dict, blank=True)
    context = models.JSONField("контекст", default=dict, blank=True)
    hints = models.PositiveSmallIntegerField("подсказок", default=0)
    mistakes = models.PositiveSmallIntegerField("ошибок", default=0)

    class Meta:
        verbose_name = "учебное задание"
        verbose_name_plural = "учебные задания"
        ordering = ("-started_at",)
        indexes = [models.Index(fields=["user", "status"])]

    def __str__(self):
        return f"{self.user} · {self.lesson} · {self.get_status_display()}"


class Exercise(models.Model):
    """
    Учения: руководитель настраивает сценарий на объекте полигона и состав участников, запускает
    по кнопке или по времени, может прекратить досрочно. По итогам — разбор с хронологией и проверками.
    Проходят в учебном контуре: карточки, заявки и уведомления — настоящие, но на полигоне.
    """

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Назначены"
        RUNNING = "running", "Идут"
        FINISHED = "finished", "Завершены"
        STOPPED = "stopped", "Прекращены досрочно"
        CANCELLED = "cancelled", "Отменены"

    title = models.CharField("название", max_length=255)
    scenario = models.CharField("сценарий", max_length=32)
    node = models.ForeignKey("topology.Node", verbose_name="объект полигона", on_delete=models.PROTECT)
    speed = models.FloatField("темп нарастания", default=2.0)
    complication = models.CharField("осложнение", max_length=32, blank=True)
    complication_after_min = models.PositiveSmallIntegerField("осложнение через, мин", default=3)
    duration_min = models.PositiveSmallIntegerField("длительность, мин", default=30)
    briefing = models.TextField("вводная для участников", blank=True)
    status = models.CharField(
        "статус", max_length=16, choices=Status.choices, default=Status.SCHEDULED, db_index=True
    )
    # пусто — запуск по кнопке; время — запуск по таймеру
    scheduled_at = models.DateTimeField("начало по таймеру", null=True, blank=True)
    started_at = models.DateTimeField("начались", null=True, blank=True)
    finished_at = models.DateTimeField("закончились", null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="руководитель", on_delete=models.PROTECT, related_name="+"
    )
    stopped_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="прекратил",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    stop_reason = models.CharField("причина прекращения", max_length=255, blank=True)
    context = models.JSONField("контекст", default=dict, blank=True)
    report = models.JSONField("разбор", default=dict, blank=True)
    created_at = models.DateTimeField("создано", auto_now_add=True)

    class Meta:
        verbose_name = "учения"
        verbose_name_plural = "учения"
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.title} · {self.get_status_display()}"


class ExerciseParticipant(models.Model):
    """Участник учений. «Молчащий» получает скрытую вводную не отвечать — так проверяется эскалация."""

    exercise = models.ForeignKey(Exercise, on_delete=models.CASCADE, related_name="participants")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="сотрудник", on_delete=models.CASCADE, related_name="exercises"
    )
    role = models.CharField("роль", max_length=32, blank=True)
    silent = models.BooleanField("молчащий (проверка эскалации)", default=False)
    notified_at = models.DateTimeField("оповещён", null=True, blank=True)
    confirmed_at = models.DateTimeField("ознакомлен", null=True, blank=True)

    class Meta:
        verbose_name = "участник учений"
        verbose_name_plural = "участники учений"
        unique_together = [("exercise", "user")]

    def __str__(self):
        return f"{self.exercise} · {self.user}"

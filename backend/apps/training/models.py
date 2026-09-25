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

from django.conf import settings
from django.db import models


class ActionLog(models.Model):
    """
    Журнал действий пользователей (ТЗ §11). Изменения данных дополнительно пишет
    django-auditlog (diff полей); здесь — сам факт действия: кто, что, когда, откуда.
    """

    ts = models.DateTimeField("время", auto_now_add=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="пользователь",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="actions",
    )
    username = models.CharField("логин", max_length=150, blank=True)
    action = models.CharField("действие", max_length=64, db_index=True)
    method = models.CharField("метод", max_length=8, blank=True)
    path = models.CharField("путь", max_length=512, blank=True)
    status_code = models.PositiveSmallIntegerField("код ответа", null=True, blank=True)
    ip = models.GenericIPAddressField("IP", null=True, blank=True)
    object_repr = models.CharField("объект", max_length=255, blank=True)
    # Ссылка на объект для выборок «кто открывал карточку» (app_label.model + pk)
    object_type = models.CharField("тип объекта", max_length=64, blank=True)
    object_id = models.CharField("ид объекта", max_length=64, blank=True)
    payload = models.JSONField("детали", default=dict, blank=True)

    class Meta:
        verbose_name = "действие пользователя"
        verbose_name_plural = "журнал действий"
        ordering = ("-ts",)
        indexes = [models.Index(fields=["object_type", "object_id", "ts"])]

    def __str__(self):
        return f"{self.ts:%Y-%m-%d %H:%M:%S} {self.username} {self.action}"

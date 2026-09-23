from django.conf import settings
from django.db import models


class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    created_at = models.DateTimeField("создано", auto_now_add=True, db_index=True)
    title = models.CharField("заголовок", max_length=255)
    body = models.TextField("текст", blank=True)
    level = models.CharField("уровень", max_length=16, default="medium")
    link = models.CharField("ссылка", max_length=255, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    read_at = models.DateTimeField("прочитано", null=True, blank=True)

    class Meta:
        verbose_name = "уведомление"
        verbose_name_plural = "уведомления"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["user", "read_at"])]

    def __str__(self):
        return self.title

from django.conf import settings
from django.db import models


class WikiSection(models.Model):
    title = models.CharField("раздел", max_length=128)
    slug = models.SlugField("код", unique=True)
    order = models.PositiveSmallIntegerField("порядок", default=0)

    class Meta:
        verbose_name = "раздел вики"
        verbose_name_plural = "разделы вики"
        ordering = ("order", "title")

    def __str__(self):
        return self.title


class WikiPage(models.Model):
    """
    Статья вики: регламенты, инструкции по ролям, справка. Текст — Markdown, правится в админке.
    Пустой список ролей — статья видна всем; иначе — только этим ролям (и администратору).
    """

    section = models.ForeignKey(
        WikiSection, verbose_name="раздел", on_delete=models.PROTECT, related_name="pages"
    )
    slug = models.SlugField("адрес", max_length=80, unique=True)
    title = models.CharField("заголовок", max_length=255)
    summary = models.CharField("кратко", max_length=255, blank=True)
    body = models.TextField("текст (Markdown)")
    roles = models.JSONField("для ролей", default=list, blank=True)
    order = models.PositiveSmallIntegerField("порядок", default=0)
    is_published = models.BooleanField("опубликована", default=True)
    updated_at = models.DateTimeField("изменена", auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="кто изменил",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        verbose_name = "статья вики"
        verbose_name_plural = "статьи вики"
        ordering = ("section__order", "order", "title")

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return f"/wiki/{self.slug}"

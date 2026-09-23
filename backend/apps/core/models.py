from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField("создано", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("изменено", auto_now=True)

    class Meta:
        abstract = True


class Catalog(TimeStampedModel):
    """Базовый справочник: код для интеграций + человекочитаемое название."""

    code = models.SlugField("код", max_length=64, unique=True)
    name = models.CharField("название", max_length=255)
    is_active = models.BooleanField("активен", default=True)

    class Meta:
        abstract = True
        ordering = ("name",)

    def __str__(self):
        return self.name

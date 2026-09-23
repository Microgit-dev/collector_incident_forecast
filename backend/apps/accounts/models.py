from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Пользователь с зоной ответственности. Роль = Django Group (см. roles.py),
    зона = поддерево топологии, от которого считается видимость данных и цепочка эскалации.
    """

    scope_node = models.ForeignKey(
        "topology.Node",
        verbose_name="зона ответственности",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="users",
    )
    position = models.CharField("должность", max_length=255, blank=True)
    phone = models.CharField("телефон", max_length=32, blank=True)

    class Meta:
        verbose_name = "пользователь"
        verbose_name_plural = "пользователи"
        permissions = [("view_all_scopes", "Видит все зоны ответственности")]

    @property
    def role_codes(self) -> list[str]:
        return sorted(self.groups.values_list("name", flat=True))

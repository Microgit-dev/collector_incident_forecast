from django.contrib.auth.models import AbstractUser
from django.db import models


class TeamKind(models.TextChoices):
    MANAGEMENT = "management", "Руководство"
    ODS = "ods", "Объединённая диспетчерская служба"
    UNIT = "unit", "Диспетчерская подразделения"
    BRIGADE = "brigade", "Ремонтная бригада"
    MAINTENANCE = "maintenance", "Служба технического обслуживания"
    ANALYTICS = "analytics", "Аналитическая группа"
    SUPPORT = "support", "Администрирование и смежные службы"


class Team(models.Model):
    """
    Команда — звено командной вертикали: бригада → диспетчерская подразделения → ОДС → руководство.

    Зона команды — поддерево топологии; участники получают её как свою зону ответственности.
    Цепочка по `parent` показывает, кому подчиняется команда и куда уходит эскалация:
    эскалация идёт вверх по дереву объектов, а у каждого уровня дерева есть своя команда.
    """

    code = models.SlugField(
        "код", max_length=64, unique=True, help_text="совпадает с departmentNumber в LDAP"
    )
    name = models.CharField("название", max_length=255)
    kind = models.CharField("вид", max_length=16, choices=TeamKind.choices)
    scope_node = models.ForeignKey(
        "topology.Node",
        verbose_name="зона ответственности",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="teams",
    )
    parent = models.ForeignKey(
        "self",
        verbose_name="вышестоящая команда",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="children",
    )
    lead = models.ForeignKey(
        "User",
        verbose_name="руководитель",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    is_active = models.BooleanField("активна", default=True)

    class Meta:
        verbose_name = "команда"
        verbose_name_plural = "команды"
        ordering = ("name",)

    def __str__(self):
        return self.name

    def chain(self) -> list["Team"]:
        """Команда и все вышестоящие до вершины вертикали."""
        teams, seen, current = [], set(), self
        while current is not None and current.pk not in seen:
            teams.append(current)
            seen.add(current.pk)
            current = current.parent
        return teams


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
    team = models.ForeignKey(
        Team,
        verbose_name="команда",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="members",
    )
    position = models.CharField("должность", max_length=255, blank=True)
    phone = models.CharField("телефон", max_length=32, blank=True)

    class Meta:
        verbose_name = "пользователь"
        verbose_name_plural = "пользователи"
        permissions = [
            ("view_all_scopes", "Видит все зоны ответственности"),
            ("assign_staff", "Назначает сотрудников в зоны и командирует в другие зоны"),
            ("view_grafana", "Аналитические панели Grafana"),
            ("view_system_monitoring", "Мониторинг системы: Prometheus и системные панели Grafana"),
        ]

    @property
    def role_codes(self) -> list[str]:
        return sorted(self.groups.values_list("name", flat=True))


class Secondment(models.Model):
    """
    Командирование: сотрудник зоны временно работает в другой зоне — видит её карточки и получает её
    уведомления, не теряя своей. В смежную зону — обычный порядок; в несмежную — только «крайний случай»
    с обязательной причиной.
    """

    user = models.ForeignKey(
        User, verbose_name="сотрудник", on_delete=models.CASCADE, related_name="secondments"
    )
    zone = models.ForeignKey(
        "topology.Node", verbose_name="куда направлен", on_delete=models.CASCADE, related_name="secondments"
    )
    starts_at = models.DateTimeField("с")
    ends_at = models.DateTimeField("по")
    reason = models.CharField("причина", max_length=255, blank=True)
    emergency = models.BooleanField("крайний случай (зона не смежная)", default=False)
    created_by = models.ForeignKey(
        User, verbose_name="кто направил", null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField("создано", auto_now_add=True)
    cancelled_at = models.DateTimeField("отозван", null=True, blank=True)

    class Meta:
        verbose_name = "командирование в другую зону"
        verbose_name_plural = "командирования в другие зоны"
        ordering = ("-starts_at",)
        indexes = [models.Index(fields=["user", "ends_at"])]

    def __str__(self):
        return f"{self.user} → {self.zone}"

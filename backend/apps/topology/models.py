from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from treebeard.mp_tree import MP_Node


class NodeKind(models.TextChoices):
    DISTRICT = "district", "Район по эксплуатации"
    ZONE = "zone", "Зона ответственности"
    COMPLEX = "complex", "Объект (комплекс)"
    CONTROL_HOUSE = "control_house", "Диспетчерский пункт / шкаф"
    GUARD_OBJECT = "guard_object", "Охраняемый объект"
    SECTION = "section", "Участок коллектора"


class Node(MP_Node):
    """
    Узел дерева объектов (справочник_объектов_диспетчер.csv + синтетические участки).

    Materialized path (treebeard) выбран ради дешёвого фильтра «всё поддерево»:
    `path__startswith=node.path` — на этом построено ограничение видимости по зоне
    ответственности пользователя (см. selectors.scope_queryset).
    """

    external_id = models.BigIntegerField("ид_объект во внешней системе", null=True, blank=True, unique=True)
    kind = models.CharField("вид", max_length=32, choices=NodeKind.choices)
    source_kind = models.CharField("вид_объекта в источнике", max_length=64, blank=True)
    name = models.CharField("диспетчерское название", max_length=255)
    # Схематическая привязка: координат у заказчика нет, используем пикеты вдоль трассы
    picket_from = models.DecimalField("пикет от", max_digits=8, decimal_places=2, null=True, blank=True)
    picket_to = models.DecimalField("пикет до", max_digits=8, decimal_places=2, null=True, blank=True)
    # Привязка к местности (WGS84): контур зоны или здания объекта, точка шкафа. У заказчика координат нет —
    # контуры задаются в редакторе (автовыделение здания по карте) или засеваются для демо (seed_geo)
    geometry = models.JSONField("контур на карте (GeoJSON, WGS84)", null=True, blank=True)
    geometry_source = models.CharField("источник контура", max_length=64, blank=True)
    color = models.CharField("цвет зоны", max_length=16, blank=True)
    # Смежные зоны: соседей видно подробнее, сотрудников можно направить к ним без «крайнего случая»
    adjacent = models.ManyToManyField("self", verbose_name="смежные зоны", blank=True, symmetrical=True)
    # Вес объекта в операционном приоритете риска: 1 — второстепенный, 5 — критичный
    criticality = models.PositiveSmallIntegerField(
        "критичность", default=3, validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    is_active = models.BooleanField("активен", default=True)

    node_order_by = ["name"]

    class Meta:
        verbose_name = "узел топологии"
        verbose_name_plural = "топология объектов"
        permissions = [("manage_zones", "Создаёт и меняет зоны ответственности, их границы и смежность")]

    def __str__(self):
        return self.name

    @property
    def is_object(self) -> bool:
        return self.kind == NodeKind.COMPLEX


class Floor(models.Model):
    """
    Этаж объекта с планом помещений, привязанным к местности по контрольным точкам (topology/georef.py).

    Контрольный этаж (is_base) привязывается к спутниковому снимку и контуру здания; остальные этажи —
    к плану контрольного: так план второго этажа ложится ровно на первый, даже если на снимке
    видна только крыша. Датчики объекта ставятся на этаж (Channel.floor) точкой на его плане.
    """

    node = models.ForeignKey(Node, verbose_name="объект", on_delete=models.CASCADE, related_name="floors")
    level = models.SmallIntegerField("этаж", help_text="0 — цокольный, отрицательные — подземные")
    name = models.CharField("название", max_length=64, blank=True)
    is_base = models.BooleanField("контрольный этаж", default=False)
    plan = models.FileField("план помещений", upload_to="plans/%Y/%m/", blank=True)
    plan_width = models.PositiveIntegerField("ширина плана, px", null=True, blank=True)
    plan_height = models.PositiveIntegerField("высота плана, px", null=True, blank=True)
    # [{"px", "py", "lon", "lat", "on"}] — пары «пиксель плана ↔ точка на местности»
    points = models.JSONField("контрольные точки", default=list, blank=True)
    # углы плана nw, ne, se, sw в WGS84 по подгонке; пусто — план ещё не привязан
    corners = models.JSONField("углы плана на местности", null=True, blank=True)
    rmse_m = models.FloatField("невязка привязки, м", null=True, blank=True)
    opacity = models.FloatField("прозрачность плана", default=0.85)
    updated_at = models.DateTimeField("изменено", auto_now=True)

    class Meta:
        verbose_name = "этаж"
        verbose_name_plural = "этажи"
        ordering = ("node", "level")
        constraints = [models.UniqueConstraint(fields=["node", "level"], name="floor_unique_level")]

    def __str__(self):
        return f"{self.node.name}: {self.title}"

    @property
    def title(self) -> str:
        if self.name:
            return self.name
        return "Цокольный этаж" if self.level == 0 else f"{self.level} этаж"

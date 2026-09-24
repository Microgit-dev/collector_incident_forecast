from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from treebeard.mp_tree import MP_Node


class NodeKind(models.TextChoices):
    DISTRICT = "district", "Район по эксплуатации"
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
    geometry = models.JSONField("геометрия (GeoJSON, схематическая)", null=True, blank=True)
    # Вес объекта в операционном приоритете риска: 1 — второстепенный, 5 — критичный
    criticality = models.PositiveSmallIntegerField(
        "критичность", default=3, validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    is_active = models.BooleanField("активен", default=True)

    node_order_by = ["name"]

    class Meta:
        verbose_name = "узел топологии"
        verbose_name_plural = "топология объектов"

    def __str__(self):
        return self.name

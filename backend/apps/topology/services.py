import csv
from pathlib import Path

from django.db import transaction

from .models import Node, NodeKind

UNLINKED_NAME = "Каналы без объекта"


def _kind(level: int, source_kind: str) -> str:
    if level == 1 or source_kind == "district":
        return NodeKind.DISTRICT
    if source_kind == "guardObject":
        return NodeKind.GUARD_OBJECT
    return NodeKind.COMPLEX if level == 2 else NodeKind.CONTROL_HOUSE


@transaction.atomic
def import_objects(path: str | Path) -> dict:
    """
    Дерево объектов из справочник_объектов_диспетчер.csv. Идемпотентно: узел ищется по
    ид_объект, повторная загрузка обновляет название и вид, не пересоздавая дерево.
    Уровни обрабатываются сверху вниз, чтобы родитель всегда существовал.
    """
    with open(path, encoding="utf-8", newline="") as fh:
        rows = sorted(csv.DictReader(fh), key=lambda r: int(r["иерархия_уровень"]))

    nodes = {n.external_id: n for n in Node.objects.exclude(external_id=None)}
    created = updated = orphans = 0
    for row in rows:
        ext_id = int(row["ид_объект"])
        level = int(row["иерархия_уровень"])
        fields = {
            "name": row["диспетчерское_название_объекта"].strip(),
            "source_kind": row["вид_объекта"],
            "kind": _kind(level, row["вид_объекта"]),
        }
        if node := nodes.get(ext_id):
            for key, value in fields.items():
                setattr(node, key, value)
            node.save()
            updated += 1
            continue
        parent = nodes.get(int(row["родитель"])) if row["родитель"] else None
        if parent is None:
            orphans += level > 1
            node = Node.objects.add_root(create_kwargs={"external_id": ext_id, **fields})
        else:
            node = Node.objects.add_child(Node.objects.get(pk=parent.pk), {"external_id": ext_id, **fields})
        nodes[ext_id] = node
        created += 1
    return {"created": created, "updated": updated, "orphans": orphans, "total": Node.objects.count()}


def unlinked_node() -> Node:
    """Служебный узел для каналов, чей объект отсутствует в справочнике."""
    node = Node.objects.filter(name=UNLINKED_NAME, depth=1).first()
    return node or Node.objects.add_root(
        create_kwargs={"name": UNLINKED_NAME, "kind": NodeKind.DISTRICT, "is_active": False}
    )

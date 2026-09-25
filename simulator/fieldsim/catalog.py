"""
Каталог устройств из справочников в формате заказчика (справочник_объектов_диспетчер.csv,
справочник_каналов_датчиков.csv). Одни и те же файлы читают симулятор и платформа — так учебный
полигон существует в одном экземпляре.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

from .vocab import Kind, kind_of

OBJECTS = "справочник_объектов_диспетчер.csv"
CHANNELS = "справочник_каналов_датчиков.csv"
_PICKET = re.compile(r"ПК\s*(\d+)(?:[+,](\d+))?", re.IGNORECASE)


def picket_of(name: str) -> float | None:
    match = _PICKET.search(name)
    if not match:
        return None
    whole, part = match.groups()
    return int(whole) + (int(part) / 10 ** len(part) if part else 0)


@dataclass
class Obj:
    id: int
    name: str
    level: int
    parent: int | None
    kind: str
    children: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class Device:
    id: int
    name: str
    sensor_type: str
    system: str
    object_id: int
    picket: float | None

    @property
    def kind(self) -> Kind:
        return kind_of(self.sensor_type)


class Catalog:
    def __init__(self, objects: dict[int, Obj], devices: dict[int, Device]):
        self.objects = objects
        self.devices = devices
        for obj in objects.values():
            if obj.parent in objects:
                objects[obj.parent].children.append(obj.id)
        self._by_object: dict[int, list[Device]] = {}
        for device in devices.values():
            self._by_object.setdefault(device.object_id, []).append(device)

    @classmethod
    def load(cls, directory: str | Path) -> Catalog:
        base = Path(directory)
        if (base / "dataset" / OBJECTS).exists():
            base = base / "dataset"
        objects: dict[int, Obj] = {}
        with open(base / OBJECTS, encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                objects[int(row["ид_объект"])] = Obj(
                    id=int(row["ид_объект"]),
                    name=row["диспетчерское_название_объекта"].strip(),
                    level=int(row["иерархия_уровень"]),
                    parent=int(row["родитель"]) if row["родитель"] else None,
                    kind=row["вид_объекта"],
                )
        devices: dict[int, Device] = {}
        with open(base / CHANNELS, encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                name = row["название_датчика"].strip()
                devices[int(row["ид_канала_данных"])] = Device(
                    id=int(row["ид_канала_данных"]),
                    name=name,
                    sensor_type=row["тип_датчика"].strip(),
                    system=row["тип_инж_системы"].strip(),
                    object_id=int(row["ид_объект"]) if row["ид_объект"] else 0,
                    picket=picket_of(name),
                )
        return cls(objects, devices)

    def subtree(self, object_id: int) -> list[int]:
        """Объект и все вложенные — в порядке обхода."""
        result, stack = [], [object_id]
        while stack:
            current = stack.pop()
            result.append(current)
            stack.extend(reversed(self.objects[current].children) if current in self.objects else [])
        return result

    def devices_under(self, object_id: int) -> list[Device]:
        return [d for oid in self.subtree(object_id) for d in self._by_object.get(oid, [])]

    def find(self, object_id: int, sensor_type: str, picket: float | None = None, count: int = 1) -> list[Device]:
        """Ближайшие к пикету устройства типа под объектом (без пикета — первые по списку)."""
        found = [d for d in self.devices_under(object_id) if d.sensor_type == sensor_type]
        if picket is not None:
            found.sort(key=lambda d: abs(d.picket - picket) if d.picket is not None else 1e9)
        return found[:count]

    def _holds_guard(self, object_id: int) -> bool:
        return any(d.sensor_type == "Состояние охраны" for d in self._by_object.get(object_id, []))

    def guard_zone(self, device: Device) -> int:
        """Зона охраны контакта: ближайший вверх по дереву узел, где стоит канал «Состояние охраны»."""
        current = device.object_id
        while current in self.objects:
            if self._holds_guard(current):
                return current
            current = self.objects[current].parent
        return device.object_id

    def guard_zones(self, object_id: int) -> list[int]:
        """Зоны, которые ставятся на охрану вместе с объектом: все зоны внутри, иначе — зона сверху."""
        inside = [oid for oid in self.subtree(object_id) if self._holds_guard(oid)]
        if inside:
            return inside
        current = object_id
        while current in self.objects:
            if self._holds_guard(current):
                return [current]
            current = self.objects[current].parent
        return []

    def picket_range(self, object_id: int) -> tuple[float, float] | None:
        pickets = [d.picket for d in self.devices_under(object_id) if d.picket is not None]
        return (min(pickets), max(pickets)) if pickets else None

    def tree(self) -> list[dict]:
        """Дерево объектов для веб-интерфейса: число каналов по поддереву."""

        def node(oid: int) -> dict:
            obj = self.objects[oid]
            return {
                "id": oid,
                "name": obj.name,
                "level": obj.level,
                "channels": len(self.devices_under(oid)),
                "children": [node(c) for c in sorted(obj.children, key=lambda c: self.objects[c].name)],
            }

        roots = [o.id for o in self.objects.values() if o.parent not in self.objects]
        return [node(r) for r in sorted(roots)]

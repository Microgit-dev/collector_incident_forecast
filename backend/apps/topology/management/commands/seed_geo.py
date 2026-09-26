"""
Демо-привязка к местности: у заказчика нет координат объектов, поэтому для стенда объекты ставятся
на реальные здания OpenStreetMap одного района Москвы, а район режется на полосы-зоны ответственности
(соседние полосы — смежные зоны). Идемпотентно: существующие зоны и контуры не трогаются.
Без доступа к картографическому сервису объекты получают условные прямоугольники.
В эксплуатации контуры задаются в редакторе «Зоны и объекты» (автовыделение здания по карте).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.topology import geo
from apps.topology.models import Node, NodeKind
from apps.topology.structure import PALETTE, suggest_adjacent

# Басманный район / Лефортово: плотная застройка, здания разного размера
BBOX = (55.7555, 37.6700, 55.7705, 37.7160)  # юг, запад, север, восток
ZONES = ["Западная", "Центральная", "Восточная", "Лефортовская"]
TRAINING_ZONES = ["Полигон · Северная", "Полигон · Южная"]
# Объекты демо-диспетчеров: Мю и Кси в одной зоне, Тау — в соседней (для показа командирования)
PINNED = {"объект Мю": 1, "объект Кси": 1, "объект Тау": 2}


def _rect(west: float, south: float, east: float, north: float) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [[[west, south], [east, south], [east, north], [west, north], [west, south]]],
    }


class Command(BaseCommand):
    help = "Демо-привязка зон и объектов к местности (реальные здания OSM или условные контуры)"

    def add_arguments(self, parser):
        parser.add_argument("--offline", action="store_true", help="не ходить в OSM, условные контуры")

    def handle(self, *args, **options):
        district = (
            Node.objects.filter(depth=1, kind=NodeKind.DISTRICT, is_active=True).order_by("path").first()
        )
        if district is None:
            self.stdout.write("geo: no district, skipped")
            return
        objects = list(Node.objects.filter(kind=NodeKind.COMPLEX, is_active=True).order_by("name"))
        if not objects:
            self.stdout.write("geo: no objects, skipped")
            return
        names = TRAINING_ZONES if len(objects) <= 10 else ZONES
        south, west, north, east = BBOX
        if len(objects) <= 10:  # полигон учебного контура — компактнее
            east = west + (east - west) * 0.4
        width = (east - west) / len(names)
        strips = [_rect(west + i * width, south, west + (i + 1) * width, north) for i in range(len(names))]

        buildings: list[dict] = []
        if not options["offline"]:
            try:
                buildings = [
                    b
                    for b in geo.buildings_in(south, west, north, east)
                    if 250 <= b["area_m2"] <= 8000 and b["center"]
                ]
            except geo.GeoError as exc:
                self.stdout.write(f"geo: OSM unavailable ({exc}), synthetic outlines")
        created = self._place(district, names, strips, objects, buildings)
        self.stdout.write(f"geo: {created}")

    @transaction.atomic
    def _place(self, district, names, strips, objects, buildings) -> dict:
        zones = []
        made = 0
        for i, (name, strip) in enumerate(zip(names, strips, strict=True)):
            zone = Node.objects.filter(kind=NodeKind.ZONE, name=name).first()
            if zone is None:
                zone = Node.objects.get(pk=district.pk).add_child(
                    kind=NodeKind.ZONE,
                    name=name,
                    geometry=strip,
                    geometry_source="demo",
                    color=PALETTE[i % len(PALETTE)],
                )
                made += 1
            zones.append(zone)
        for zone in zones:
            zone.adjacent.add(*suggest_adjacent(zone))

        # здания по полосам, в каждой — по порядку с запада на восток и с севера на юг
        pools: list[list[dict]] = [[] for _ in zones]
        inner = [self._inset(s) for s in strips]  # не на самой границе зоны
        for b in sorted(buildings, key=lambda b: (-b["center"][1], b["center"][0])):
            for idx, strip in enumerate(inner):
                if geo.contains(strip, *b["center"]):
                    pools[idx].append(b)
                    break
        placed = moved = 0
        target = [min(PINNED.get(o.name, n % len(zones)), len(zones) - 1) for n, o in enumerate(objects)]
        per_zone = [target.count(i) for i in range(len(zones))]
        counters = [0] * len(zones)
        in_zone = [z.path for z in Node.objects.filter(kind=NodeKind.ZONE)]
        for obj, idx in zip(objects, target, strict=True):
            # пути перечитываются: зоны вставлены в район по алфавиту и сдвинули пути соседних узлов
            obj = Node.objects.get(pk=obj.pk)
            zone = Node.objects.get(pk=zones[idx].pk)
            if not any(obj.path.startswith(p) for p in in_zone):
                Node.objects.get(pk=obj.pk).move(Node.objects.get(pk=zone.pk), pos="sorted-child")
                moved += 1
            obj = Node.objects.get(pk=obj.pk)
            k = counters[idx]
            counters[idx] += 1
            if obj.geometry:
                continue
            pool = pools[idx]
            if pool:
                # равномерно по полосе, чтобы объекты не слипались
                b = pool[int(k * len(pool) / max(per_zone[idx], 1)) % len(pool)]
                obj.geometry, obj.geometry_source = b["geometry"], "demo:" + b["source"]
            else:
                obj.geometry, obj.geometry_source = self._synthetic(strips[idx], k), "demo:synthetic"
            obj.save(update_fields=["geometry", "geometry_source"])
            placed += 1
        return {"zones_created": made, "objects_moved": moved, "objects_placed": placed}

    def _inset(self, strip: dict, share: float = 0.12) -> dict:
        (west, south), _, (east, north) = strip["coordinates"][0][0], None, strip["coordinates"][0][2]
        dx, dy = (east - west) * share, (north - south) * share
        return _rect(west + dx, south + dy, east - dx, north - dy)

    def _synthetic(self, strip: dict, k: int) -> dict:
        (west, _south), (east, north) = strip["coordinates"][0][0], strip["coordinates"][0][2]
        cols = 4
        row, col = divmod(k, cols)
        dx, dy = (east - west) / cols, 0.0012
        cx = west + dx * (col + 0.5)
        cy = north - dy * (row + 0.7)
        w, h = dx * 0.35, dy * 0.35 * (1 + (k % 3) * 0.2)
        return _rect(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)

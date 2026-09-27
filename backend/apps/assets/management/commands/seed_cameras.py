"""
Демо-реестр камер видеонаблюдения (у заказчика реестр камер ведётся в его VMS и заводится через
админку или реестр оборудования). Камеры ставятся у входов — там, где стоят контактные датчики дверей,
люков и аварийных выходов, — и дополнительно через каждые SPACING пикетов по трассе объекта.
Идемпотентна: камеры с тем же ид не дублируются.
"""

from collections import defaultdict

from django.core.management.base import BaseCommand

from apps.assets.models import Camera, Channel
from apps.forecasting.domain.scenarios import FIRE_TYPES, INTRUSION_CONTACT

SPACING = 10.0
PER_NODE = 6


class Command(BaseCommand):
    help = "Расставляет демо-камеры у входов и вдоль трассы объектов"

    def handle(self, *args, **options):
        pickets: dict[int, dict[float, str]] = defaultdict(dict)
        rows = (
            Channel.objects.filter(is_active=True, picket__isnull=False)
            .filter(sensor_type__name__in=sorted(INTRUSION_CONTACT | FIRE_TYPES))
            .values_list("node_id", "picket", "sensor_type__name")
        )
        for node_id, picket, stype in rows:
            where = "вход" if stype in INTRUSION_CONTACT else "трасса"
            pickets[node_id].setdefault(float(picket), where)
        created = 0
        for node_id, marks in pickets.items():
            chosen: list[tuple[float, str]] = []
            # сначала входы, затем точки трассы не ближе SPACING к уже выбранным
            for picket, where in sorted(marks.items(), key=lambda kv: (kv[1] != "вход", kv[0])):
                if all(abs(picket - p) >= (1.0 if where == "вход" else SPACING) for p, _ in chosen):
                    chosen.append((picket, where))
                if len(chosen) >= PER_NODE:
                    break
            for picket, where in sorted(chosen):
                label = f"{picket:g}".replace(".", ",")
                _, is_new = Camera.objects.get_or_create(
                    external_id=f"CAM-{node_id}-{label}",
                    defaults={
                        "node_id": node_id,
                        "picket": picket,
                        "name": f"Камера ПК{label} ({where})",
                    },
                )
                created += is_new
        self.stdout.write(f"cameras: {created} created, {Camera.objects.count()} total")

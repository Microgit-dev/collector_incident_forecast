"""
Три демонстрационных сценария (ТЗ §15) на настоящих эпизодах из данных заказчика. Эпизод берётся
из Parquet-архива и публикуется в Kafka как живой поток с текущим временем и ускорением: всё
остальное — нормализация, правила, склейка в карточки, гипотезы, приоритет, уведомления —
отрабатывает так же, как в работе.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.assets.models import Channel
from apps.ingestion.streaming import publish, states_before, stream_events
from apps.topology.models import Node

MSK = ZoneInfo("Europe/Moscow")
PRIME_PAUSE = 8  # с


@dataclass(frozen=True)
class Scenario:
    title: str
    start: str  # по Москве
    end: str
    node: str | None = None  # весь объект (его поддерево)
    channel: int | None = None  # или один канал (внешний ид)
    speed: float = 10.0
    show: tuple[str, ...] = ()


SCENARIOS = {
    "alarms": Scenario(
        title="Поток тревог: потеря связи на «Кси ПК0–ПК202», 24.06.2026",
        node="объект Кси ПК0-ПК202",
        start="2026-06-24T12:20",
        end="2026-06-24T12:50",
        speed=10,
        show=(
            "Главный экран: «Сырые сигналы» растут сотнями, «Эпизоды» — одна карточка.",
            "Карточка: «Потеря связи», контур технический, гипотеза «потеря связи с контроллером», чек-лист.",
            "Схема объектов: вся трасса «Кси» в отметках каналов не в норме.",
        ),
    ),
    "fire": Scenario(
        title="Пожарный риск: срабатывания извещателей на «Кси ПК202–ПК302», 29.06.2026",
        node="объект Кси ПК202-ПК302",
        start="2026-06-29T10:55",
        end="2026-06-29T11:20",
        speed=5,
        show=(
            "Главный экран: карточка «Пожар / задымление» физического контура с высоким приоритетом.",
            "Карточка: гипотезы «возгорание» против «ложное срабатывание», соседние извещатели подтверждают друг друга.",
            "Решение: «что произошло» → реальное событие или ложное срабатывание; эскалация, если не взять в срок.",
        ),
    ),
    "sensor": Scenario(
        title="Отказ датчика: «АНС2 Н1 ПК100 Обр» на «ДУ объект Альфа» — предсказан за 21 час",
        channel=196627,
        start="2026-06-02T20:55",
        end="2026-06-02T21:05",
        speed=5,
        show=(
            "До запуска: Журнал прогнозов → бэктест → «АНС2 Н1 ПК100 Обр», прогноз 01.06 23:59, риск критический"
            " 72 %, факторы (65 суток с неисправностями за 90) и история канала.",
            "После запуска: карточка технического контура по этому каналу («Отключено устройство»), гипотеза"
            " «отказ отдельного датчика»; решение «что произошло: неисправность датчика» — подтверждающая метка"
            " для дообучения.",
            "Заявка: черновик из карточки → утвердить → передать в систему заявок → бригада, отчёт.",
        ),
    ),
}


class Command(BaseCommand):
    help = "Демо-сценарий: настоящий эпизод из архива подаётся в систему как живой поток"

    def add_arguments(self, parser):
        parser.add_argument("scenario", choices=sorted(SCENARIOS))
        parser.add_argument("--speed", type=float, help="ускорение относительно реального времени")
        parser.add_argument(
            "--dry-run", action="store_true", help="только показать, что будет воспроизведено"
        )

    def handle(self, *args, scenario, speed=None, dry_run=False, **options):
        sc = SCENARIOS[scenario]
        start = datetime.fromisoformat(sc.start).replace(tzinfo=MSK)
        end = datetime.fromisoformat(sc.end).replace(tzinfo=MSK)
        path = settings.ARTIFACTS_DIR / "archive" / f"journal_{start.year}.parquet"
        if not path.exists():
            raise CommandError(f"Нет архива {path.name}: загрузите журналы {start.year} года")
        if sc.node:
            node = Node.objects.filter(name=sc.node).first()
            if node is None:
                raise CommandError(f"Нет объекта «{sc.node}»")
            channels = list(
                Channel.objects.filter(node__path__startswith=node.path).values_list("external_id", flat=True)
            )
        else:
            channels = [sc.channel]
        speed = speed or sc.speed
        minutes = (end - start).total_seconds() / 60 / speed
        self.stdout.write(self.style.MIGRATE_HEADING(sc.title))
        self.stdout.write(
            f"Интервал {start:%d.%m.%Y %H:%M}–{end:%H:%M} МСК, каналов {len(channels)}, "
            f"ускорение ×{speed:g} — около {minutes:.1f} мин"
        )
        for line in sc.show:
            self.stdout.write(f"  • {line}")
        if dry_run:
            return
        primed = publish(states_before(str(path), start, channels), speed=0)
        self.stdout.write(f"Исходные состояния каналов на начало эпизода: {primed}")
        time.sleep(PRIME_PAUSE)  # consumer применяет исходные состояния до начала эпизода
        sent = stream_events("smvu_archive", str(path), start=start, end=end, channels=channels, speed=speed)
        self.stdout.write(self.style.SUCCESS(f"Опубликовано событий эпизода: {sent}"))

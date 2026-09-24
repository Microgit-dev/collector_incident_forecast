import dataclasses
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.ingestion.adapters import REGISTRY
from apps.ingestion.kafka import encode, make_producer


class Command(BaseCommand):
    help = (
        "Эмулятор потока СМВУ: читает журнал и публикует события в Kafka, сохраняя интервалы "
        "между событиями с ускорением --speed. Реальных интеграций заказчик не даёт — "
        "поэтому поток строится из настоящих исторических данных, а не из случайных чисел."
    )

    def add_arguments(self, parser):
        parser.add_argument("path", help="CSV журнала, например /data/dataset/журнал_событий_пример.csv")
        parser.add_argument("--adapter", default="smvu_csv")
        parser.add_argument(
            "--speed", type=float, default=60.0, help="Во сколько раз быстрее реального времени"
        )
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument(
            "--historical",
            action="store_true",
            help="Сохранять исходное время событий. По умолчанию время заменяется текущим — "
            "поток выглядит «живым», и реактивные правила создают инциденты",
        )

    def handle(self, *args, path, adapter, speed, limit, historical, **options):
        producer = make_producer()
        topic = settings.KAFKA["TOPIC_RAW_EVENTS"]
        prev_ts = None
        sent = 0
        for event in REGISTRY[adapter].iter_events(path=path):
            if prev_ts is not None and speed > 0:
                gap = (event.ts - prev_ts).total_seconds() / speed
                if gap > 0:
                    producer.poll(0)
                    time.sleep(min(gap, 5.0))
            prev_ts = event.ts
            if not historical:
                event = dataclasses.replace(event, ts=timezone.now())
            # Ключ = канал: события одного канала попадают в одну партицию и сохраняют порядок
            producer.produce(topic, key=str(event.channel_external_id), value=encode(event.to_message()))
            sent += 1
            if sent % 10_000 == 0:
                producer.poll(0)
                self.stdout.write(f"sent {sent} (source time {prev_ts:%Y-%m-%d %H:%M:%S})")
            if limit and sent >= limit:
                break
        producer.flush()
        self.stdout.write(self.style.SUCCESS(f"done: {sent} events → {topic}"))

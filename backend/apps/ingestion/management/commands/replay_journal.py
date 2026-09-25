from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.ingestion.streaming import stream_events


class Command(BaseCommand):
    help = (
        "Эмулятор потока СМВУ: читает журнал и публикует события в Kafka, сохраняя интервалы "
        "между событиями с ускорением --speed. Реальных интеграций заказчик не даёт — "
        "поэтому поток строится из настоящих исторических данных, а не из случайных чисел."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "path",
            help="CSV журнала (/data/dataset/журнал_событий_пример.csv) или архив "
            "(/artifacts/archive/journal_2026.parquet с --adapter smvu_archive)",
        )
        parser.add_argument(
            "--from", dest="start", type=datetime.fromisoformat, help="начало интервала (архив)"
        )
        parser.add_argument("--to", dest="end", type=datetime.fromisoformat, help="конец интервала (архив)")
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

    def handle(self, *args, path, adapter, speed, limit, historical, start=None, end=None, **options):
        sent = stream_events(
            adapter,
            path,
            start=start,
            end=end,
            speed=speed,
            limit=limit,
            historical=historical,
            echo=self.stdout.write,
        )
        self.stdout.write(self.style.SUCCESS(f"done: {sent} events → {settings.KAFKA['TOPIC_RAW_EVENTS']}"))

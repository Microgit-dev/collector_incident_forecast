import logging
import signal
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from prometheus_client import Histogram, start_http_server

from apps.ingestion.adapters import RawEvent
from apps.ingestion.kafka import decode, make_consumer
from apps.ingestion.pipeline import Pipeline

logger = logging.getLogger(__name__)

# Задержка от времени события до записи — проверка требования ТЗ «не более 300 с»
LAG_SECONDS = Histogram(
    "ingestion_event_lag_seconds",
    "Задержка обработки события",
    buckets=(1, 5, 15, 30, 60, 120, 300, 600, 1800),
)


class Command(BaseCommand):
    help = "Потоковый приём событий СМВУ из Kafka: нормализация и запись в телеметрию"

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=2000)
        parser.add_argument("--poll-timeout", type=float, default=1.0)
        parser.add_argument("--metrics-port", type=int, default=9101)

    def handle(self, *args, batch_size, poll_timeout, metrics_port, **options):
        start_http_server(metrics_port)
        topic = settings.KAFKA["TOPIC_RAW_EVENTS"]
        consumer = make_consumer()
        consumer.subscribe([topic])
        pipeline = Pipeline()
        running = True

        def stop(*_):
            nonlocal running
            running = False

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        self.stdout.write(f"consuming {topic} …")

        try:
            while running:
                messages = consumer.consume(num_messages=batch_size, timeout=poll_timeout)
                events = []
                for msg in messages:
                    if msg.error():
                        logger.warning("kafka error: %s", msg.error())
                        continue
                    try:
                        events.append(RawEvent.from_message(decode(msg.value())))
                    except (ValueError, KeyError):
                        logger.warning("malformed message at offset %s", msg.offset())
                if not events:
                    continue
                result = pipeline.process(events)
                consumer.commit(asynchronous=False)
                # В режиме реплея время события историческое, поэтому lag меряем по времени приёма
                now = time.time()
                for msg in messages:
                    _, ts_ms = msg.timestamp()
                    if ts_ms > 0:
                        LAG_SECONDS.observe(max(0.0, now - ts_ms / 1000))
                logger.info(
                    "batch: received=%s stored=%s unknown=%s changes=%s",
                    result.received,
                    result.stored,
                    result.skipped_unknown_channel,
                    len(result.changes),
                )
        finally:
            consumer.close()

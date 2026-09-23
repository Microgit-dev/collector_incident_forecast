import json

from confluent_kafka import Consumer, Producer
from django.conf import settings


def make_producer() -> Producer:
    return Producer(
        {
            "bootstrap.servers": settings.KAFKA["BOOTSTRAP_SERVERS"],
            "linger.ms": 50,
            "compression.type": "lz4",
            "enable.idempotence": True,
        }
    )


def make_consumer(group_id: str | None = None) -> Consumer:
    return Consumer(
        {
            "bootstrap.servers": settings.KAFKA["BOOTSTRAP_SERVERS"],
            "group.id": group_id or settings.KAFKA["CONSUMER_GROUP"],
            "auto.offset.reset": "earliest",
            # Коммитим вручную после успешной записи батча: at-least-once,
            # дубликаты гасит составной ключ (ts, event_id) в hypertable
            "enable.auto.commit": False,
        }
    )


def encode(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode()


def decode(raw: bytes) -> dict:
    return json.loads(raw)

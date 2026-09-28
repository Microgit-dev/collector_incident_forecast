"""
Конструктор источников: шаблон формата (templates.py) + профиль нормализации канала = новый датчик
без программиста.

- preview   — песочница: пример сообщения → события → как их нормализует профиль канала (или выбранный
              профиль, если канал ещё не заведён);
- ingest    — приём сообщений по шаблону (HTTP от шлюза с ключом источника) в тот же поток Kafka,
              что у СМВУ: дальше конвейер не отличает источник;
- unwrap    — консьюмер принимает и обёртку {"template": код, "payload": "…"}: шлюз может писать в Kafka
              в своём формате.
"""

from __future__ import annotations

import secrets
import time

from django.conf import settings

from apps.assets.models import Channel
from apps.normalization.domain.engine import normalize
from apps.normalization.selectors import compiled_registry

from .adapters.base import RawEvent
from .models import DataSource
from .pipeline import FALLBACK_PROFILE
from .templates import TemplateError, parse

TEMPLATE_ADAPTER = "template"
MAX_PAYLOAD = 1 * 2**20


def new_token() -> str:
    return secrets.token_urlsafe(24)


def preview(fmt: str, config: dict, sample: str, profile_code: str | None = None) -> dict:
    result = parse(fmt, config, sample, source="preview")
    registry = compiled_registry()
    channels = {
        c["external_id"]: c
        for c in Channel.objects.filter(
            external_id__in=[e.channel_external_id for e in result.events]
        ).values(
            "external_id",
            "name",
            "node__name",
            "sensor_type__name",
            "profile_override__code",
            "sensor_type__profile__code",
        )
    }
    rows = []
    for e in result.events[:200]:
        channel = channels.get(e.channel_external_id)
        code = (
            (channel["profile_override__code"] or channel["sensor_type__profile__code"])
            if channel
            else profile_code
        )
        profile = registry.profiles.get(code or "", FALLBACK_PROFILE)
        n = normalize(e.raw_value, profile, registry.global_rules, e.raw_alarm)
        rows.append(
            {
                "channel": e.channel_external_id,
                "channel_name": channel["name"] if channel else None,
                "object": channel["node__name"] if channel else None,
                "sensor_type": channel["sensor_type__name"] if channel else None,
                "known": channel is not None,
                "profile": profile.code,
                "ts": e.ts.isoformat(),
                "raw_value": e.raw_value,
                "raw_alarm": e.raw_alarm,
                "event_id": e.event_id,
                "state": n.state.value,
                "numeric": n.numeric,
                "facet": n.facet,
                "quality": n.quality.value,
            }
        )
    return {"events": rows, "total": len(result.events), "errors": result.errors}


def publish(events: list[RawEvent]) -> int:
    from .kafka import encode, make_producer

    producer = make_producer()
    topic = settings.KAFKA["TOPIC_RAW_EVENTS"]
    for e in events:
        producer.produce(topic, key=str(e.channel_external_id).encode(), value=encode(e.to_message()))
    producer.flush(10)
    return len(events)


def ingest(source: DataSource, text: str) -> dict:
    result = parse(source.format, source.config, text, source=source.code)
    published = publish(result.events) if result.events else 0
    return {"accepted": published, "errors": result.errors[:50], "error_count": len(result.errors)}


class TemplateCache:
    """Шаблоны источников для консьюмера: перечитываются раз в ttl секунд."""

    def __init__(self, ttl: int = 60):
        self.ttl, self._loaded, self._by_code = ttl, 0.0, {}

    def get(self, code: str) -> DataSource | None:
        if time.monotonic() - self._loaded > self.ttl:
            self._by_code = {
                s.code: s for s in DataSource.objects.filter(adapter=TEMPLATE_ADAPTER, is_active=True)
            }
            self._loaded = time.monotonic()
        return self._by_code.get(code)


def unwrap(message: dict, cache: TemplateCache) -> list[RawEvent]:
    """Сообщение Kafka: событие СМВУ как есть или {"template": код, "payload": текст} — разбор по шаблону."""
    if "template" not in message:
        return [RawEvent.from_message(message)]
    source = cache.get(str(message["template"]))
    if source is None:
        raise TemplateError(f"нет активного шаблона «{message['template']}»")
    payload = message.get("payload", "")
    if not isinstance(payload, str):
        import json

        payload = json.dumps(payload, ensure_ascii=False)
    return parse(source.format, source.config, payload, source=source.code).events

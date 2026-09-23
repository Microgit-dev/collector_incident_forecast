"""
Конвейер приёма: RawEvent → канал из справочника → нормализация по профилю → телеметрия.
Используется одинаково потоковым консьюмером Kafka и пакетным импортом файлов.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from prometheus_client import Counter

from apps.assets.models import Channel
from apps.normalization.domain.engine import Profile, normalize
from apps.normalization.selectors import CompiledRegistry, compiled_registry
from apps.telemetry.services import NormalizedReading, StateChange, store_readings

from .adapters import RawEvent

logger = logging.getLogger(__name__)

EVENTS_TOTAL = Counter("ingestion_events_total", "Событий обработано конвейером", ["result"])
FALLBACK_PROFILE = Profile(code="fallback")


@dataclass
class BatchResult:
    received: int = 0
    stored: int = 0
    skipped_unknown_channel: int = 0
    changes: list[StateChange] = field(default_factory=list)


class ChannelDirectory:
    """Кэш ид_канала_данных → (pk, код профиля) с периодическим обновлением из БД."""

    def __init__(self, ttl_seconds: int = 300):
        self.ttl = ttl_seconds
        self._map: dict[int, tuple[int, str | None]] = {}
        self._loaded_at = 0.0

    def _load(self) -> None:
        rows = Channel.objects.values_list(
            "external_id", "pk", "profile_override__code", "sensor_type__profile__code"
        )
        self._map = {ext: (pk, override or by_type) for ext, pk, override, by_type in rows}
        self._loaded_at = time.monotonic()

    def get(self, external_id: int) -> tuple[int, str | None] | None:
        if time.monotonic() - self._loaded_at > self.ttl:
            self._load()
        return self._map.get(external_id)


class Pipeline:
    def __init__(self, registry_ttl_seconds: int = 60):
        self.directory = ChannelDirectory()
        self._registry: CompiledRegistry | None = None
        self._registry_ttl = registry_ttl_seconds
        self._registry_loaded_at = 0.0

    @property
    def registry(self) -> CompiledRegistry:
        # Правки профилей в админке подхватываются без рестарта консьюмера
        if self._registry is None or time.monotonic() - self._registry_loaded_at > self._registry_ttl:
            self._registry = compiled_registry()
            self._registry_loaded_at = time.monotonic()
        return self._registry

    def process(self, events: list[RawEvent]) -> BatchResult:
        result = BatchResult(received=len(events))
        registry = self.registry
        items: list[NormalizedReading] = []
        for event in events:
            resolved = self.directory.get(event.channel_external_id)
            if resolved is None:
                result.skipped_unknown_channel += 1
                continue
            channel_id, profile_code = resolved
            profile = registry.profiles.get(profile_code or "", FALLBACK_PROFILE)
            items.append(
                NormalizedReading(
                    event_id=event.event_id,
                    channel_id=channel_id,
                    ts=event.ts,
                    raw_value=event.raw_value,
                    raw_alarm=event.raw_alarm,
                    value=normalize(event.raw_value, profile, registry.global_rules),
                )
            )
        result.changes = store_readings(items)
        result.stored = len(items)
        EVENTS_TOTAL.labels("stored").inc(result.stored)
        EVENTS_TOTAL.labels("unknown_channel").inc(result.skipped_unknown_channel)
        return result

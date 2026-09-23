from __future__ import annotations

from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class RawEvent:
    """
    Единый внутренний формат события, в который адаптер приводит любой источник.
    Дальше конвейер работает только с ним — это контракт между адаптерами и ядром.
    """

    event_id: int
    channel_external_id: int
    ts: datetime
    raw_value: str
    raw_alarm: bool | None = None
    source: str = "smvu"

    def to_message(self) -> dict[str, Any]:
        data = asdict(self)
        data["ts"] = self.ts.isoformat()
        return data

    @classmethod
    def from_message(cls, data: dict[str, Any]) -> RawEvent:
        return cls(
            event_id=int(data["event_id"]),
            channel_external_id=int(data["channel_external_id"]),
            ts=datetime.fromisoformat(data["ts"]),
            raw_value=str(data.get("raw_value", "")),
            raw_alarm=data.get("raw_alarm"),
            source=data.get("source", "smvu"),
        )


class SourceAdapter(Protocol):
    """Адаптер читает источник и отдаёт RawEvent. Регистрируется в adapters.REGISTRY."""

    key: str

    def iter_events(self, **params: Any) -> Iterator[RawEvent]: ...

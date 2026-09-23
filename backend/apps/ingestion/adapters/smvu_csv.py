from __future__ import annotations

import csv
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .base import RawEvent

MSK = ZoneInfo("Europe/Moscow")
_TRUE = {"t", "true", "1", "да"}
_FALSE = {"f", "false", "0", "нет"}


def parse_bool(value: str) -> bool | None:
    v = value.strip().lower()
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    return None


class SmvuCsvAdapter:
    """
    Журнал сработок СМВУ в CSV: ид_события,ид_канала_данных,дата,время,тревожное,значение_датчика.
    Годовые выгрузки пишут тревожное как t/f, пример — как true/false; поддерживаем оба.
    Время в выгрузке местное (МСК).
    """

    key = "smvu_csv"

    def iter_events(self, path: str | Path, encoding: str = "utf-8", **_) -> Iterator[RawEvent]:
        with open(path, encoding=encoding, newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                try:
                    ts = datetime.fromisoformat(f"{row['дата']}T{row['время']}").replace(tzinfo=MSK)
                    yield RawEvent(
                        event_id=int(row["ид_события"]),
                        channel_external_id=int(row["ид_канала_данных"]),
                        ts=ts,
                        raw_value=row.get("значение_датчика") or "",
                        raw_alarm=parse_bool(row.get("тревожное") or ""),
                    )
                except (KeyError, ValueError):
                    # Битые строки не останавливают загрузку; счётчик пропусков ведёт конвейер
                    continue

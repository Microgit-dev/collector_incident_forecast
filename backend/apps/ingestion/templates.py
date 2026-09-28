"""
Шаблоны формата сообщений: подключение датчика или шлюза с любым форматом без программиста.

Шаблон описывает, где в сообщении канал, время, значение и признак тревоги. Разбор приводит сообщение
к единому событию RawEvent, дальше — тот же конвейер, что у СМВУ: профиль нормализации канала
(пороги, служебные коды, правила состояний), прогнозы, карточки.

Форматы:
    json   — пути к полям через точку («data.dev.id», «items[0].v»); items — путь к массиву измерений;
    csv    — колонки по названию из заголовка или по порядку (columns), разделитель;
    regex  — регулярное выражение с именованными группами (?P<channel>…) для текстовых строк.

Поля (fields):
    channel      путь к ид канала или «=80000001» — константа; channel_map — ключ → ид канала
    ts           путь к времени или список путей (дата и время отдельно); ts_format — iso, epoch_s,
                 epoch_ms или формат strptime («%d.%m.%Y %H:%M:%S»); timezone — пояс времени без смещения
    value        путь к значению (текст или число — интерпретирует профиль)
    alarm        путь к признаку тревоги (1/0, t/f, true/false, да/нет), необязательно
    event_id     путь к ид события, необязательно (иначе — хеш канала, времени и значения)
measurements — несколько измерений в одном сообщении (составной датчик): у каждого свои value и
channel, остальные поля общие. Пример — шлюз, который шлёт температуру и влажность одним пакетом.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from .adapters.base import RawEvent

FORMATS = ("json", "csv", "regex")
_TRUE = {"1", "t", "true", "yes", "да", "on", "alarm", "тревога"}
_FALSE = {"0", "f", "false", "no", "нет", "off", "norm", "норма"}
_INDEX = re.compile(r"^(.*)\[(\d+)\]$")


class TemplateError(ValueError):
    pass


@dataclass
class ParseResult:
    events: list[RawEvent] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)


def resolve(item: Any, path: str | None) -> Any:
    """Значение по пути «a.b[0].c» (префикс «$.» допускается); константа — «=значение»."""
    if path is None or path == "":
        return None
    if isinstance(path, str) and path.startswith("="):
        return path[1:]
    current = item
    for part in str(path).removeprefix("$.").removeprefix("$").split("."):
        if part == "":
            continue
        index = None
        if m := _INDEX.match(part):
            part, index = m.group(1), int(m.group(2))
        if part:
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]
        if index is not None:
            if not isinstance(current, list) or index >= len(current):
                return None
            current = current[index]
    return current


def _alarm(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    return None


def _timestamp(item: Any, fields: dict) -> datetime:
    spec = fields.get("ts")
    fmt = fields.get("ts_format", "iso")
    zone = ZoneInfo(fields.get("timezone") or "Europe/Moscow")
    if not spec:
        return datetime.now(UTC)
    parts = [resolve(item, p) for p in spec] if isinstance(spec, list) else [resolve(item, spec)]
    if any(p is None or p == "" for p in parts):
        raise TemplateError(f"нет времени по пути {spec}")
    if fmt in ("epoch_s", "epoch_ms"):
        value = float(parts[0])
        return datetime.fromtimestamp(value / 1000 if fmt == "epoch_ms" else value, tz=UTC)
    text = " ".join(str(p).strip() for p in parts)
    if fmt == "iso":
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    else:
        moment = datetime.strptime(text, fmt)
    return moment if moment.tzinfo else moment.replace(tzinfo=zone)


def _event_id(channel: int, ts: datetime, value: str) -> int:
    digest = hashlib.blake2b(f"{channel}|{ts.isoformat()}|{value}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") >> 1  # положительный bigint


def _channel(item: Any, spec: dict) -> int:
    raw = resolve(item, spec.get("channel"))
    mapping = spec.get("channel_map") or {}
    if mapping:
        key = str(raw)
        if key not in mapping:
            raise TemplateError(f"канал «{key}» не описан в channel_map")
        raw = mapping[key]
    if raw is None or raw == "":
        raise TemplateError("нет ид канала")
    try:
        return int(str(raw).strip())
    except ValueError as exc:
        raise TemplateError(f"ид канала не число: «{raw}»") from exc


def _events_from_item(item: Any, fields: dict, measurements: list[dict], source: str) -> list[RawEvent]:
    ts = _timestamp(item, fields)
    alarm = _alarm(resolve(item, fields.get("alarm")))
    specs = measurements or [fields]
    events = []
    for spec in specs:
        merged = {**fields, **{k: v for k, v in spec.items() if v not in (None, "")}}
        value = resolve(item, merged.get("value"))
        if value is None:
            if measurements:
                continue  # измерение отсутствует в этом пакете — не ошибка
            raise TemplateError(f"нет значения по пути {merged.get('value')}")
        text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
        channel = _channel(item, merged)
        given = resolve(item, merged.get("event_id"))
        events.append(
            RawEvent(
                event_id=int(given) if given not in (None, "") else _event_id(channel, ts, text),
                channel_external_id=channel,
                ts=ts,
                raw_value=text,
                raw_alarm=_alarm(resolve(item, spec["alarm"])) if spec.get("alarm") else alarm,
                source=source,
            )
        )
    return events


def _items(fmt: str, config: dict, text: str) -> list[Any]:
    if fmt == "json":
        text = text.strip()
        # несколько JSON-сообщений построчно (NDJSON) или один документ
        docs = []
        try:
            docs = [json.loads(text)]
        except json.JSONDecodeError:
            for n, line in enumerate(text.splitlines(), start=1):
                if line.strip():
                    try:
                        docs.append(json.loads(line))
                    except json.JSONDecodeError as exc:
                        raise TemplateError(f"строка {n}: не JSON ({exc.msg})") from exc
        items: list[Any] = []
        for doc in docs:
            docs_items = resolve(doc, config["items"]) if config.get("items") else doc
            if isinstance(docs_items, list):
                # общие поля верхнего уровня доступны в каждом измерении через «^.поле»
                items.extend({**d, "^": doc} if isinstance(d, dict) else d for d in docs_items)
            else:
                items.append(docs_items)
        return items
    if fmt == "csv":
        delimiter = config.get("delimiter") or ","
        reader = csv.reader(io.StringIO(text.strip()), delimiter=delimiter)
        rows = [r for r in reader if any(c.strip() for c in r)]
        if config.get("header", True):
            header, rows = [h.strip() for h in rows[0]], rows[1:]
        else:
            header = config.get("columns") or [str(i) for i in range(len(rows[0]) if rows else 0)]
        return [dict(zip(header, (c.strip() for c in r), strict=False)) for r in rows]
    if fmt == "regex":
        try:
            pattern = re.compile(config["pattern"])
        except (KeyError, re.error) as exc:
            raise TemplateError(f"регулярное выражение: {exc}") from exc
        items = []
        for n, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            m = pattern.search(line)
            if not m:
                raise TemplateError(f"строка {n} не подходит под шаблон")
            items.append(m.groupdict())
        return items
    raise TemplateError(f"неизвестный формат «{fmt}»: json, csv или regex")


def parse(fmt: str, config: dict, text: str, source: str = "template") -> ParseResult:
    """Сообщение (или пачка строк) → события RawEvent. Ошибки строк не останавливают разбор."""
    result = ParseResult()
    try:
        items = _items(fmt, config, text)
    except (TemplateError, IndexError) as exc:
        result.errors.append({"item": None, "error": str(exc)})
        return result
    fields = config.get("fields") or {}
    measurements = config.get("measurements") or []
    for n, item in enumerate(items, start=1):
        try:
            result.events.extend(_events_from_item(item, fields, measurements, source))
        except (TemplateError, ValueError, TypeError) as exc:
            result.errors.append({"item": n, "error": str(exc)})
    return result


# ---------------------------------------------------------------- библиотека шаблонов

LIBRARY: list[dict] = [
    {
        "code": "smvu-json",
        "name": "СМВУ: событие JSON (поток Kafka)",
        "description": "Текущий формат шлюза СМВУ: одно событие — один канал.",
        "format": "json",
        "config": {
            "fields": {
                "channel": "channel_external_id",
                "ts": "ts",
                "ts_format": "iso",
                "value": "raw_value",
                "alarm": "raw_alarm",
                "event_id": "event_id",
            }
        },
        "sample": '{"event_id": 3008235019, "channel_external_id": 56682, "ts": "2026-06-24T12:15:00+03:00", '
        '"raw_value": "25,40", "raw_alarm": false}',
    },
    {
        "code": "smvu-csv",
        "name": "СМВУ: журнал сработок CSV",
        "description": "Выгрузка журнала: ид_события, ид_канала, дата, время, тревожное, значение.",
        "format": "csv",
        "config": {
            "delimiter": ",",
            "header": True,
            "fields": {
                "channel": "ид_канала_данных",
                "ts": ["дата", "время"],
                "ts_format": "%Y-%m-%d %H:%M:%S",
                "value": "значение_датчика",
                "alarm": "тревожное",
                "event_id": "ид_события",
            },
        },
        "sample": "ид_события,ид_канала_данных,дата,время,тревожное,значение_датчика\n"
        "3008235019,56682,2026-06-24,12:15:00,f,25.40\n3008235020,183582,2026-06-24,12:16:00,t,Тревога",
    },
    {
        "code": "gateway-multi",
        "name": "Шлюз: несколько измерений в пакете",
        "description": "Беспроводной шлюз шлёт пакет с устройством и массивом измерений; каждое — свой канал.",
        "format": "json",
        "config": {
            "items": "readings",
            "fields": {
                "ts": "^.time",
                "ts_format": "epoch_s",
                "channel": "kind",
                "channel_map": {"temp": 80000001, "hum": 80000002, "ch4": 80000003},
                "value": "v",
            },
        },
        "sample": '{"device": "GW-17", "time": 1782292500, "readings": '
        '[{"kind": "temp", "v": 23.4}, {"kind": "hum", "v": 81}, {"kind": "ch4", "v": 0.02}]}',
    },
    {
        "code": "text-line",
        "name": "Текстовая строка «канал;дата время;значение»",
        "description": "Контроллер пишет строки в последовательный порт или файл.",
        "format": "regex",
        "config": {
            "pattern": r"^(?P<channel>\d+);(?P<ts>\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}:\d{2});(?P<value>[^;]*)(;(?P<alarm>[01]))?$",
            "fields": {
                "channel": "channel",
                "ts": "ts",
                "ts_format": "%d.%m.%Y %H:%M:%S",
                "value": "value",
                "alarm": "alarm",
            },
        },
        "sample": "56682;24.06.2026 12:15:00;25,40;0\n183582;24.06.2026 12:16:00;Тревога;1",
    },
    {
        "code": "mqtt-kv",
        "name": "Датчик MQTT: «T=21.3;H=45»",
        "description": "Компактная строка ключ=значение: ключи сопоставляются каналам, время — приёма.",
        "format": "regex",
        "config": {
            "pattern": r"^T=(?P<t>-?[\d.]+);H=(?P<h>[\d.]+)$",
            "fields": {},
            "measurements": [{"channel": "=80000001", "value": "t"}, {"channel": "=80000002", "value": "h"}],
        },
        "sample": "T=21.3;H=45",
    },
]

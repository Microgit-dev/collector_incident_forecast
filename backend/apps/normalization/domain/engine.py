"""
Движок нормализации: сырое значение канала любого формата → каноническое состояние.

Чистый Python без Django — используется и в потоковом консьюмере Kafka, и в офлайн-пайплайне
обучения (polars), и в тестах. Правила и профили хранятся в БД (редактируются в админке)
и передаются сюда уже скомпилированными (см. selectors.compiled_registry).

Почему так: у заказчика нет формального кода отказа, а значения одного поля смешивают
числа, текстовые состояния, служебные коды производителей и артефакты дат. Добавить новый
тип датчика = завести профиль и правила, без изменения кода.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum


class State(StrEnum):
    NORMAL = "normal"  # штатное состояние / показание в норме
    WARNING = "warning"  # показание выше порога предупреждения
    ALARM = "alarm"  # тревога по физическому событию (дым, газ, вода, проникновение)
    FAULT = "fault"  # неисправность датчика: код отказа, служебное значение, артефакт
    POWER_LOSS = "power_loss"  # обесточен / работа от батарей
    UNKNOWN = "unknown"  # «Неопределен» и нераспознанные значения
    EVENT = "event"  # рабочее событие без тревоги: включён/выключен, взят на охрану


class Quality(StrEnum):
    OK = "ok"
    EMPTY = "empty"
    EPOCH_ARTIFACT = "epoch_artifact"  # «01.01.1970 03:00:0x» — сбой даты, по заказчику = неисправность
    SENTINEL = "sentinel"  # служебный код производителя (-100, 255, -3276, -127…)
    OUT_OF_RANGE = "out_of_range"  # вне физически допустимого диапазона профиля
    UNEXPECTED_NUMERIC = "unexpected_numeric"
    UNMAPPED_TEXT = "unmapped_text"


class ValueKind(StrEnum):
    NUMERIC = "numeric"
    STATE = "state"
    MIXED = "mixed"


# Состояния, которые считаются тревожными для диспетчера
ALARMING_STATES = frozenset({State.ALARM, State.FAULT, State.POWER_LOSS})

_EPOCH_RE = re.compile(r"^01\.01\.1970\b")


@dataclass(frozen=True, slots=True)
class Rule:
    pattern: str
    state: State
    facet: str = "primary"
    is_regex: bool = False

    def matches(self, text_lower: str) -> bool:
        if self.is_regex:
            return re.search(self.pattern, text_lower, re.IGNORECASE) is not None
        return text_lower == self.pattern.lower()


@dataclass(frozen=True, slots=True)
class Profile:
    code: str
    value_kind: ValueKind = ValueKind.MIXED
    valid_min: float | None = None
    valid_max: float | None = None
    warn_threshold: float | None = None
    alarm_threshold: float | None = None
    # above — тревога при росте (газ, температура), below — при падении
    direction: str = "above"
    sentinels: frozenset[str] = frozenset()
    rules: tuple[Rule, ...] = ()


@dataclass(frozen=True, slots=True)
class Normalized:
    state: State
    numeric: float | None = None
    text: str | None = None
    facet: str = "primary"
    quality: Quality = Quality.OK
    flags: tuple[str, ...] = field(default=())

    @property
    def is_alarming(self) -> bool:
        return self.state in ALARMING_STATES


def parse_number(raw: str) -> float | None:
    try:
        return float(raw.replace(",", ".").replace(" ", ""))
    except ValueError:
        return None


def _canonical_sentinel(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(value)


def _classify_numeric(value: float, profile: Profile) -> tuple[State, Quality]:
    if _canonical_sentinel(value) in profile.sentinels:
        return State.FAULT, Quality.SENTINEL
    if profile.value_kind == ValueKind.STATE:
        return State.UNKNOWN, Quality.UNEXPECTED_NUMERIC
    if (profile.valid_min is not None and value < profile.valid_min) or (
        profile.valid_max is not None and value > profile.valid_max
    ):
        return State.FAULT, Quality.OUT_OF_RANGE

    def beyond(threshold: float | None) -> bool:
        if threshold is None:
            return False
        return value >= threshold if profile.direction == "above" else value <= threshold

    if beyond(profile.alarm_threshold):
        return State.ALARM, Quality.OK
    if beyond(profile.warn_threshold):
        return State.WARNING, Quality.OK
    return State.NORMAL, Quality.OK


def normalize(raw: str | None, profile: Profile, global_rules: tuple[Rule, ...] = ()) -> Normalized:
    """Главная точка входа. Правила профиля имеют приоритет над глобальными."""
    text = (raw or "").strip().strip('"')
    if not text:
        return Normalized(State.UNKNOWN, quality=Quality.EMPTY)

    if _EPOCH_RE.match(text):
        return Normalized(State.FAULT, text=text, quality=Quality.EPOCH_ARTIFACT)

    number = parse_number(text)
    if number is not None:
        state, quality = _classify_numeric(number, profile)
        return Normalized(state, numeric=number, quality=quality)

    lowered = text.lower()
    for rule in (*profile.rules, *global_rules):
        if rule.matches(lowered):
            return Normalized(rule.state, text=text, facet=rule.facet)
    return Normalized(State.UNKNOWN, text=text, quality=Quality.UNMAPPED_TEXT)

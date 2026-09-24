"""
Правила-индикаторы риска пожара и несанкционированного доступа (чистые функции).

Почему правила, а не модель: тревоги дымовых извещателей и охраны в журналах в основном ложные
(«мигающие» извещатели, работы с нарядом-допуском), подтверждённых пожаров и проникновений в
данных нет. Модель на таких метках научилась бы предсказывать ложные срабатывания. Правила
собирают подтверждения из разных источников и дают индекс риска 0–1 с объяснением по факторам.
Формулировка — «риск», а не «факт»: решение принимает диспетчер.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

NIGHT = set(range(22, 24)) | set(range(0, 6))
TEMP_RISE = 5.0  # °C к суточной медиане — «быстрый рост»
TEMP_ALARM = 40.0  # °C — порог тревоги профиля температуры
PICKET_NEIGHBOURS = 2.0


@dataclass(frozen=True, slots=True)
class ChannelWindow:
    """Канал объекта за окно перед моментом оценки."""

    channel_id: int
    sensor_type: str
    name: str = ""
    picket: float | None = None
    alarms: int = 0
    last_raw: str = ""
    numeric_now: float | None = None  # среднее за последние 30 минут
    numeric_base: float | None = None  # медиана за сутки
    health: int | None = None
    fault_history: int = 0


@dataclass(frozen=True, slots=True)
class ScenarioContext:
    local_time: datetime
    works_in_progress: int = 0
    guard_armed: bool | None = None  # режим охраны объекта по последнему сообщению
    guard_changed_recently: bool = False  # охрану снимали/ставили за последний час


@dataclass
class Assessment:
    score: float
    factors: list[dict] = field(default_factory=list)
    channel_id: int | None = None  # главный канал для карточки

    def add(self, title: str, weight: float, value=None) -> None:
        self.factors.append(
            {"feature": "rule", "title": title, "value": value, "contribution": round(weight, 3)}
        )


FIRE_TYPES = {"Датчик дыма", "Тепловой датчик", "Ручной извещатель"}
TEMP_TYPES = {"Датчик температуры", "Тепловой датчик"}
INTRUSION_CONTACT = {"КД Дверь", "КД Люк", "КД АВ", "9-секционный люк", "Стекло"}
INTRUSION_MOTION = {"Датчик движения"}


def _flaky(c: ChannelWindow) -> bool:
    return c.fault_history >= 3 or (c.health is not None and c.health < 60)


def _close(a: ChannelWindow, b: ChannelWindow) -> bool:
    return a.picket is not None and b.picket is not None and abs(a.picket - b.picket) <= PICKET_NEIGHBOURS


def fire_risk(channels: list[ChannelWindow], ctx: ScenarioContext) -> Assessment:
    alarming = [c for c in channels if c.sensor_type in FIRE_TYPES and c.alarms > 0]
    result = Assessment(0.0)
    smoke = [c for c in alarming if c.sensor_type == "Датчик дыма"]
    manual = [c for c in alarming if c.sensor_type == "Ручной извещатель"]
    heat = [c for c in alarming if c.sensor_type == "Тепловой датчик"]
    if smoke:
        result.score += 0.35 + min(0.3, 0.15 * (len(smoke) - 1))
        result.add(
            f"Сработали дымовые извещатели: {len(smoke)}",
            0.35 + min(0.3, 0.15 * (len(smoke) - 1)),
            len(smoke),
        )
    if manual:
        result.score += 0.4
        result.add("Нажат ручной пожарный извещатель", 0.4, len(manual))
    if heat:
        result.score += 0.3
        result.add(f"Сработали тепловые извещатели: {len(heat)}", 0.3, len(heat))
    hot = [
        c
        for c in channels
        if c.sensor_type in TEMP_TYPES and c.numeric_now is not None and c.numeric_base is not None
    ]
    rising = [c for c in hot if c.numeric_now - c.numeric_base >= TEMP_RISE]
    if rising:
        top = max(rising, key=lambda c: c.numeric_now - c.numeric_base)
        delta = round(top.numeric_now - top.numeric_base, 1)
        result.score += 0.25
        result.add(f"Рост температуры на {delta} °C к суточной норме («{top.name}»)", 0.25, delta)
        # рост температуры рядом со сработавшим извещателем — независимое подтверждение
        if any(_close(top, a) for a in alarming):
            result.score += 0.15
            result.add("Рост температуры рядом со сработавшим извещателем", 0.15)
    over = [c for c in hot if c.numeric_now >= TEMP_ALARM]
    if over:
        result.score += 0.15
        result.add(f"Температура выше {TEMP_ALARM:g} °C", 0.15, round(max(c.numeric_now for c in over), 1))
    if len(alarming) >= 2 and any(_close(a, b) for i, a in enumerate(alarming) for b in alarming[i + 1 :]):
        result.score += 0.15
        result.add("Соседние извещатели в пределах 2 пикетов подтверждают друг друга", 0.15)
    if alarming and all(_flaky(c) for c in alarming):
        result.score *= 0.6
        result.add("Сработавшие извещатели ненадёжны (история сбоев, низкое качество данных)", -0.4)
    if ctx.works_in_progress:
        result.score *= 0.7
        result.add(f"На объекте работы (заявок в работе: {ctx.works_in_progress})", -0.3)
    result.score = round(min(result.score, 0.99), 3)
    main = manual or heat or smoke or rising
    result.channel_id = main[0].channel_id if main else None
    return result


def intrusion_risk(channels: list[ChannelWindow], ctx: ScenarioContext) -> Assessment:
    contacts = [c for c in channels if c.sensor_type in INTRUSION_CONTACT and c.alarms > 0]
    motion = [c for c in channels if c.sensor_type in INTRUSION_MOTION and c.alarms > 0]
    result = Assessment(0.0)
    if not contacts and not motion:
        return result
    if contacts:
        result.score += 0.3
        result.add(f"Контакт открыт при охране: {len(contacts)} (двери, люки, выходы)", 0.3, len(contacts))
    if motion:
        result.score += 0.25
        result.add(f"Движение при охране: {len(motion)}", 0.25, len(motion))
    if contacts and motion:
        result.score += 0.2
        result.add("Контакт и движение вместе — сценарий входа на объект", 0.2)
    if ctx.guard_armed:
        result.score += 0.25
        result.add("Объект на охране", 0.25)
    if ctx.local_time.hour in NIGHT or ctx.local_time.weekday() >= 5:
        result.score += 0.15
        result.add("Ночь или выходной", 0.15)
    repeats = sum(c.alarms for c in contacts + motion)
    if repeats >= 3:
        result.score += 0.1
        result.add(f"Повторные срабатывания за час: {repeats}", 0.1, repeats)
    if ctx.works_in_progress or ctx.guard_changed_recently or ctx.guard_armed is False:
        result.score *= 0.4
        reason = (
            f"заявок в работе: {ctx.works_in_progress}"
            if ctx.works_in_progress
            else "охрану недавно снимали или ставили"
            if ctx.guard_changed_recently
            else "объект снят с охраны"
        )
        result.add(f"Вероятен санкционированный доступ ({reason})", -0.6)
    result.score = round(min(result.score, 0.99), 3)
    main = contacts or motion
    result.channel_id = main[0].channel_id
    return result


def level(score: float) -> str:
    """Уровни индекса правил фиксированы: индекс — не вероятность, калибровать его не на чем."""
    if score >= 0.75:
        return "critical"
    if score >= 0.5:
        return "high"
    if score >= 0.3:
        return "medium"
    return "low"

"""
Корреляция сигналов: контур риска, тип технического эпизода и гипотезы первопричины.

Чистые функции без БД. Поток СМВУ за июнь 2026 года — 90 тыс. переходов в тревожные
и технические состояния (до 644 в минуту на объект). Склейка по объекту и контуру
с паузой не больше 30 минут даёт около 2,1 тыс. эпизодов — в 43 раза меньше карточек.

Два контура:
    физический — авария, угроза жизни: пожар, газ, вода, проникновение, аномальная температура;
    технический — угроза способности видеть объект: датчик, связь, питание, оборудование.
Физические угрозы разных типов не склеиваются: пожар и проникновение — разные карточки
с разными действиями. Технические склеиваются: при пропадании питания шкафа «неисправны»
десятки каналов сразу, и диспетчеру нужна одна карточка «потеря питания», а не сорок.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

PHYSICAL = "physical"
TECHNICAL = "technical"
PHYSICAL_TYPES = {"fire", "gas", "flood", "intrusion", "temperature"}

WORK_HOURS = range(8, 18)
BURST_SECONDS = 60  # каналы, ушедшие в сбой за минуту, — признак общей причины
PPR_DETECTORS = 5  # столько пожарных извещателей за PPR_WINDOW_S в рабочее время — это ППР
PPR_WINDOW_S = 600


def contour(incident_type: str) -> str:
    return PHYSICAL if incident_type in PHYSICAL_TYPES else TECHNICAL


@dataclass(frozen=True, slots=True)
class Signal:
    channel_id: int | None
    state: str  # alarm, fault, power_loss, unknown, silent, forecast
    ts: datetime
    sensor_type: str = ""
    name: str = ""
    picket: float | None = None
    health: int | None = None  # Data Health Score канала
    fault_history: int = 0  # неисправностей канала за 90 суток до эпизода
    numeric: float | None = None


@dataclass(frozen=True, slots=True)
class Context:
    """Обстановка вокруг эпизода, которую не видно по самим сигналам."""

    local_time: datetime
    works_in_progress: int = 0  # заявки «в работе» на объекте
    node_channels: int = 0  # всего каналов на объекте


@dataclass(frozen=True, slots=True)
class Hypothesis:
    code: str
    title: str
    weight: float
    evidence: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "title": self.title,
            "weight": round(self.weight, 3),
            "evidence": self.evidence,
        }


# ---------- тип технического эпизода ----------

_PROCESS_TYPES = {"Состояние насоса", "Состояние вентилятора"}


def technical_type(signals: list[Signal]) -> str:
    """Тип по составу сигналов: питание и связь важнее, чем «отказ датчика» каждого канала."""
    states = Counter(s.state for s in signals)
    total = sum(states.values()) or 1
    if states["power_loss"] / total >= 0.3:
        return "power"
    if (states["unknown"] + states["silent"]) / total >= 0.5:
        return "communication"
    process = sum(s.sensor_type in _PROCESS_TYPES for s in signals)
    if process / total >= 0.5:
        return "equipment"
    return "sensor_failure"


# ---------- гипотезы ----------


def _burst(signals: list[Signal]) -> int:
    """Наибольшее число разных каналов, ушедших в сбой в пределах одной минуты."""
    times = sorted((s.ts, s.channel_id) for s in signals if s.channel_id)
    best, start = 0, 0
    for end in range(len(times)):
        while (times[end][0] - times[start][0]).total_seconds() > BURST_SECONDS:
            start += 1
        best = max(best, len({c for _, c in times[start : end + 1]}))
    return best


def _work_time(ctx: Context) -> bool:
    return ctx.local_time.weekday() < 5 and ctx.local_time.hour in WORK_HOURS


def _normalize(items: list[Hypothesis], top: int = 3) -> list[Hypothesis]:
    total = sum(h.weight for h in items) or 1
    ranked = sorted(items, key=lambda h: -h.weight)[:top]
    return [Hypothesis(h.code, h.title, h.weight / total, h.evidence) for h in ranked]


def hypotheses(incident_type: str, signals: list[Signal], ctx: Context) -> list[Hypothesis]:
    if not signals:
        return []
    if contour(incident_type) == TECHNICAL:
        return _technical(signals, ctx)
    return _physical(incident_type, signals, ctx)


def _technical(signals: list[Signal], ctx: Context) -> list[Hypothesis]:
    channels = {s.channel_id for s in signals if s.channel_id}
    n = len(channels)
    states = Counter(s.state for s in signals)
    total = sum(states.values())
    burst = _burst(signals)
    share_of_node = n / ctx.node_channels if ctx.node_channels else 0
    result = []

    power = states["power_loss"] / total
    if power or (burst >= 5 and share_of_node >= 0.3):
        ev = []
        if power:
            ev.append(f"«Обесточен» у {states['power_loss']} сигналов из {total}")
        if burst >= 5:
            ev.append(f"{burst} каналов ушли в сбой в пределах минуты")
        result.append(
            Hypothesis(
                "power", "Потеря питания объекта или шкафа", 0.2 + 1.5 * power + 0.1 * min(burst, 10), ev
            )
        )

    comm = (states["unknown"] + states["silent"]) / total
    if comm or (burst >= 5 and not power):
        ev = (
            [f"«Не определено» или молчание у {states['unknown'] + states['silent']} сигналов"]
            if comm
            else []
        )
        if burst >= 5 and not power:
            ev.append(f"{burst} каналов одновременно без обесточивания — похоже на обрыв опроса")
        result.append(
            Hypothesis(
                "communication",
                "Потеря связи с контроллером (опрос, линия, коммутатор)",
                0.2 + 1.2 * comm + 0.08 * min(burst, 10),
                ev,
            )
        )

    if 2 <= n <= 12 and burst >= 2 and not power:
        pickets = sorted(s.picket for s in signals if s.picket is not None)
        compact = len(pickets) >= 2 and pickets[-1] - pickets[0] <= 5
        ev = [
            f"{n} каналов одной линии"
            + (f" на участке ПК{pickets[0]:g}–ПК{pickets[-1]:g}" if compact else "")
        ]
        result.append(
            Hypothesis(
                "module",
                "Неисправность модуля или шлейфа (общая линия датчиков)",
                0.5 + (0.4 if compact else 0),
                ev,
            )
        )

    if n <= 3:
        worst = max(signals, key=lambda s: s.fault_history)
        low_health = [s for s in signals if s.health is not None and s.health < 60]
        ev = []
        if worst.fault_history:
            ev.append(f"У канала «{worst.name}» {worst.fault_history} неисправностей за 90 суток")
        if low_health:
            ev.append(f"Низкий балл качества данных: {', '.join(str(s.health) for s in low_health[:3])}")
        weight = 0.6 + 0.3 * min(worst.fault_history, 5) / 5 + (0.2 if low_health else 0)
        result.append(
            Hypothesis(
                "sensor",
                "Отказ отдельного датчика",
                weight,
                ev or ["Сбой одного-двух каналов без признаков общей причины"],
            )
        )

    if ctx.works_in_progress or _work_time(ctx):
        ev = []
        if ctx.works_in_progress:
            ev.append(f"На объекте заявок в работе: {ctx.works_in_progress}")
        if _work_time(ctx):
            ev.append("Рабочее время")
        result.append(
            Hypothesis(
                "works",
                "Плановые или ремонтные работы на объекте",
                0.25 + 0.6 * bool(ctx.works_in_progress),
                ev,
            )
        )

    if not result:
        result.append(Hypothesis("unknown", "Причина не ясна — нужна проверка", 1.0, []))
    return _normalize(result)


def _physical(incident_type: str, signals: list[Signal], ctx: Context) -> list[Hypothesis]:
    channels = {s.channel_id for s in signals if s.channel_id}
    n = len(channels)
    healthy = [s for s in signals if s.health is None or s.health >= 60]
    flaky = [s for s in signals if s.fault_history >= 3 or (s.health is not None and s.health < 60)]
    night = not _work_time(ctx)
    result = []

    real = {
        "fire": ("fire", "Возгорание или задымление"),
        "gas": ("gas", "Реальная загазованность"),
        "flood": ("flood", "Поступление воды (подтопление)"),
        "intrusion": ("intrusion", "Несанкционированное проникновение"),
        "temperature": ("temperature", "Аномальная температура: перегрев или переохлаждение участка"),
    }[incident_type]
    ev = []
    weight = 0.35
    if n >= 2:
        ev.append(f"Подтверждают {n} независимых каналов")
        weight += 0.25 * min(n - 1, 3)
    if incident_type == "intrusion" and night:
        ev.append("Нерабочее время")
        weight += 0.3
    if incident_type == "gas":
        peak = max((s.numeric for s in signals if s.numeric is not None), default=None)
        if peak is not None:
            ev.append(f"Концентрация до {peak:g} % метана")
            weight += 0.4 if peak >= 1.0 else 0.1
    if incident_type == "temperature":
        values = [s.numeric for s in signals if s.numeric is not None]
        if values:
            ev.append(f"Температура от {min(values):g} до {max(values):g} °C")
    if healthy and len(healthy) == len(signals):
        ev.append("Каналы с хорошим качеством данных")
        weight += 0.1
    result.append(Hypothesis(real[0], real[1], weight, ev))

    if n == 1 or flaky:
        ev = []
        if n == 1:
            ev.append("Сработал один канал, соседи молчат")
        if flaky:
            ev.append(f"Канал с историей сбоев или низким качеством данных ({len(flaky)})")
        false_title = {
            "fire": "Ложное срабатывание: пыль, конденсат, неисправность извещателя",
            "gas": "Ложное срабатывание: дрейф или неисправность сигнализатора",
            "flood": "Ложное срабатывание датчика затопления",
            "intrusion": "Ложное срабатывание охранного извещателя",
            "temperature": "Сбой датчика температуры или местный нагрев (оборудование, солнце у входа)",
        }[incident_type]
        result.append(Hypothesis("false", false_title, 0.3 + 0.3 * (n == 1) + 0.3 * bool(flaky), ev))

    # ППР по заказчику: 5 и больше пожарных извещателей объекта за 10 минут в рабочее время —
    # плановая проверка извещателей, а не пожар
    times = [s.ts for s in signals]
    ppr = (
        incident_type == "fire"
        and n >= PPR_DETECTORS
        and _work_time(ctx)
        and (max(times) - min(times)).total_seconds() <= PPR_WINDOW_S
    )
    if ctx.works_in_progress or (_work_time(ctx) and incident_type in {"intrusion", "fire"}):
        title = {
            "intrusion": "Санкционированный доступ (наряд-допуск, бригада)",
            "fire": "ППР: плановая проверка извещателей" if ppr else "Огневые или пыльные работы на объекте",
        }.get(incident_type, "Работы на объекте")
        ev = []
        if ppr:
            ev.append(
                f"Сработали {n} извещателей за 10 минут в рабочее время — так идёт проверка по графику ППР"
            )
        if ctx.works_in_progress:
            ev.append(f"На объекте заявок в работе: {ctx.works_in_progress}")
        if _work_time(ctx):
            ev.append("Рабочее время")
        result.append(Hypothesis("works", title, 0.2 + 0.7 * bool(ctx.works_in_progress) + 1.3 * ppr, ev))

    return _normalize(result)

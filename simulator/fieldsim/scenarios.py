"""
Сценарии: последовательность изменений на устройствах объекта с задержками (в секундах реального
времени при скорости 1). Устройства подбираются по типу и близости к пикету, поэтому любой сценарий
работает на любом объекте, где есть нужные датчики, — и на полигоне, и на справочнике заказчика.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .vocab import ALARM, FAULT, NORMAL, POWER, SILENT, UNKNOWN

if TYPE_CHECKING:
    from .engine import Engine, Step


@dataclass(frozen=True)
class Scenario:
    code: str
    title: str
    description: str
    build: Callable[[Engine, int, float | None, float], list[Step]]
    uses_picket: bool = True


def _step(delay: float, title: str, action) -> Step:
    from .engine import Step

    return Step(delay, title, action)


def _picket(engine: Engine, object_id: int, picket: float | None) -> float | None:
    if picket is not None:
        return float(picket)
    span = engine.catalog.picket_range(object_id)
    return round(engine.rng.uniform(*span)) if span else None


def _need(found: list, what: str) -> list:
    if not found:
        raise ValueError(f"на объекте нет устройств: {what}")
    return found


def fire(engine: Engine, object_id: int, picket: float | None, speed: float = 1.0) -> list[Step]:
    cat = engine.catalog
    pk = _picket(engine, object_id, picket)
    temp = cat.find(object_id, "Датчик температуры", pk, 1)
    smoke = _need(cat.find(object_id, "Датчик дыма", pk, 2), "датчики дыма")
    heat = cat.find(object_id, "Тепловой датчик", pk, 1)
    steps = []
    if temp:
        t = temp[0]
        steps.append(_step(0, f"Растёт температура: {t.name}", lambda: engine.ramp(t.id, 52, 240 / speed)))
    steps.append(_step(60, f"Дым: {smoke[0].name}", lambda: engine.set_mode(smoke[0].id, ALARM)))
    if heat:
        steps.append(_step(60, f"Сработал тепловой: {heat[0].name}", lambda: engine.set_mode(heat[0].id, ALARM)))
    if len(smoke) > 1:
        steps.append(_step(60, f"Дым у соседнего: {smoke[1].name}", lambda: engine.set_mode(smoke[1].id, ALARM)))
    return steps


def gas(engine: Engine, object_id: int, picket: float | None, speed: float = 1.0) -> list[Step]:
    cat = engine.catalog
    pk = _picket(engine, object_id, picket)
    sensors = _need(cat.find(object_id, "Газовый датчик", pk, 2), "газовые датчики")
    main = sensors[0]
    steps = [
        _step(0, f"Метан растёт до 0,7 %: {main.name}", lambda: engine.ramp(main.id, 0.7, 180 / speed)),
        _step(180, f"Метан выше 1 %: {main.name}", lambda: engine.ramp(main.id, 1.4, 120 / speed)),
    ]
    if len(sensors) > 1:
        other = sensors[1]
        steps.append(
            _step(60, f"Метан у соседнего до 0,6 %: {other.name}", lambda: engine.ramp(other.id, 0.6, 120 / speed))
        )
    return steps


def flood(engine: Engine, object_id: int, picket: float | None, speed: float = 1.0) -> list[Step]:
    cat = engine.catalog
    pk = _picket(engine, object_id, picket)
    pumps = _need(cat.find(object_id, "Состояние насоса", pk, 2), "насосы")
    sensor = cat.find(object_id, "Датчик затопления", pk, 1)
    phase = cat.find(object_id, "Состояние фазы", pk, 1)
    steps = [_step(0, f"Включился насос: {pumps[0].name}", lambda: engine.set_op(pumps[0].id, True))]
    if len(pumps) > 1:
        steps.append(_step(90, f"Включился второй насос: {pumps[1].name}", lambda: engine.set_op(pumps[1].id, True)))
    if sensor:
        steps.append(_step(90, f"Затопление: {sensor[0].name}", lambda: engine.set_mode(sensor[0].id, ALARM)))
    steps.append(_step(30, f"Насос затоплен: {pumps[0].name}", lambda: engine.set_mode(pumps[0].id, ALARM)))
    if phase:
        steps.append(_step(60, f"Пропало питание: {phase[0].name}", lambda: engine.set_mode(phase[0].id, POWER)))
    return steps


def intrusion(engine: Engine, object_id: int, picket: float | None, speed: float = 1.0) -> list[Step]:
    """
    Нарушитель вскрывает люк у пикета и идёт вдоль коллектора: двери и датчики движения срабатывают
    по порядку пикетов в сторону дальнего конца объекта — платформа строит по ним маршрут.
    """
    cat = engine.catalog
    pk = _picket(engine, object_id, picket)
    hatch = cat.find(object_id, "КД Люк", pk, 1)
    door = cat.find(object_id, "КД Дверь", pk, 1)
    _need(hatch + door, "охранные контакты")
    entry = hatch[0] if hatch else door[0]
    start = entry.picket if entry.picket is not None else pk
    span = cat.picket_range(object_id)
    # идёт к дальнему концу объекта от места входа
    forward = span is None or start is None or (span[1] - start) >= (start - span[0])
    path = [
        d
        for d in cat.devices_under(object_id)
        if d.sensor_type in ("Датчик движения", "КД Дверь", "КД АВ")
        and d is not entry
        and d.picket is not None
        and start is not None
        and ((d.picket >= start) if forward else (d.picket <= start))
    ]
    path.sort(key=lambda d: abs(d.picket - start))
    steps = [_step(0, "Объект поставлен на охрану", lambda: engine.set_guard(object_id, True))]
    steps.append(_step(30, f"Вскрыт: {entry.name}", lambda: engine.set_mode(entry.id, ALARM)))
    for d in path[:6]:
        verb = "Движение" if d.sensor_type == "Датчик движения" else "Открыто"
        steps.append(_step(40, f"{verb}: {d.name}", lambda d=d: engine.set_mode(d.id, ALARM)))
    return steps


def temperature(engine: Engine, object_id: int, picket: float | None, speed: float = 1.0) -> list[Step]:
    """Аномальная температура без дыма: прорыв теплосети или перегрев кабелей у пикета."""
    cat = engine.catalog
    pk = _picket(engine, object_id, picket)
    temps = _need(cat.find(object_id, "Датчик температуры", pk, 2), "датчики температуры")
    main = temps[0]
    steps = [_step(0, f"Температура растёт до 58 °C: {main.name}", lambda: engine.ramp(main.id, 58, 300 / speed))]
    if len(temps) > 1:
        other = temps[1]
        steps.append(_step(180, f"У соседнего до 45 °C: {other.name}", lambda: engine.ramp(other.id, 45, 240 / speed)))
    return steps


def ppr(engine: Engine, object_id: int, picket: float | None, speed: float = 1.0) -> list[Step]:
    """
    ППР (планово-предупредительные работы): бригада в рабочее время по очереди проверяет пожарные
    извещатели вдоль коллектора — пять и больше сработок за 10 минут, каждая сразу сбрасывается.
    Учит отличать проверку извещателей от пожара.
    """
    cat = engine.catalog
    pk = _picket(engine, object_id, picket)
    smoke = _need(cat.find(object_id, "Датчик дыма", pk, 6), "датчики дыма")
    smoke.sort(key=lambda d: d.picket if d.picket is not None else 0)
    steps = [_step(0, "Охрана снята: бригада на ППР", lambda: engine.set_guard(object_id, False))]
    for i, d in enumerate(smoke):
        steps.append(
            _step(0 if i == 0 else 60, f"Проверка извещателя: {d.name}", lambda d=d: engine.set_mode(d.id, ALARM))
        )
        steps.append(_step(20, f"Сброс: {d.name}", lambda d=d: engine.set_mode(d.id, NORMAL)))
    return steps


def authorized(engine: Engine, object_id: int, picket: float | None, speed: float = 1.0) -> list[Step]:
    """Работы по наряду-допуску: охрана снята, двери и движение — рабочая активность, не тревога."""
    cat = engine.catalog
    pk = _picket(engine, object_id, picket)
    door = _need(cat.find(object_id, "КД Дверь", pk, 1), "двери")[0]
    motion = cat.find(object_id, "Датчик движения", pk, 1)
    steps = [
        _step(0, "Охрана снята (наряд-допуск)", lambda: engine.set_guard(object_id, False)),
        _step(20, f"Бригада открыла: {door.name}", lambda: engine.set_mode(door.id, ALARM)),
    ]
    if motion:
        steps.append(_step(20, f"Движение бригады: {motion[0].name}", lambda: engine.set_mode(motion[0].id, ALARM)))
    steps.append(_step(120, f"Дверь закрыта: {door.name}", lambda: engine.set_mode(door.id, NORMAL)))
    return steps


def power_loss(engine: Engine, object_id: int, picket: float | None, speed: float = 1.0) -> list[Step]:
    cat = engine.catalog
    ups = cat.find(object_id, "ИБП", None, 1)
    part = _power_part(engine, object_id)
    steps = []
    if ups:
        steps.append(_step(0, f"ИБП перешёл на батареи: {ups[0].name}", lambda: engine.set_mode(ups[0].id, POWER)))
    name = cat.objects[part].name
    steps.append(_step(45, f"Обесточен шкаф: {name} — все каналы разом", lambda: engine.cascade(part, POWER)))
    steps.append(_step(240, f"Питание восстановлено: {name}", lambda: engine.restore(part)))
    if ups:
        steps.append(_step(5, f"ИБП на сети: {ups[0].name}", lambda: engine.set_mode(ups[0].id, NORMAL)))
    return steps


def _power_part(engine: Engine, object_id: int) -> int:
    """Часть объекта, которая «теряет питание»: пожарная (ПС), если есть, иначе сам объект."""
    cat = engine.catalog
    for oid in cat.subtree(object_id):
        if cat.objects[oid].name.endswith(" ПС"):
            return oid
    return object_id


def sensor_failure(engine: Engine, object_id: int, picket: float | None, speed: float = 1.0) -> list[Step]:
    """Деградация датчика: дребезг с учащением, затем служебный код и отказ."""
    cat = engine.catalog
    pk = _picket(engine, object_id, picket)
    device = _need(
        cat.find(object_id, "Газовый датчик", pk, 1) or cat.find(object_id, "Датчик дыма", pk, 1), "датчики"
    )[0]
    steps = []
    for i, gap in enumerate((0, 90, 60, 40, 25)):
        steps.append(_step(gap, f"Сбой {i + 1}: {device.name}", lambda: engine.set_mode(device.id, FAULT)))
        steps.append(_step(10, f"Восстановился: {device.name}", lambda: engine.set_mode(device.id, NORMAL)))
    steps.append(_step(30, f"Служебный код -100: {device.name}", lambda: engine.sentinel(device.id)))
    steps.append(_step(20, f"Отказ: {device.name}", lambda: engine.set_mode(device.id, FAULT)))
    return steps


def comm_loss(engine: Engine, object_id: int, picket: float | None, speed: float = 1.0) -> list[Step]:
    """Потеря связи с контроллером: каналы уходят в «Неопределен», затем молчат, затем возвращаются."""
    part = _power_part(engine, object_id)
    name = engine.catalog.objects[part].name
    return [
        _step(0, f"Нет ответа контроллера: {name}", lambda: engine.cascade(part, UNKNOWN)),
        _step(30, f"Каналы молчат: {name}", lambda: engine.cascade(part, SILENT)),
        _step(300, f"Связь восстановлена: {name}", lambda: engine.restore(part)),
    ]


def restore(engine: Engine, object_id: int, picket: float | None, speed: float = 1.0) -> list[Step]:
    return [_step(0, "Всё в норму, охрана снята", lambda: engine.restore(object_id))]


SCENARIOS: dict[str, Scenario] = {
    s.code: s
    for s in [
        Scenario("fire", "Пожар", "Рост температуры, дым, тепловой извещатель, дым у соседнего пикета", fire),
        Scenario(
            "gas", "Загазованность", "Метан у пикета растёт до 0,7 %, затем выше 1 %; соседний датчик — до 0,6 %", gas
        ),
        Scenario(
            "flood", "Подтопление", "Насосы АНС включаются, датчик затопления, насос затоплен, пропало питание", flood
        ),
        Scenario(
            "intrusion",
            "Проникновение",
            "Объект на охране, вскрыт люк, нарушитель идёт вдоль коллектора: двери и движение по пикетам",
            intrusion,
        ),
        Scenario(
            "temperature",
            "Аномальная температура",
            "Без дыма: у пикета до 58 °C, у соседнего до 45 °C (теплосеть, кабели)",
            temperature,
        ),
        Scenario(
            "ppr",
            "ППР: проверка извещателей",
            "Бригада по очереди проверяет 5–6 дымовых извещателей, каждый сразу сбрасывается",
            ppr,
        ),
        Scenario(
            "authorized",
            "Работы по наряду",
            "Охрана снята, дверь и движение — рабочая активность без тревоги (учит отличать от НСД)",
            authorized,
        ),
        Scenario(
            "power",
            "Обесточивание",
            "ИБП на батареях, затем все каналы пожарной части разом; через 4 мин — восстановление",
            power_loss,
            False,
        ),
        Scenario("sensor", "Отказ датчика", "Дребезг с учащением, служебный код −100, отказ", sensor_failure),
        Scenario(
            "comm", "Потеря связи", "Каналы уходят в «Неопределен», молчат 5 минут, возвращаются", comm_loss, False
        ),
        Scenario("restore", "Восстановить всё", "Все каналы объекта в норму, охрана снята", restore, False),
    ]
}

"""
Словарь СМВУ: как устройство каждого типа сообщает о своём состоянии.

Значения взяты из журналов заказчика (те же строки, те же флаги «тревожное»), поэтому платформа
нормализует поток симулятора теми же профилями и правилами, что и боевой.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Режимы канала в симуляторе
NORMAL = "normal"
ALARM = "alarm"
FAULT = "fault"
DISABLED = "disabled"  # «Отключено устройство»
POWER = "power"  # обесточен / питание от батарей
UNKNOWN = "unknown"
SILENT = "silent"  # канал перестал выходить на связь

MODES = {
    NORMAL: "Норма",
    ALARM: "Тревога",
    FAULT: "Неисправен",
    DISABLED: "Отключено",
    POWER: "Обесточен",
    UNKNOWN: "Не определено",
    SILENT: "Нет связи",
}

# Сообщения, общие для всех типов
COMMON = {
    FAULT: ("Неисправен", True),
    DISABLED: ("Отключено устройство", True),
    UNKNOWN: ("Неопределен", False),
    POWER: ("Обесточен", True),
}
SENTINEL = "-100"  # служебный код производителя: платформа по заказчику считает его неисправностью
EPOCH = "01.01.1970 03:00:00"  # артефакт даты — тоже неисправность


@dataclass(frozen=True)
class Kind:
    """Поведение типа датчика."""

    code: str
    title: str
    states: dict[str, tuple[str, bool]] = field(default_factory=dict)
    # Числовые датчики: базовое значение, шум, период опроса (с), порог тревоги
    numeric: tuple[float, float, int, float] | None = None
    # Охранные контакты: тревожны, только когда объект под охраной (иначе — рабочая активность)
    guarded: bool = False
    # Исполнительные устройства: включён / выключен
    operation: bool = False
    heartbeat_s: int = 1800

    def message(self, mode: str) -> tuple[str, bool]:
        return self.states.get(mode) or COMMON.get(mode) or self.states[NORMAL]

    @property
    def modes(self) -> list[str]:
        base = [NORMAL, ALARM] if ALARM in self.states or self.numeric else [NORMAL]
        return [*base, FAULT, DISABLED, POWER, UNKNOWN, SILENT]


def _discrete(code, title, alarm=None, normal=("Норма", False), guarded=False, **extra) -> Kind:
    states = {NORMAL: normal}
    if alarm:
        states[ALARM] = alarm
    states.update(extra.pop("states", {}))
    return Kind(code, title, states, guarded=guarded, **extra)


KINDS: dict[str, Kind] = {
    k.title: k
    for k in [
        _discrete("smoke", "Датчик дыма", ("Обнаружен дым", True)),
        _discrete("heat", "Тепловой датчик", ("Не замкнут", True)),
        _discrete("manual", "Ручной извещатель", ("Не замкнут", True)),
        _discrete("uir", "Состояние УИР-Р", ("Рычаг сдернут", True)),
        Kind(
            "temperature",
            "Датчик температуры",
            {NORMAL: ("В норме от +3 до +40", False), ALARM: ("Температура выше 40ºC", True)},
            numeric=(21.0, 0.4, 120, 40.0),
        ),
        Kind(
            "gas",
            "Газовый датчик",
            {NORMAL: ("Норма", False), ALARM: ("Обнаружен газ", True)},
            numeric=(0.01, 0.01, 60, 1.0),
        ),
        _discrete("door", "КД Дверь", ("Не замкнут", True), guarded=True),
        _discrete("hatch", "КД Люк", ("Не замкнут", True), guarded=True),
        _discrete("hatch9", "9-секционный люк", ("Не замкнут", True), guarded=True),
        _discrete("contact", "КД АВ", ("Не замкнут", True), guarded=True),
        _discrete("glass", "Стекло", ("Не замкнут", True), guarded=True),
        _discrete("motion", "Датчик движения", ("Обнаружено движение", True), ("Движения нет", False), guarded=True),
        _discrete("guard", "Состояние охраны"),
        _discrete("phase", "Состояние фазы", normal=("Есть питание", False), states={POWER: ("Обесточен", False)}),
        _discrete(
            "ups",
            "ИБП",
            normal=("Питание от сети", False),
            states={POWER: ("Питание от батарей", True), FAULT: ("Батарея неисправна", False)},
        ),
        _discrete("pump", "Состояние насоса", ("Затоплен", True), operation=True),
        _discrete("fan", "Состояние вентилятора", operation=True),
        _discrete("switch", "Переключатель", operation=True),
        _discrete("flood", "Датчик затопления", ("Затоплен", True)),
    ]
}
GENERIC = _discrete("generic", "Прочее")


def kind_of(sensor_type: str) -> Kind:
    return KINDS.get(sensor_type, GENERIC)

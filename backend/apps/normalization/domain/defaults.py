"""
Стартовая таксономия, собранная из справочник_состояний.csv и ответов заказчика.
Засевается в БД командой bootstrap; дальше живёт и правится в админке.

Справочник заказчика грязный (состояния записаны не у своих типов, дубли, «35ºC1»),
поэтому текстовые правила глобальные, а профили задают только числовую семантику
и частные исключения.
"""

from .engine import Rule, State, ValueKind

# Служебные значения производителей: по заказчику трактуются как неисправность
DEFAULT_SENTINELS = ("-100", "255", "-3276", "-127", "-32768", "32767", "65535", "-999")

# (pattern, state, facet, is_regex)
GLOBAL_RULES: tuple[Rule, ...] = tuple(
    Rule(pattern, state, facet, is_regex)
    for pattern, state, facet, is_regex in [
        # Норма
        ("Норма", State.NORMAL, "primary", False),
        ("Дыма нет", State.NORMAL, "primary", False),
        ("Движения нет", State.NORMAL, "primary", False),
        ("Рычаг норма", State.NORMAL, "primary", False),
        ("Устройства на объекте исправны", State.NORMAL, "diagnostics", False),
        (r"^в норме", State.NORMAL, "temperature", True),
        # Неисправность датчика / устройства
        ("Неисправен", State.FAULT, "primary", False),
        ("Отключено устройство", State.FAULT, "primary", False),
        ("Много неисправных устройств", State.FAULT, "diagnostics", False),
        ("Батарея неисправна", State.FAULT, "power", False),
        ("Батарея разряжена", State.FAULT, "power", False),
        # Питание
        ("Обесточен", State.POWER_LOSS, "power", False),
        ("Питание от батарей", State.POWER_LOSS, "power", False),
        ("Питание от сети", State.NORMAL, "power", False),
        ("Есть питание", State.NORMAL, "power", False),
        # Физические тревоги
        ("Обнаружен дым", State.ALARM, "primary", False),
        ("Обнаружен газ", State.ALARM, "primary", False),
        ("Обнаружено движение", State.ALARM, "primary", False),
        (r"^движение (вверх|вниз|влево|вправо)$", State.ALARM, "primary", True),
        ("Затоплен", State.ALARM, "primary", False),
        ("Не замкнут", State.ALARM, "primary", False),
        ("Замкнут", State.ALARM, "primary", False),
        (r"рычаг(и)? сдернут|оба рычага сдернуты", State.ALARM, "primary", True),
        (r"^температура (выше|ниже)", State.ALARM, "temperature", True),
        ("Работают все насосы АНС", State.ALARM, "pumps", False),
        ("Работают все насосы в АНС", State.ALARM, "pumps", False),
        ("Включены все насосы АНС", State.ALARM, "pumps", False),
        # Неопределённость
        ("Неопределен", State.UNKNOWN, "primary", False),
        ("Не определено", State.UNKNOWN, "primary", False),
        # Рабочие события без тревоги
        ("Включен", State.EVENT, "operation", False),
        ("Выключен", State.EVENT, "operation", False),
        ("На охране", State.EVENT, "guard", False),
        ("Снято с охраны", State.EVENT, "guard", False),
        ("Разговор", State.EVENT, "intercom", False),
        ("Вызов", State.EVENT, "intercom", False),
    ]
)

# code -> параметры профиля; тип_датчика из справочника каналов маппится на профиль
DEFAULT_PROFILES: dict[str, dict] = {
    "gas_methane": {
        "name": "Газоанализатор (метан, % об.)",
        "value_kind": ValueKind.MIXED,
        "unit": "% об.",
        # 1% — порог тревоги заказчика, 5–15% — НКПР/ВКПР метана по паспортам
        "valid_min": 0.0,
        "valid_max": 100.0,
        "warn_threshold": 0.5,
        "alarm_threshold": 1.0,
        "expected_interval_s": 60,
        "sensor_types": ["Газовый датчик"],
    },
    "temperature": {
        "name": "Датчик температуры (°C)",
        "value_kind": ValueKind.MIXED,
        "unit": "°C",
        "valid_min": -40.0,
        "valid_max": 125.0,
        "warn_threshold": 35.0,
        "alarm_threshold": 40.0,
        "expected_interval_s": 600,
        "sensor_types": ["Датчик температуры", "Тепловой датчик"],
    },
    "discrete": {
        "name": "Дискретный датчик / состояние",
        "value_kind": ValueKind.STATE,
        "unit": "",
        "expected_interval_s": 3600,
        "sensor_types": [
            "Датчик дыма",
            "Состояние фазы",
            "КД Дверь",
            "Датчик движения",
            "Переключатель",
            "Состояние УИР-Р",
            "КД АВ",
            "Состояние вентилятора",
            "Состояние насоса",
            "Ручной извещатель",
            "КД Люк",
            "Состояние охраны",
            "Стекло",
            "Датчик затопления",
            "9-секционный люк",
        ],
    },
    "ups": {
        "name": "ИБП",
        "value_kind": ValueKind.MIXED,
        "unit": "",
        "expected_interval_s": 3600,
        "sensor_types": ["ИБП"],
    },
}

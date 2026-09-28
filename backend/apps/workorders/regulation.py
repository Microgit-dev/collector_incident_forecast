"""
Регламент ТО по видам оборудования и привязка реестра к нему.

Нормы систем АКМ и ДУ выведены из графика ТО и ТР заказчика на 2026 год (27 объектов, 170 строк):
у каждого вида одна и та же периодичность на всех объектах, одно из ТО в году — «ТО+ТР».
Нормы остальных систем (пожарная и охранная сигнализация, контроль доступа, насосы, вентиляция) —
из интервалов эмуляции реестра (apps/assets/domain/reliability.py); их в графике заказчика нет.
Значения хранятся в MaintenanceNorm и правятся инженером ТО; импорт графика заказчика обновляет нормы
по его фактической периодичности (schedules.derive_norms).
"""

from __future__ import annotations

from dataclasses import dataclass

CUSTOMER = "график ТО и ТР АКМ и ДУ на 2026 г., РЭК"
EMULATION = "регламент эмуляции реестра (открытые источники)"


@dataclass(frozen=True)
class NormSpec:
    type_name: str
    system: str
    unit: str
    visits: int
    repairs: int = 1
    ppr: bool = False
    source: str = CUSTOMER


DEFAULT_NORMS = [
    # АКМ и ДУ — по графику заказчика
    NormSpec("Газоанализаторы", "АКМ", "шт.", 6, ppr=True),
    NormSpec("Кабельные линии АКМ", "АКМ", "м.", 2),
    NormSpec("Кабельные линии ДУ", "ДУ", "м.", 2),
    NormSpec("БУиК, БСУ", "АКМ", "шт.", 6),
    NormSpec("Пульт СЗ (ПУИ)", "ДУ", "шт.", 6),
    NormSpec("Аппарат сигнализации (АС-9)", "АКМ", "шт.", 6),
    NormSpec("МУСБ", "ДУ", "шт.", 4),
    NormSpec("ГАСБ", "АКМ", "шт.", 4),
    NormSpec("ПККГ", "АКМ", "шт.", 4),
    NormSpec("МОД", "ДУ", "шт.", 4),
    NormSpec("МУИ", "ДУ", "шт.", 4),
    NormSpec("УЛСБ", "ДУ", "шт.", 4),
    NormSpec("УЛСБ-А", "ДУ", "шт.", 4),
    NormSpec("Повторитель интерфейса", "ДУ", "шт.", 4),
    NormSpec("Двухпортовый преобразователь", "ДУ", "шт.", 4),
    NormSpec("БП", "ДУ", "шт.", 4),
    NormSpec("ИБП", "ЭП", "шт.", 4),
    # остальные системы — по регламенту эмуляции реестра
    NormSpec("Извещатели пожарные", "АПС", "шт.", 4, source=EMULATION),
    NormSpec("Датчики температуры", "АПС", "шт.", 1, source=EMULATION),
    NormSpec("Извещатели охранные", "ОПС", "шт.", 2, source=EMULATION),
    NormSpec("Контроль доступа (двери, люки)", "СКУД", "шт.", 2, source=EMULATION),
    NormSpec("Датчики затопления", "АНС", "шт.", 2, source=EMULATION),
    NormSpec("Насосы дренажные", "АНС", "шт.", 4, source=EMULATION),
    NormSpec("Вентиляторы", "ВЕНТ", "шт.", 2, source=EMULATION),
    NormSpec("Шкафы автоматики", "ДУ", "шт.", 1, source=EMULATION),
]

# Наименование единицы в эмуляции реестра (Norm.label) → вид по регламенту
TYPE_BY_LABEL = {
    "Сигнализатор метана": "Газоанализаторы",
    "Извещатель дымовой": "Извещатели пожарные",
    "Извещатель тепловой": "Извещатели пожарные",
    "Извещатель пожарный ручной": "Извещатели пожарные",
    "Датчик температуры": "Датчики температуры",
    "Датчик затопления": "Датчики затопления",
    "Извещатель охранный объёмный": "Извещатели охранные",
    "Извещатель разбития стекла": "Извещатели охранные",
    "Дверь (контроль доступа)": "Контроль доступа (двери, люки)",
    "Аварийный выход (контроль доступа)": "Контроль доступа (двери, люки)",
    "Люк (контроль доступа)": "Контроль доступа (двери, люки)",
    "Люк 9-секционный": "Контроль доступа (двери, люки)",
    "Насос дренажный": "Насосы дренажные",
    "Вентилятор": "Вентиляторы",
    "Источник бесперебойного питания": "ИБП",
    "Шкаф автоматики": "Шкафы автоматики",
}


def seed_norms() -> int:
    """Нормы по умолчанию: создаются только отсутствующие, правки инженера ТО не перезаписываются."""
    from .models import MaintenanceNorm

    created = 0
    for spec in DEFAULT_NORMS:
        _, is_new = MaintenanceNorm.objects.get_or_create(
            type_name=spec.type_name,
            defaults={
                "system": spec.system,
                "unit": spec.unit,
                "visits_per_year": spec.visits,
                "repairs_per_year": spec.repairs,
                "ppr": spec.ppr,
                "source": spec.source,
            },
        )
        created += is_new
    return created


def interval_days(visits_per_year: int) -> int:
    return max(1, round(365 / max(visits_per_year, 1)))


def assign_types() -> dict[str, int]:
    """
    Эмулированным единицам реестра без вида по регламенту — вид и система по наименованию,
    регламентный интервал — по норме вида. Записи из реестра заказчика и ручные не трогаются.
    """
    from apps.assets.models import Equipment

    from .models import MaintenanceNorm

    norms = {n.type_name: n for n in MaintenanceNorm.objects.all()}
    updated = 0
    for label, type_name in TYPE_BY_LABEL.items():
        norm = norms.get(type_name)
        if norm is None:
            continue
        updated += Equipment.objects.filter(
            source="emulated", type_name="", name__startswith=f"{label}:"
        ).update(
            type_name=type_name,
            system=norm.system,
            unit=norm.unit,
            maintenance_interval_days=interval_days(norm.visits_per_year),
        )
    left = Equipment.objects.filter(source="emulated", type_name="").count()
    return {"updated": updated, "without_type": left}

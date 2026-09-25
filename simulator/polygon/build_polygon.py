"""
Учебный полигон: справочники объектов и каналов в формате заказчика.

Полигон повторяет структуру района в миниатюре — район, три объекта с названиями, как в
демо-составе (Мю, Кси, Тау), у каждого пожарная (ПС), охранная (ОС) и диспетчерская (ДУ) часть.
Каналы названы по правилам СМВУ («ДД ПК204», «ГАЗ Д3 ПК212»), поэтому пикеты разбираются тем же
кодом, что и у боевых каналов, и схема строится без доработок.

Идентификаторы вынесены за пределы боевых (объекты от 900000, каналы от 90000000): даже если
файл по ошибке загрузят в боевой контур, он не пересечётся со справочником заказчика.

    python simulator/polygon/build_polygon.py
"""

import csv
from pathlib import Path

OUT = Path(__file__).parent / "dataset"
DISTRICT = (900000, "Район по эксплуатации")
COMPLEXES = [
    # (ид, название, первый пикет трассы)
    (900100, "объект Мю", 200),
    (900200, "объект Кси", 0),
    (900300, "объект Тау", 60),
]
LENGTH = 40  # длина учебной трассы в пикетах

FIRE = ("Пожарная охрана", "ПС")
GUARD = ("Охранная подсистема", "ОС")
CONTROL = ("Диспетчерский контроль", "ДУ")


def channels_for(first: int) -> dict[str, list[tuple[str, str, str]]]:
    """Каналы по частям объекта: (тип_инж_системы, тип_датчика, название)."""
    pk = [first + step for step in range(0, LENGTH + 1, 4)]  # колодцы и вентшахты через 4 пикета
    low = first + LENGTH // 2  # нижняя точка трассы: насосная и датчик затопления
    fire = [
        *[(FIRE[0], "Датчик дыма", f"ДД ПК{p}") for p in pk],
        *[(FIRE[0], "Тепловой датчик", f"ТД ПК{p}") for p in pk],
        *[("Температурная подсистема", "Датчик температуры", f"Темп. ВШ ПК{p}") for p in pk[::2]],
        (FIRE[0], "Ручной извещатель", "ИПР вход в коллектор"),
        *[(FIRE[0], "Состояние УИР-Р", f"УИР-Р ПК{p}") for p in pk[1::4]],
    ]
    guard = [
        (GUARD[0], "Состояние охраны", "Охранная зона коллектора"),
        *[(GUARD[0], "КД Люк", f"КД люк ПК{p}") for p in (pk[0], pk[5], pk[-1])],
        *[(GUARD[0], "КД Дверь", f"КД дв.отс. ПК{p}") for p in (pk[1], pk[4], pk[7], pk[9])],
        *[(GUARD[0], "Датчик движения", f"ОД ПК{p}") for p in (pk[1], pk[4], pk[7], pk[9])],
        *[(GUARD[0], "КД АВ", f"КД АВ ПК{p}") for p in (pk[2], pk[8])],
    ]
    control = [
        *[("Газовая охрана", "Газовый датчик", f"ГАЗ Д{i + 1} ПК{p}") for i, p in enumerate(pk[::2])],
        (CONTROL[0], "Состояние насоса", f"Н1 АНС ПК{low}"),
        (CONTROL[0], "Состояние насоса", f"Н2 АНС ПК{low}"),
        (CONTROL[0], "Датчик затопления", f"Затопление АНС ПК{low}"),
        *[(CONTROL[0], "Состояние вентилятора", f"В{i + 1} ПК{p}") for i, p in enumerate(pk[1::4])],
        (CONTROL[0], "Состояние фазы", f"ЩАП Ввод-1 Э/щ ПК{low}"),
        (CONTROL[0], "Состояние фазы", f"ЩАП Ввод-2 Э/щ ПК{low}"),
        ("Диагностическая подсистема", "ИБП", "ББП ДП"),
    ]
    return {"ПС": fire, "ОС": guard, "ДУ": control}


def build() -> tuple[int, int]:
    OUT.mkdir(exist_ok=True)
    objects = [(DISTRICT[0], 1, "", "district", DISTRICT[1])]
    channels = []
    next_channel = 90_000_001
    for complex_id, name, first in COMPLEXES:
        objects.append((complex_id, 2, DISTRICT[0], "controlHouse", name))
        for offset, (part, rows) in enumerate(channels_for(first).items(), start=1):
            object_id = complex_id + offset
            kind = "controlHouse" if part == "ДУ" else "guardObject"
            objects.append((object_id, 3, complex_id, kind, f"{name} {part}"))
            for number, (system, sensor, title) in enumerate(rows, start=1):
                tag = f"{object_id}-1.{offset}.{number}."
                channels.append((next_channel, system, sensor, tag, title, object_id))
                next_channel += 1

    with open(OUT / "справочник_объектов_диспетчер.csv", "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
        writer.writerow(["ид_объект", "иерархия_уровень", "родитель", "вид_объекта", "диспетчерское_название_объекта"])
        writer.writerows(objects)
    with open(OUT / "справочник_каналов_датчиков.csv", "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
        writer.writerow(
            [
                "ид_канала_данных",
                "тип_инж_системы",
                "тип_датчика",
                "тег_инженерной_системы",
                "название_датчика",
                "ид_объект",
            ]
        )
        writer.writerows(channels)
    return len(objects), len(channels)


if __name__ == "__main__":
    objects, channels = build()
    print(f"objects={objects} channels={channels}")

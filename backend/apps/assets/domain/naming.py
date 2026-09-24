"""
Разбор названий каналов СМВУ: пикет, ответвление и место установки.

Координат у заказчика нет, но почти все каналы (10 720 из 11 485) несут пикет в названии.
Из него строится линейная схема коллектора. Встречаемые формы:
    «ТД ПК86-85», «ТД ПК570-572»        — диапазон, берём первый пикет;
    «Дым ПК159+5», «Темп. ВШ ПК88,5»    — плюсовка, ПК159+5 = 159,5;
    «Управление ФАНС2 ПК48 Г1 ПК5»      — магистраль ПК48, ответвление Г1 на его ПК5;
    «ГРО18 ПК175(ПК153-ПК175 прав.)»    — первый пикет, в скобках — зона действия.
Трактовка плюсовки как десятых долей пикета — допущение, зафиксированное в docs/data-methodology.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

_PICKET = r"ПК\s*(\d+)(?:\s*([+,.])\s*(\d+))?"
_MAIN = re.compile(_PICKET, re.IGNORECASE)
_BRANCH = re.compile(r"\bГ(\d+)\s+" + _PICKET, re.IGNORECASE)

# Сокращение в названии → человекочитаемое место установки
_PLACES = [
    (re.compile(r"\bВШ\b", re.I), "вентшахта"),
    (re.compile(r"\bкам\.?|\bкамер", re.I), "камера"),
    (re.compile(r"\bщит|\bэ/щ|\bЩАП\b|\bшкаф", re.I), "щитовая"),
    (re.compile(r"\bАНС\b", re.I), "насосная станция"),
    (re.compile(r"\bВК\b|\bвход", re.I), "вход"),
    (re.compile(r"\bлюк", re.I), "люк"),
    (re.compile(r"\bДП\b|\bдисп", re.I), "диспетчерский пункт"),
]


@dataclass(frozen=True, slots=True)
class ParsedName:
    picket: Decimal | None
    branch: str | None
    branch_picket: Decimal | None
    place: str

    @property
    def location_hint(self) -> str:
        parts = [self.place] if self.place else []
        if self.branch:
            suffix = f" ПК{self.branch_picket.normalize()}" if self.branch_picket is not None else ""
            parts.append(f"ответвление {self.branch}{suffix}")
        return ", ".join(parts)


def _to_decimal(whole: str, sep: str | None, frac: str | None) -> Decimal:
    if not frac:
        return Decimal(whole)
    # «+5» и «,5» трактуются одинаково — десятые доли пикета
    return Decimal(f"{whole}.{frac}")


def parse_name(name: str) -> ParsedName:
    branch = branch_picket = None
    main_text = name
    if match := _BRANCH.search(name):
        branch = f"Г{match.group(1)}"
        branch_picket = _to_decimal(match.group(2), match.group(3), match.group(4))
        main_text = name[: match.start()]
    picket = None
    if match := _MAIN.search(main_text):
        picket = _to_decimal(match.group(1), match.group(2), match.group(3))
    place = next((label for rx, label in _PLACES if rx.search(name)), "")
    return ParsedName(picket=picket, branch=branch, branch_picket=branch_picket, place=place)

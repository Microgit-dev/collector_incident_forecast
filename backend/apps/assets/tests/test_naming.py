from decimal import Decimal

import pytest

from apps.assets.domain.naming import parse_name


@pytest.mark.parametrize(
    ("name", "picket", "branch", "branch_picket", "place"),
    [
        ("ТД ПК86-85", Decimal("86"), None, None, ""),
        ("Темп. ВШ ПК88,5", Decimal("88.5"), None, None, "вентшахта"),
        ("ГАЗ Д22 ПК159+5", Decimal("159.5"), None, None, ""),
        ("Управление ФАНС2 ПК48 Г1 ПК5", Decimal("48"), "Г1", Decimal("5"), ""),
        ("Дым ПК1050 Г1 ПК2+8", Decimal("1050"), "Г1", Decimal("2.8"), ""),
        ("ГРО18 ПК175(ПК153-ПК175 прав.)", Decimal("175"), None, None, ""),
        ("Дым ПК683+5 кам.", Decimal("683.5"), None, None, "камера"),
        ("АКБ ПК55 э/щ", Decimal("55"), None, None, "щитовая"),
        ("ОД комната 1", None, None, None, ""),
        ("АНС Н1", None, None, None, "насосная станция"),
    ],
)
def test_parse_name(name, picket, branch, branch_picket, place):
    parsed = parse_name(name)
    assert (parsed.picket, parsed.branch, parsed.branch_picket, parsed.place) == (
        picket,
        branch,
        branch_picket,
        place,
    )


def test_location_hint():
    assert parse_name("Дым ПК1050 Г1 ПК2+8 кам.").location_hint == "камера, ответвление Г1 ПК2.8"

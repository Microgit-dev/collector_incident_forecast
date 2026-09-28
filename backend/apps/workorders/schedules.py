"""
Графики работ на год в формах заказчика (ТЗ §3 «планирование профилактических работ», §8, §18
«соответствие рекомендаций реальным»):

- **График ТО и ТР** — объект × вид оборудования, количество, отметки «ТО» / «ТО+ТР» по месяцам.
  Периодичность — регламент вида (MaintenanceNorm): 2, 4 или 6 ТО в год, одно из них с ТР.
  Как у заказчика, у всех видов объекта общий месяц ТР, остальные ТО отсчитываются от него
  с шагом 12 / (ТО в год). Месяц ТР объекта выбирается так, чтобы выровнять нагрузку по месяцам:
  объекты по убыванию числа работ, каждому — месяц с наименьшей накопленной нагрузкой.
- **План-график ППР аппаратуры контроля метана** — ежегодный цикл: демонтаж датчиков → сдача
  в метрологическую службу на ППР и поверку (до 9:00 следующего рабочего дня) → вывоз → сдача
  работ комиссии. Мелкие объекты объединяются в партию с соседним, партии идут одна за другой
  и равномерно распределены по рабочим дням года. Длительности — по графику заказчика на 2026 год:
  ОМ 6–13 рабочих дней в зависимости от числа датчиков, приёмка 3–5 рабочих дней.

Графики строятся по реестру зоны или загружаются из файла заказчика. Сверка: генератор
применяется к составу оборудования из графика заказчика, и сравниваются периодичность и нагрузка
по месяцам. Утверждённый график превращается в заявки (строка графика → черновик заявки).
"""

from __future__ import annotations

import io
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from django.db import transaction
from django.utils import timezone

from .models import MaintenanceNorm, MaintenanceSchedule, ScheduleLine

MONTH_SHORT = ["янв.", "февр.", "март", "апр.", "май", "июн.", "июл.", "авг.", "сен.", "окт.", "ноя.", "дек."]
MONTH_NAMES = [
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
]
TO, TO_TR = "ТО", "ТО+ТР"

# Нерабочие праздничные дни (производственный календарь РФ, упрощённо); 2026 — с переносами
HOLIDAYS = {
    2026: {
        *(date(2026, 1, d) for d in range(1, 12)),
        date(2026, 2, 23),
        date(2026, 3, 9),
        date(2026, 5, 1),
        date(2026, 5, 11),
        date(2026, 6, 12),
        date(2026, 11, 4),
        date(2026, 12, 31),
    }
}


def _holidays(year: int) -> set[date]:
    if year in HOLIDAYS:
        return HOLIDAYS[year]
    return {
        *(date(year, 1, d) for d in range(1, 9)),
        date(year, 2, 23),
        date(year, 3, 8),
        date(year, 5, 1),
        date(year, 5, 9),
        date(year, 6, 12),
        date(year, 11, 4),
    }


def working_days(year: int) -> list[date]:
    off = _holidays(year)
    day, days = date(year, 1, 1), []
    while day.year == year:
        if day.weekday() < 5 and day not in off:
            days.append(day)
        day += timedelta(days=1)
    return days


def add_wd(day: date, n: int, calendar: list[date]) -> date:
    """n рабочих дней после day (по календарю года; за его концом — просто будни)."""
    later = [d for d in calendar if d > day]
    if n <= len(later):
        return later[n - 1]
    current = later[-1] if later else day
    left = n - len(later)
    while left:
        current += timedelta(days=1)
        if current.weekday() < 5:
            left -= 1
    return current


# ---------------------------------------------------------------- ТО и ТР


@dataclass
class Group:
    """Объект × вид оборудования с регламентом."""

    object_label: str
    type_name: str
    quantity: float
    unit: str
    visits: int
    repairs: int = 1
    node_id: int | None = None
    brand: str = ""
    months: dict[str, str] = field(default_factory=dict)


def months_for(anchor: int, visits: int, repairs: int) -> dict[str, str]:
    """Отметки по месяцам (1–12): ТР в месяце-якоре, остальные ТО с равным шагом назад от него."""
    if visits <= 0:
        return {}
    step = 12 / visits
    marks: dict[str, str] = {}
    for j in range(visits):
        month = (anchor - round(j * step)) % 12
        marks[str(month + 1)] = TO_TR if j < repairs else TO
    return marks


def plan_to_tr(groups: list[Group]) -> list[Group]:
    """Месяц ТР каждого объекта — с наименьшей накопленной нагрузкой (объекты по убыванию работ)."""
    by_object: dict[str, list[Group]] = defaultdict(list)
    for g in groups:
        by_object[g.object_label].append(g)
    load = [0] * 12
    weight = {k: sum(g.visits for g in v) for k, v in by_object.items()}
    for label in sorted(by_object, key=lambda k: (-weight[k], k)):
        best = None
        for anchor in range(12):
            trial = load[:]
            for g in by_object[label]:
                for m in months_for(anchor, g.visits, g.repairs):
                    trial[int(m) - 1] += 1
            key = (max(trial), sum(x * x for x in trial), anchor)
            if best is None or key < best[0]:
                best = (key, anchor, trial)
        _, anchor, load = best
        for g in by_object[label]:
            g.months = months_for(anchor, g.visits, g.repairs)
    return groups


def monthly_load(lines) -> list[int]:
    load = [0] * 12
    for line in lines:
        for m in line.months:
            load[int(m) - 1] += 1
    return load


def _object_of_map():
    from apps.topology.models import Node, NodeKind

    objects = sorted(
        Node.objects.filter(kind=NodeKind.COMPLEX).values_list("path", "pk", "name"), key=lambda r: -len(r[0])
    )
    return objects


def compose_to_tr(user) -> list[Group]:
    """Состав для графика ТО и ТР: действующее оборудование зоны с видом по регламенту, по объектам."""
    from apps.assets.models import Equipment
    from apps.topology.selectors import scope_queryset

    norms = {n.type_name: n for n in MaintenanceNorm.objects.all()}
    objects = _object_of_map()
    totals: dict[tuple[int, str], dict] = {}
    rows = (
        scope_queryset(Equipment.objects.filter(is_active=True).exclude(type_name=""), user, "node")
        .values_list("node__path", "node_id", "node__name", "type_name", "quantity", "unit")
        .iterator()
    )
    for path, node_id, node_name, type_name, qty, unit in rows:
        if type_name not in norms:
            continue
        obj = next(((pk, name) for p, pk, name in objects if path.startswith(p)), (node_id, node_name))
        key = (obj[0], type_name)
        entry = totals.setdefault(key, {"label": obj[1], "qty": 0.0, "unit": unit})
        entry["qty"] += qty
    groups = []
    for (node_id, type_name), entry in totals.items():
        norm = norms[type_name]
        groups.append(
            Group(
                object_label=entry["label"],
                type_name=type_name,
                quantity=entry["qty"],
                unit=entry["unit"] or norm.unit,
                visits=norm.visits_per_year,
                repairs=norm.repairs_per_year,
                node_id=node_id,
            )
        )
    return sorted(groups, key=lambda g: (g.object_label, g.type_name))


# ---------------------------------------------------------------- ППР


@dataclass
class PprItem:
    object_label: str
    quantity: int
    node_id: int | None = None
    batch: int = 0
    month: int = 0
    dismantle_on: date | None = None
    delivery_on: date | None = None
    pickup_on: date | None = None
    acceptance_on: date | None = None


def om_days(count: int) -> int:
    """Рабочих дней в ОМ на ППР и поверку: 6–13 по графику заказчика, дольше для больших партий."""
    return min(13, 6 + round(count / 20))


def acceptance_days(count: int) -> int:
    return 3 if count <= 60 else 4


def plan_ppr(items: list[PprItem], year: int, batches_per_year: int = 16) -> list[PprItem]:
    """Партии (мелкие объекты — с соседним) равномерно по рабочим дням года, одна за другой."""
    calendar = working_days(year)
    total = sum(i.quantity for i in items) or 1
    target = total / max(1, min(batches_per_year, len(items)))
    groups: list[list[PprItem]] = []
    for item in items:
        # мелкий объект (меньше 40 % средней партии) едет в ОМ вместе с соседним, как у заказчика
        small = item.quantity < 0.4 * target
        if groups and small and sum(i.quantity for i in groups[-1]) + item.quantity <= 2 * target:
            groups[-1].append(item)
        else:
            groups.append([item])
    # длительность цикла партии в рабочих днях; свободные дни года делятся поровну между партиями,
    # чтобы ППР шли весь год, а не упирались друг в друга в начале года
    cycles = [
        1 + om_days(sum(i.quantity for i in g)) + acceptance_days(sum(i.quantity for i in g)) + len(g) - 1
        for g in groups
    ]
    spare = max(0, len(calendar) - sum(cycles) - 10)  # запас в конце года под перенос партии
    gap = spare // max(1, len(groups))
    position = 0
    for n, (group, cycle) in enumerate(zip(groups, cycles, strict=True), start=1):
        count = sum(i.quantity for i in group)
        start = calendar[min(len(calendar) - 1, position)]
        delivery = add_wd(start, 1, calendar)
        pickup = add_wd(delivery, om_days(count), calendar)
        acceptance = add_wd(pickup, acceptance_days(count), calendar)
        middle = delivery + (pickup - delivery) / 2
        for k, item in enumerate(group):
            item.batch, item.month = n, middle.month
            item.dismantle_on, item.delivery_on, item.pickup_on = start, delivery, pickup
            # мелкие объекты партии принимаются следующими днями
            item.acceptance_on = add_wd(acceptance, k, calendar) if k else acceptance
        position += cycle + 1 + gap
    return items


def compose_ppr(user) -> list[PprItem]:
    """Датчики метана зоны (виды с ежегодным ППР) по объектам, в порядке дерева."""
    from apps.assets.models import Equipment
    from apps.topology.selectors import scope_queryset

    ppr_types = list(MaintenanceNorm.objects.filter(ppr=True).values_list("type_name", flat=True))
    objects = _object_of_map()
    counts: dict[int, list] = {}
    rows = scope_queryset(
        Equipment.objects.filter(is_active=True, type_name__in=ppr_types), user, "node"
    ).values_list("node__path", "node_id", "node__name", "quantity")
    for path, node_id, node_name, qty in rows:
        pk, name, opath = next(
            ((pk, name, p) for p, pk, name in objects if path.startswith(p)), (node_id, node_name, path)
        )
        entry = counts.setdefault(pk, [name, 0, opath])
        entry[1] += qty
    ordered = sorted(counts.items(), key=lambda kv: kv[1][2])
    return [PprItem(object_label=v[0], quantity=int(v[1]), node_id=k) for k, v in ordered if v[1]]


# ---------------------------------------------------------------- сохранение и сводка


def stats_of(schedule: MaintenanceSchedule) -> dict:
    lines = list(schedule.lines.all())
    if schedule.kind == MaintenanceSchedule.Kind.TO_TR:
        load = monthly_load(lines)
        return {
            "objects": len({ln.object_label for ln in lines}),
            "lines": len(lines),
            "load": load,
            "repairs": [sum(1 for ln in lines if ln.months.get(str(m)) == TO_TR) for m in range(1, 13)],
        }
    sensors = [0] * 12
    for ln in lines:
        if ln.month:
            sensors[ln.month - 1] += ln.quantity
    return {
        "objects": len(lines),
        "batches": len({ln.batch for ln in lines if ln.batch}),
        "sensors": int(sum(ln.quantity for ln in lines)),
        "load": [int(x) for x in sensors],
    }


@transaction.atomic
def save_to_tr(
    groups: list[Group], year: int, user, source: str, title: str, file_name: str = ""
) -> MaintenanceSchedule:
    schedule = MaintenanceSchedule.objects.create(
        kind=MaintenanceSchedule.Kind.TO_TR,
        year=year,
        title=title,
        source=source,
        zone=getattr(user, "scope_node", None) if user else None,
        created_by=user,
        file_name=file_name,
    )
    ScheduleLine.objects.bulk_create(
        [
            ScheduleLine(
                schedule=schedule,
                order=i,
                node_id=g.node_id,
                object_label=g.object_label,
                type_name=g.type_name,
                brand=g.brand,
                quantity=g.quantity,
                unit=g.unit,
                months=g.months,
            )
            for i, g in enumerate(groups)
        ]
    )
    schedule.stats = stats_of(schedule)
    schedule.save(update_fields=["stats"])
    return schedule


@transaction.atomic
def save_ppr(
    items: list[PprItem], year: int, user, source: str, title: str, file_name: str = ""
) -> MaintenanceSchedule:
    schedule = MaintenanceSchedule.objects.create(
        kind=MaintenanceSchedule.Kind.PPR,
        year=year,
        title=title,
        source=source,
        zone=getattr(user, "scope_node", None) if user else None,
        created_by=user,
        file_name=file_name,
    )
    ScheduleLine.objects.bulk_create(
        [
            ScheduleLine(
                schedule=schedule,
                order=i,
                node_id=it.node_id,
                object_label=it.object_label,
                type_name="Газоанализаторы",
                quantity=it.quantity,
                month=it.month or None,
                batch=it.batch or None,
                dismantle_on=it.dismantle_on,
                delivery_on=it.delivery_on,
                pickup_on=it.pickup_on,
                acceptance_on=it.acceptance_on,
            )
            for i, it in enumerate(items)
        ]
    )
    schedule.stats = stats_of(schedule)
    schedule.save(update_fields=["stats"])
    return schedule


def generate(kind: str, year: int, user) -> MaintenanceSchedule:
    zone = getattr(user, "scope_node", None)
    where = zone.name if zone else "район"
    if kind == MaintenanceSchedule.Kind.TO_TR:
        groups = plan_to_tr(compose_to_tr(user))
        return save_to_tr(
            groups, year, user, MaintenanceSchedule.Source.GENERATED, f"График ТО и ТР на {year} г. — {where}"
        )
    items = plan_ppr(compose_ppr(user), year)
    return save_ppr(
        items, year, user, MaintenanceSchedule.Source.GENERATED, f"План-график ППР АКМ на {year} г. — {where}"
    )


# ---------------------------------------------------------------- файлы заказчика


class ScheduleFileError(ValueError):
    pass


def _cell_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and (m := re.search(r"(\d{2}\.\d{2}\.\d{4})", value)):
        return datetime.strptime(m.group(1), "%d.%m.%Y").date()
    return None


def _year_of(ws, default: int) -> int:
    for row in ws.iter_rows(min_row=1, max_row=12, values_only=True):
        for value in row:
            if isinstance(value, str) and (m := re.search(r"(20\d{2})\s*г", value)):
                return int(m.group(1))
    return default


def read_customer_file(content: bytes) -> tuple[str, int, list]:
    """Определяет форму (ТО и ТР или ППР) по заголовкам и возвращает (вид, год, строки)."""
    from openpyxl import load_workbook

    ws = load_workbook(io.BytesIO(content), data_only=True).worksheets[0]
    year = _year_of(ws, timezone.localdate().year)
    for row in ws.iter_rows(min_row=1, max_row=20):
        values = {c.column_letter: c.value for c in row if c.value is not None}
        texts = " ".join(str(v) for v in values.values()).lower()
        if "месяц то" in texts and "вид оборудования" in texts:
            return MaintenanceSchedule.Kind.TO_TR, year, _parse_to_tr(ws, row[0].row)
        if "месяц проведения ппр" in texts:
            return MaintenanceSchedule.Kind.PPR, year, _parse_ppr(ws, row[0].row)
    raise ScheduleFileError("Не найдены заголовки графика ТО и ТР или план-графика ППР")


def _parse_to_tr(ws, header_row: int) -> list[Group]:
    month_cols = "GHIJKLMNOPQR"
    groups, current, last_number = [], None, None
    for r in range(header_row + 2, ws.max_row + 1):
        number, obj, kind = ws[f"B{r}"].value, ws[f"C{r}"].value, ws[f"D{r}"].value
        # шапка повторяется на каждой странице А4 — пропускаем
        if str(obj or "").strip().lower() == "вид оборудования" or str(number or "").startswith("№"):
            continue
        if obj:
            # «Объект» без номера — продолжение предыдущего объекта (объединённая ячейка)
            last_number = number if number is not None else last_number
            current = f"{str(obj).strip()} {last_number}" if last_number is not None else str(obj).strip()
        # оборудование бывает записано прямо в строке объекта
        if not kind or current is None:
            continue
        kind = str(kind).strip()
        if kind.lower() in {"марка", "вид оборудования"}:
            continue
        marks = {}
        for i, col in enumerate(month_cols):
            value = ws[f"{col}{r}"].value
            if value:
                marks[str(i + 1)] = TO_TR if "ТР" in str(value).upper() else TO
        qty = ws[f"E{r}"].value
        groups.append(
            Group(
                object_label=current,
                type_name=kind,
                quantity=float(qty) if isinstance(qty, (int, float)) else 0,
                unit=str(ws[f"F{r}"].value or "шт.").strip(),
                visits=len(marks),
                repairs=sum(1 for v in marks.values() if v == TO_TR),
                months=marks,
            )
        )
    return groups


def _parse_ppr(ws, header_row: int) -> list[PprItem]:
    items, month, batch = [], 0, 0
    for r in range(header_row + 1, ws.max_row + 1):
        label = ws[f"C{r}"].value
        if not label:
            continue
        name = ws[f"B{r}"].value
        if isinstance(name, str) and name.strip() in MONTH_NAMES:
            month = MONTH_NAMES.index(name.strip()) + 1
        start = _cell_date(ws[f"E{r}"].value)
        if start or not items:
            batch += 1
        count = ws[f"D{r}"].value
        items.append(
            PprItem(
                object_label=str(label).strip(),
                quantity=int(count) if isinstance(count, (int, float)) else 0,
                batch=batch,
                month=month,
                dismantle_on=start,
                delivery_on=_cell_date(ws[f"F{r}"].value),
                pickup_on=_cell_date(ws[f"G{r}"].value),
                acceptance_on=_cell_date(ws[f"H{r}"].value),
            )
        )
    return items


def import_customer(content: bytes, file_name: str, user) -> MaintenanceSchedule:
    kind, year, rows = read_customer_file(content)
    if kind == MaintenanceSchedule.Kind.TO_TR:
        return save_to_tr(
            rows,
            year,
            user,
            MaintenanceSchedule.Source.CUSTOMER,
            f"График ТО и ТР на {year} г. (заказчик)",
            file_name,
        )
    return save_ppr(
        rows,
        year,
        user,
        MaintenanceSchedule.Source.CUSTOMER,
        f"План-график ППР АКМ на {year} г. (заказчик)",
        file_name,
    )


def derive_norms(schedule: MaintenanceSchedule) -> dict[str, int]:
    """Регламент из графика заказчика: для каждого вида — самая частая пара (ТО в год, из них ТР)."""
    from .regulation import CUSTOMER

    patterns: dict[str, Counter] = defaultdict(Counter)
    units = {}
    for ln in schedule.lines.all():
        visits = len(ln.months)
        if visits:
            patterns[ln.type_name][(visits, sum(1 for v in ln.months.values() if v == TO_TR))] += 1
            units[ln.type_name] = ln.unit
    created = updated = 0
    for type_name, counter in patterns.items():
        (visits, repairs), _ = counter.most_common(1)[0]
        norm, is_new = MaintenanceNorm.objects.get_or_create(
            type_name=type_name, defaults={"unit": units[type_name], "source": CUSTOMER}
        )
        norm.visits_per_year, norm.repairs_per_year = visits, max(repairs, 0)
        if not is_new:
            norm.source = CUSTOMER
        norm.save()
        created += is_new
        updated += not is_new
    return {"created": created, "updated": updated}


# ---------------------------------------------------------------- сверка с графиком заказчика


def _cv(values: list[float]) -> float:
    mean = sum(values) / len(values) if values else 0
    if not mean:
        return 0.0
    return round((sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5 / mean, 3)


def validate(schedule: MaintenanceSchedule) -> dict:
    """
    Генератор на составе графика заказчика: тот же набор объектов и оборудования, регламент — из норм.
    Сравнивается периодичность по строкам и равномерность нагрузки по месяцам.
    """
    norms = {n.type_name: n for n in MaintenanceNorm.objects.all()}
    lines = list(schedule.lines.all())
    if schedule.kind == MaintenanceSchedule.Kind.TO_TR:
        groups = []
        for ln in lines:
            norm = norms.get(ln.type_name.strip())
            visits = norm.visits_per_year if norm else len(ln.months)
            repairs = norm.repairs_per_year if norm else 1
            groups.append(Group(ln.object_label, ln.type_name, ln.quantity, ln.unit, visits, repairs))
        plan_to_tr(groups)
        same_visits = sum(1 for g, ln in zip(groups, lines, strict=True) if len(g.months) == len(ln.months))
        same_tr = sum(
            1
            for g, ln in zip(groups, lines, strict=True)
            if sum(v == TO_TR for v in g.months.values()) == sum(v == TO_TR for v in ln.months.values())
        )
        theirs, ours = monthly_load(lines), monthly_load(groups)
        result = {
            "rows": len(lines),
            "periodicity_match": round(same_visits / len(lines), 3) if lines else None,
            "repairs_match": round(same_tr / len(lines), 3) if lines else None,
            "load_customer": theirs,
            "load_generated": ours,
            "cv_customer": _cv(theirs),
            "cv_generated": _cv(ours),
            "max_customer": max(theirs) if theirs else 0,
            "max_generated": max(ours) if ours else 0,
        }
    else:
        items = [PprItem(ln.object_label, int(ln.quantity)) for ln in lines]
        plan_ppr(items, schedule.year)
        theirs = [0] * 12
        for ln in lines:
            if ln.month:
                theirs[ln.month - 1] += int(ln.quantity)
        ours = [0] * 12
        for it in items:
            ours[it.month - 1] += it.quantity
        result = {
            "rows": len(lines),
            "batches_customer": len({ln.batch for ln in lines if ln.batch}),
            "batches_generated": len({it.batch for it in items}),
            "load_customer": theirs,
            "load_generated": ours,
            "cv_customer": _cv(theirs),
            "cv_generated": _cv(ours),
            "last_acceptance_customer": max(
                (ln.acceptance_on for ln in lines if ln.acceptance_on), default=None
            ),
            "last_acceptance_generated": max(
                (it.acceptance_on for it in items if it.acceptance_on), default=None
            ),
        }
        for key in ("last_acceptance_customer", "last_acceptance_generated"):
            result[key] = result[key].isoformat() if result[key] else None
    schedule.stats = {**schedule.stats, "validation": result}
    schedule.save(update_fields=["stats"])
    return result


# ---------------------------------------------------------------- выгрузка в форме заказчика


def export_xlsx(schedule: MaintenanceSchedule) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    thin = Side(style="thin")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    bold = Font(bold=True)
    zone = schedule.zone.name if schedule.zone else "Район"
    lines = list(schedule.lines.all())
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToHeight = 0

    if schedule.kind == MaintenanceSchedule.Kind.TO_TR:
        ws.title = str(schedule.year)
        ws["J1"] = zone
        ws["G2"] = f"График ТО и ТР систем на {schedule.year}г"
        ws["G2"].font = Font(bold=True, size=14)
        headers = {
            "B": "№ п.п.",
            "C": "Вид оборудования",
            "D": "Марка",
            "E": "Кол-во",
            "F": "ед.",
            "G": "Месяц ТО",
            "S": "Примечания",
        }
        for col, text in headers.items():
            ws[f"{col}4"] = text
        ws.merge_cells("G4:R4")
        for i, name in enumerate(MONTH_SHORT):
            ws[f"{get_column_letter(7 + i)}5"] = name
        for col in ("B", "C", "D", "E", "F", "S"):
            ws.merge_cells(f"{col}4:{col}5")
        row, number, current = 6, 0, None
        for ln in lines:
            if ln.object_label != current:
                current, number = ln.object_label, number + 1
                ws[f"B{row}"], ws[f"C{row}"] = number, ln.object_label
                ws[f"C{row}"].font = bold
                row += 1
            ws[f"D{row}"] = ln.type_name
            ws[f"E{row}"] = int(ln.quantity) if float(ln.quantity).is_integer() else ln.quantity
            ws[f"F{row}"] = ln.unit
            for m, mark in ln.months.items():
                ws[f"{get_column_letter(6 + int(m))}{row}"] = mark
            ws[f"S{row}"] = ln.note
            row += 1
        for r in ws.iter_rows(min_row=4, max_row=row - 1, min_col=2, max_col=19):
            for cell in r:
                cell.border = box
                cell.alignment = center if cell.column >= 5 else Alignment(vertical="center", wrap_text=True)
        widths = {"B": 6, "C": 28, "D": 30, "E": 9, "F": 5, "S": 18}
        for col, width in widths.items():
            ws.column_dimensions[col].width = width
        for i in range(12):
            ws.column_dimensions[get_column_letter(7 + i)].width = 7
        for cell in ws[4] + ws[5]:
            cell.font = bold
    else:
        ws.title = "ППР"
        ws["A7"] = (
            f"Приложение к план-графику планово-предупредительных работ (ППР) аппаратуры контроля метана на {schedule.year} год"
        )
        ws["A7"].font = Font(bold=True, size=12)
        ws.merge_cells("A7:H7")
        headers = [
            "Подразделение",
            "Месяц проведения ППР",
            "Наименование коллектора",
            "Кол-во, шт.",
            "Начало работ по демонтажу датчиков метана",
            "Предоставление датчиков метана в ОМ на ППР и поверку",
            "Вывоз датчиков метана из ОМ",
            "Сдача работ по ППР комиссии",
        ]
        for i, text in enumerate(headers):
            cell = ws.cell(row=9, column=1 + i, value=text)
            cell.font, cell.alignment, cell.border = bold, center, box
        row, last_month, last_batch = 10, None, None
        for i, ln in enumerate(lines):
            if i == 0:
                ws[f"A{row}"] = zone
            if ln.month and ln.month != last_month:
                ws[f"B{row}"] = MONTH_NAMES[ln.month - 1]
                last_month = ln.month
            ws[f"C{row}"] = ln.object_label
            ws[f"D{row}"] = int(ln.quantity)
            first_of_batch = ln.batch != last_batch
            if first_of_batch:
                ws[f"E{row}"] = ln.dismantle_on
                ws[f"F{row}"] = f"до 9:00 {ln.delivery_on:%d.%m.%Y}" if ln.delivery_on else None
                ws[f"G{row}"] = ln.pickup_on
                last_batch = ln.batch
            ws[f"H{row}"] = ln.acceptance_on
            for col in "EGH":
                ws[f"{col}{row}"].number_format = "DD.MM.YYYY"
            for c in range(1, 9):
                ws.cell(row=row, column=c).border = box
                ws.cell(row=row, column=c).alignment = center
            row += 1
        for col, width in zip("ABCDEFGH", (16, 14, 28, 10, 18, 22, 16, 16), strict=True):
            ws.column_dimensions[col].width = width
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


# ---------------------------------------------------------------- от графика к заявкам

WORK_BY_TYPE = {
    "Газоанализаторы": "calibration",
    "Насосы дренажные": "pump_service",
    "Вентиляторы": "ventilation",
    "ИБП": "power_check",
    "БП": "power_check",
    "Шкафы автоматики": "power_check",
    "Контроль доступа (двери, люки)": "security",
    "Извещатели охранные": "security",
}


def due_lines(user, today: date | None = None, months_ahead: int = 1) -> list[dict]:
    """Работы утверждённых графиков на текущий и следующий месяц, которые ещё не в плане."""
    from apps.topology.selectors import scope_queryset

    today = today or timezone.localdate()
    wanted = {((today.month - 1 + k) % 12) + 1 for k in range(months_ahead + 1)}
    lines = scope_queryset(
        ScheduleLine.objects.filter(
            schedule__status=MaintenanceSchedule.Status.APPROVED,
            schedule__year=today.year,
            node__isnull=False,
        ).select_related("schedule"),
        user,
        "node",
    ).prefetch_related("workorders")
    rows = []
    for ln in lines:
        if ln.schedule.kind == MaintenanceSchedule.Kind.TO_TR:
            months = sorted(int(m) for m in ln.months if int(m) in wanted)
            if not months:
                continue
            month, work = months[0], ln.months[str(months[0])]
        else:
            if not ln.dismantle_on or ln.dismantle_on.month not in wanted:
                continue
            month, work = ln.dismantle_on.month, "ППР и поверка"
        open_orders = [w for w in ln.workorders.all() if w.status != "cancelled" and w.due_at.month == month]
        rows.append(
            {
                "id": ln.pk,
                "schedule": ln.schedule.title,
                "kind": ln.schedule.kind,
                "object": ln.object_label,
                "type_name": ln.type_name,
                "quantity": ln.quantity,
                "unit": ln.unit,
                "month": month,
                "work": work,
                "date": ln.dismantle_on,
                "planned": {
                    "id": open_orders[0].pk,
                    "number": open_orders[0].number,
                    "status": open_orders[0].status,
                }
                if open_orders
                else None,
            }
        )
    return sorted(rows, key=lambda r: (r["month"], r["object"], r["type_name"]))


def schedule_line(line: ScheduleLine, day: date, user):
    """Черновик заявки по строке утверждённого графика на выбранную дату."""
    from .maintenance import _due_at
    from .models import WorkOrder
    from .services import next_number

    if line.node_id is None:
        raise ValueError("Строка графика не привязана к объекту системы")
    ppr = line.schedule.kind == MaintenanceSchedule.Kind.PPR
    month = line.dismantle_on.month if ppr and line.dismantle_on else day.month
    work = "ППР и поверка" if ppr else line.months.get(str(month), TO)
    qty = int(line.quantity) if float(line.quantity).is_integer() else line.quantity
    return WorkOrder.objects.create(
        number=next_number(),
        node_id=line.node_id,
        schedule_line=line,
        work_type="calibration" if ppr else WORK_BY_TYPE.get(line.type_name, "inspection"),
        priority="medium",
        title=f"{work}: {line.type_name} — {line.object_label}"[:255],
        description=(
            f"Основание: {line.schedule.title}, {MONTH_NAMES[month - 1].lower()}.\n"
            f"{line.type_name}: {qty} {line.unit}"
            + (
                f"\nЦикл ППР: демонтаж {line.dismantle_on:%d.%m}, ОМ до 9:00 {line.delivery_on:%d.%m}, "
                f"вывоз {line.pickup_on:%d.%m}, комиссия {line.acceptance_on:%d.%m}"
                if ppr and line.dismantle_on
                else ""
            )
        ),
        due_at=_due_at(day),
        created_by=user,
    )

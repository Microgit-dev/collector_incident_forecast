"""
Вероятность для индикаторов пожара и НСД: выборка из архива и калибровка.

По Parquet-архиву журналов индекс считается теми же правилами (domain/scenarios.py) и на тех же
окнах, что и в работе (scenarios.py): тревоги за час, среднее температуры за 30 минут, медиана за
сутки, режим охраны за 7 суток, история неисправностей канала за 90 суток. Шаг — час. Для каждого
момента с индексом от MIN_SCORE известен исход — те же тревоги на объекте через 1–24 ч
(как resolve_scenarios). Из пар «индекс → исход» строится калибровка (domain/calibration.py):
обучение на годах до отложенного, проверка — на отложенном годе.

Чего нет в архиве: Data Health канала на тот момент и заявок в работе. В выборке они не учитываются;
в работе эти поправки уменьшают индекс до калибровки, а калибровка монотонна.
"""

from __future__ import annotations

import bisect
import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import numpy as np
import polars as pl
from django.conf import settings

from .channel_model import MSK
from .domain import calibration as cal
from .domain.scenarios import (
    TEMP_TYPES,
    ChannelWindow,
    ScenarioContext,
    fire_risk,
    intrusion_risk,
)
from .models import ForecastTask, IndicatorCalibration
from .scenarios import GUARD_TYPE, MIN_SCORE, TASK_TYPES, WINDOW

logger = logging.getLogger(__name__)

EXCLUDED_YEARS = {2021}  # переход на новую систему мониторинга — заказчик рекомендует исключить
STEP = timedelta(hours=1)
VALID = ("ok", "drift")
RISK = {ForecastTask.FIRE: fire_risk, ForecastTask.INTRUSION: intrusion_risk}
WINDOW_NP = np.timedelta64(int(WINDOW.total_seconds()), "s")


@dataclass(frozen=True, slots=True)
class Sample:
    task: str
    at: datetime
    node_id: int
    score: float
    outcome: bool


class _FaultHistory:
    """Сумма неисправностей канала за 90 суток до дня (как _fault_history в работе), по суточной витрине."""

    def __init__(self, channel_ids: list[int]):
        from apps.telemetry.models import ChannelDaily

        rows = (
            ChannelDaily.objects.filter(channel_id__in=channel_ids, faults__gt=0)
            .order_by("channel_id", "day")
            .values_list("channel_id", "day", "faults")
        )
        self.days: dict[int, list[date]] = defaultdict(list)
        self.cum: dict[int, list[int]] = defaultdict(list)
        for cid, day, faults in rows:
            self.days[cid].append(day)
            self.cum[cid].append((self.cum[cid][-1] if self.cum[cid] else 0) + faults)

    def __call__(self, cid: int, day: date) -> int:
        days = self.days.get(cid)
        if not days:
            return 0
        cum = self.cum[cid]

        def upto(d: date) -> int:  # сумма по дням < d
            i = bisect.bisect_left(days, d)
            return cum[i - 1] if i else 0

        return upto(day) - upto(day - timedelta(days=90))


def _channels() -> pl.DataFrame:
    from apps.assets.models import Channel

    types = TASK_TYPES[ForecastTask.FIRE] | TASK_TYPES[ForecastTask.INTRUSION] | {GUARD_TYPE}
    rows = Channel.objects.filter(sensor_type__name__in=types).values_list(
        "id", "node_id", "sensor_type__name", "name", "picket"
    )
    return pl.DataFrame(
        [(i, n, t, nm, float(p) if p is not None else None) for i, n, t, nm, p in rows],
        schema={
            "channel_id": pl.Int64,
            "node_id": pl.Int64,
            "stype": pl.String,
            "name": pl.String,
            "picket": pl.Float64,
        },
        orient="row",
    )


def _journal(year: int, channel_ids: list[int]) -> pl.DataFrame:
    path = settings.ARTIFACTS_DIR / "archive" / f"journal_{year}.parquet"
    if not path.exists():
        return pl.DataFrame()
    return (
        pl.scan_parquet(path)
        .filter(pl.col("channel_id").is_in(channel_ids) & (pl.col("facet") == "primary"))
        .select("ts", "channel_id", "state", "numeric", "quality", "raw_value")
        .sort("ts")
        .collect()
    )


def _utc(t: np.datetime64) -> datetime:
    return datetime.fromtimestamp(int(t.astype("datetime64[s]").astype(np.int64)), tz=UTC)


def year_samples(year: int, progress: Callable[[str], None] = lambda _: None) -> list[Sample]:
    """Все моменты года (шаг час) с индексом от MIN_SCORE и исходом через 1–24 ч."""
    meta = _channels()
    df = _journal(year, meta["channel_id"].to_list())
    if df.is_empty():
        return []
    df = df.join(meta.select("channel_id", "node_id", "stype"), on="channel_id").sort("ts")
    info = {r["channel_id"]: r for r in meta.iter_rows(named=True)}
    faults = _FaultHistory(meta["channel_id"].to_list())
    risk_types = sorted(TASK_TYPES[ForecastTask.FIRE] | TASK_TYPES[ForecastTask.INTRUSION])

    # Режим охраны объекта: последнее «На охране» / «Снято с охраны»
    guard: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    marks = df.filter(
        (pl.col("stype") == GUARD_TYPE) & pl.col("raw_value").is_in(["На охране", "Снято с охраны"])
    )
    for (node_id,), part in marks.group_by("node_id"):
        guard[node_id] = (part["ts"].to_numpy(), (part["raw_value"] == "На охране").to_numpy())

    # Тревоги каналов пожара и НСД (для окна «за час» и для исхода — как resolve_scenarios)
    alarms = df.filter((pl.col("state") == "alarm") & pl.col("stype").is_in(risk_types))
    a_ts, a_cid = alarms["ts"].to_numpy(), alarms["channel_id"].to_numpy()
    outcome_at: dict[tuple[str, int], np.ndarray] = {}
    for task, types in TASK_TYPES.items():
        for (node_id,), part in alarms.filter(pl.col("stype").is_in(sorted(types))).group_by("node_id"):
            outcome_at[(task, node_id)] = part["ts"].to_numpy()

    # Температура: корректные измерения (служебные коды и артефакты в среднее и медиану не входят)
    temps = df.filter(
        pl.col("stype").is_in(sorted(TEMP_TYPES))
        & pl.col("quality").is_in(VALID)
        & pl.col("numeric").is_not_null()
    ).select("ts", "channel_id", "numeric")
    t_ts = temps["ts"].to_numpy()

    ts = df["ts"].to_numpy()
    start = ts[0].astype("datetime64[h]") + np.timedelta64(24, "h")
    end = ts[-1].astype("datetime64[h]") - np.timedelta64(25, "h")  # у последних суток года нет исхода
    one_h, half_h, day = (np.timedelta64(x, "m") for x in (60, 30, 24 * 60))
    week, window = np.timedelta64(7, "D"), WINDOW_NP
    samples: list[Sample] = []
    moments = np.arange(start, end, np.timedelta64(1, "h")).astype(ts.dtype)
    for step, t in enumerate(moments):
        if step % 1000 == 0:
            progress(f"{year}: {step}/{len(moments)} ч, случаев {len(samples)}")
        # те же каналы, что отбирает WINDOW_SQL: тревога за час или рост температуры от 3 °C к медиане за сутки
        chosen: dict[int, dict] = {}
        lo, hi = np.searchsorted(a_ts, t - one_h, "right"), np.searchsorted(a_ts, t, "right")
        for c, n in zip(*np.unique(a_cid[lo:hi], return_counts=True), strict=True):
            chosen[int(c)] = {"alarms": int(n)}
        lo, mid, hi = (np.searchsorted(t_ts, x, "right") for x in (t - day, t - half_h, t))
        if mid < hi:
            now_ids = np.unique(temps["channel_id"][mid:hi].to_numpy())
            agg = (
                temps.slice(lo, hi - lo)
                .filter(pl.col("channel_id").is_in(now_ids))
                .group_by("channel_id")
                .agg(
                    now=pl.col("numeric").filter(pl.col("ts") > _utc(t - half_h)).mean(),
                    base=pl.col("numeric").median(),
                )
            )
            for c, now_v, base_v in agg.iter_rows():
                if c not in chosen and now_v - base_v < 3:
                    continue
                chosen.setdefault(c, {"alarms": 0}).update(now=now_v, base=base_v)
        if not chosen:
            continue
        local = _utc(t).astimezone(MSK)
        by_node: dict[int, list[ChannelWindow]] = defaultdict(list)
        for c, entry in chosen.items():
            m = info[c]
            by_node[m["node_id"]].append(
                ChannelWindow(
                    channel_id=c,
                    sensor_type=m["stype"],
                    name=m["name"],
                    picket=m["picket"],
                    alarms=entry["alarms"],
                    numeric_now=entry.get("now"),
                    numeric_base=entry.get("base"),
                    fault_history=faults(c, local.date()),
                )
            )
        for node_id, channels in by_node.items():
            armed, changed = None, False
            if node_id in guard:
                g_ts, g_armed = guard[node_id]
                i = np.searchsorted(g_ts, t, "right") - 1
                if i >= 0 and t - g_ts[i] <= week:
                    armed, changed = bool(g_armed[i]), bool(t - g_ts[i] <= window)
            ctx = ScenarioContext(local_time=local, guard_armed=armed, guard_changed_recently=changed)
            for task, fn in RISK.items():
                score = fn(channels, ctx).score
                if score < MIN_SCORE:
                    continue
                later = outcome_at.get((task, node_id))
                hit = False
                if later is not None:
                    j = np.searchsorted(later, t + one_h, "right")
                    hit = bool(j < len(later) and later[j] <= t + day)
                samples.append(Sample(task, local, node_id, score, hit))
    return samples


def available_years() -> list[int]:
    years = []
    for path in sorted((settings.ARTIFACTS_DIR / "archive").glob("journal_*.parquet")):
        year = int(path.stem.split("_")[1])
        if year not in EXCLUDED_YEARS:
            years.append(year)
    return years


def calibrate(
    years: list[int] | None = None,
    test_year: int | None = None,
    progress: Callable[[str], None] = lambda _: None,
) -> dict[str, IndicatorCalibration]:
    """
    Выборка по годам архива. Проверка честная: калибровка на годах до test_year применяется к test_year
    (в test — её итоги, «train_period» — на чём обучалась проверяемая версия). Рабочая калибровка
    затем строится по всем годам, включая test_year: уровень повторов меняется от года к году,
    и последний год нужен ей больше всего.
    """
    years = years or available_years()
    if test_year is None:
        test_year = max(years) if len(years) > 1 else None
    train_years = [y for y in years if y != test_year]
    train: list[Sample] = []
    test: list[Sample] = []
    for year in years:
        rows = year_samples(year, progress)
        progress(f"{year}: случаев {len(rows)}")
        (test if year == test_year else train).extend(rows)
    result = {}
    for task in RISK:
        fitted = cal.fit((s.score, s.outcome) for s in train if s.task == task)
        held = [(s.score, s.outcome) for s in test if s.task == task]
        check = {}
        if held:
            base = fitted["base_rate"]
            check = {
                "train_period": _period(train_years),
                "n": len(held),
                "k": sum(y for _, y in held),
                "brier": cal.brier((cal.probability(fitted, x), y) for x, y in held),
                "brier_base": cal.brier((base, y) for _, y in held),
                "brier_index": cal.brier((x, y) for x, y in held),
                "reliability": cal.reliability(fitted, held),
            }
        working = cal.fit((s.score, s.outcome) for s in train + test if s.task == task)
        result[task] = IndicatorCalibration.objects.create(
            task=task,
            period=_period(years),
            test_period=str(test_year) if test_year else "",
            calibration=working,
            test=check,
        )
    return result


def _period(years: list[int]) -> str:
    if not years:
        return ""
    return (
        str(years[0])
        if len(years) == 1
        else f"{years[0]}–{years[-1]}" + (" без 2021" if years[0] < 2021 < years[-1] else "")
    )


def latest() -> dict[str, dict]:
    """Действующие калибровки по задачам (последние записи)."""
    found: dict[str, dict] = {}
    for row in IndicatorCalibration.objects.order_by("-created_at").values("task", "calibration", "period"):
        found.setdefault(row["task"], {**row["calibration"], "period": row["period"]})
    return found

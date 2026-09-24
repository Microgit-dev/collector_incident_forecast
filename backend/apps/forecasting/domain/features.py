"""
Признаки прогноза отказа канала. Одна функция для обучения и для прогноза.

Единица наблюдения — «канал на конец суток d». Каналы СМВУ шлют сообщения в основном при смене
состояния, поэтому по дням без сообщений строится календарная сетка: счётчики равны нулю,
а состояние переносится из последнего известного (last_state).

Метка (слабая, журналов ремонтов нет): в следующие сутки d+1 канал сообщил о неисправности
(state = fault — это и явное «Неисправен», и служебные коды, и артефакт даты 1970).
Прогнозируется **начало** отказа: в выборку попадают только каналы, исправные на конец суток d.
Канал, который уже неисправен, — это факт для правила, а не прогноз.

2021 год исключён из данных, поэтому сетка делится на сегменты, и окна не перескакивают разрыв.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import polars as pl

STATES = ["normal", "warning", "alarm", "fault", "power_loss", "unknown", "event", ""]
COUNTS = ["readings", "warnings", "alarms", "faults", "power_losses", "unknowns", "invalid"]
KEYS = ["channel_id", "segment"]
NO_EVENT = 999  # «давно / никогда» для признаков «дней с последнего…»


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    name: str
    title: str  # шаблон пояснения для карточки прогноза, {v} — значение


SPECS = [
    FeatureSpec("faults_1", "Неисправностей за последние сутки: {v}"),
    FeatureSpec("faults_7", "Неисправностей за 7 суток: {v}"),
    FeatureSpec("faults_30", "Неисправностей за 30 суток: {v}"),
    FeatureSpec("faults_90", "Неисправностей за 90 суток: {v}"),
    FeatureSpec("fault_days_30", "Суток с неисправностями за 30 суток: {v}"),
    FeatureSpec("fault_days_90", "Суток с неисправностями за 90 суток: {v}"),
    FeatureSpec("days_since_fault", "Суток с последней неисправности: {v}"),
    FeatureSpec("power_1", "Потерь питания за сутки: {v}"),
    FeatureSpec("power_7", "Потерь питания за 7 суток: {v}"),
    FeatureSpec("power_30", "Потерь питания за 30 суток: {v}"),
    FeatureSpec("unknown_7", "Неопределённых состояний за 7 суток: {v}"),
    FeatureSpec("unknown_30", "Неопределённых состояний за 30 суток: {v}"),
    FeatureSpec("invalid_7", "Невалидных значений за 7 суток: {v}"),
    FeatureSpec("invalid_30", "Невалидных значений за 30 суток: {v}"),
    FeatureSpec("alarms_7", "Тревог за 7 суток: {v}"),
    FeatureSpec("alarms_30", "Тревог за 30 суток: {v}"),
    FeatureSpec("warnings_7", "Предупреждений за 7 суток: {v}"),
    FeatureSpec("readings_1", "Сообщений за сутки: {v}"),
    FeatureSpec("readings_mean_7", "Сообщений в сутки (среднее за 7 суток): {v}"),
    FeatureSpec("readings_mean_30", "Сообщений в сутки (среднее за 30 суток): {v}"),
    FeatureSpec("readings_ratio", "Активность канала к обычной: {v}"),
    FeatureSpec("silent_days_7", "Суток без сообщений из последних 7: {v}"),
    FeatureSpec("days_since_msg", "Суток с последнего сообщения: {v}"),
    FeatureSpec("last_state", "Состояние на конец суток: {v}"),
    FeatureSpec("num_avg_1", "Среднее значение за сутки: {v}"),
    FeatureSpec("num_delta_7", "Отклонение от среднего за 7 суток: {v}"),
    FeatureSpec("num_std_7", "Разброс суточных значений за 7 суток: {v}"),
    FeatureSpec("num_range_1", "Размах значений за сутки: {v}"),
    FeatureSpec("node_faults_1", "Неисправностей других каналов объекта за сутки: {v}"),
    FeatureSpec("node_faults_7", "Неисправностей других каналов объекта за 7 суток: {v}"),
    FeatureSpec("node_power_1", "Потерь питания на объекте за сутки: {v}"),
    FeatureSpec("node_power_7", "Потерь питания на объекте за 7 суток: {v}"),
    FeatureSpec("sensor_type", "Тип датчика: {v}"),
]
FEATURES = [s.name for s in SPECS]
TITLES = {s.name: s.title for s in SPECS}
CATEGORICAL = ["last_state", "sensor_type"]
# Возраст канала, месяц и день недели проверены и исключены: на отложенном годе они ухудшали
# качество — модель запоминала конкретные каналы и периоды вместо признаков деградации.


def segment_expr(breaks: list[date]) -> pl.Expr:
    """Номер непрерывного участка истории: разрыв (исключённый год) начинает новый сегмент."""
    expr = pl.lit(0, dtype=pl.Int8)
    for i, br in enumerate(sorted(breaks), start=1):
        expr = pl.when(pl.col("day") >= br).then(pl.lit(i, dtype=pl.Int8)).otherwise(expr)
    return expr


def build_grid(daily: pl.DataFrame, end_day: date, excluded: tuple[date, date] | None = None) -> pl.DataFrame:
    """
    Календарная сетка «канал × сутки» от первого появления канала до end_day включительно.
    Дни без сообщений: счётчики 0, состояние — последнее известное.
    """
    spans = daily.group_by("channel_id").agg(pl.col("day").min().alias("start"))
    grid = spans.select(
        "channel_id", pl.date_ranges("start", pl.lit(end_day), interval="1d").alias("day")
    ).explode("day", empty_as_null=True)
    if excluded:
        grid = grid.filter(~pl.col("day").is_between(*excluded))
    breaks = [excluded[1]] if excluded else []
    grid = grid.join(daily, on=["channel_id", "day"], how="left").with_columns(
        segment_expr([date.fromordinal(b.toordinal() + 1) for b in breaks]).alias("segment"),
        *[pl.col(c).fill_null(0) for c in COUNTS],
    )
    return grid.sort(["channel_id", "day"]).with_columns(
        pl.col("last_state").replace("", None).forward_fill().over(KEYS).fill_null(""),
        pl.when(pl.col("readings") > 0)
        .then(pl.col("day"))
        .otherwise(None)
        .forward_fill()
        .over(KEYS)
        .alias("last_msg_day"),
    )


def _roll(col: str, n: int) -> pl.Expr:
    return pl.col(col).rolling_sum(window_size=n, min_samples=1).over(KEYS)


def compute_features(grid: pl.DataFrame, node_daily: pl.DataFrame, meta: pl.DataFrame) -> pl.DataFrame:
    """
    grid — сетка из build_grid (отсортирована по каналу и дню);
    node_daily — по объекту и суткам: node_faults, node_power (сумма по всем каналам объекта);
    meta — channel_id, node_id, sensor_type, first_day.
    """
    fault_day = (pl.col("faults") > 0).cast(pl.Int32)
    g = grid.with_columns(
        fault_day.alias("_fault_day"), (pl.col("readings") == 0).cast(pl.Int32).alias("_silent")
    )
    g = g.with_columns(
        pl.when(pl.col("_fault_day") == 1)
        .then(pl.col("day"))
        .otherwise(None)
        .forward_fill()
        .over(KEYS)
        .alias("_last_fault_day"),
    )
    g = g.join(meta, on="channel_id", how="left").join(node_daily, on=["node_id", "day"], how="left")
    g = g.with_columns(pl.col("node_faults").fill_null(0), pl.col("node_power").fill_null(0))
    g = g.with_columns(
        # объектные счётчики — без собственного канала: иначе признак дублирует faults_*
        (pl.col("node_faults") - pl.col("faults")).alias("_node_faults"),
        (pl.col("node_power") - pl.col("power_losses")).alias("_node_power"),
    )
    days_between = lambda a, b: (pl.col(a) - pl.col(b)).dt.total_days()  # noqa: E731
    feats = g.with_columns(
        pl.col("faults").alias("faults_1"),
        _roll("faults", 7).alias("faults_7"),
        _roll("faults", 30).alias("faults_30"),
        _roll("faults", 90).alias("faults_90"),
        _roll("_fault_day", 30).alias("fault_days_30"),
        _roll("_fault_day", 90).alias("fault_days_90"),
        days_between("day", "_last_fault_day")
        .fill_null(NO_EVENT)
        .clip(upper_bound=NO_EVENT)
        .alias("days_since_fault"),
        pl.col("power_losses").alias("power_1"),
        _roll("power_losses", 7).alias("power_7"),
        _roll("power_losses", 30).alias("power_30"),
        _roll("unknowns", 7).alias("unknown_7"),
        _roll("unknowns", 30).alias("unknown_30"),
        _roll("invalid", 7).alias("invalid_7"),
        _roll("invalid", 30).alias("invalid_30"),
        _roll("alarms", 7).alias("alarms_7"),
        _roll("alarms", 30).alias("alarms_30"),
        _roll("warnings", 7).alias("warnings_7"),
        pl.col("readings").alias("readings_1"),
        (_roll("readings", 7) / 7).alias("readings_mean_7"),
        (_roll("readings", 30) / 30).alias("readings_mean_30"),
        (pl.col("readings") / (_roll("readings", 30) / 30 + 1)).alias("readings_ratio"),
        _roll("_silent", 7).alias("silent_days_7"),
        days_between("day", "last_msg_day")
        .fill_null(NO_EVENT)
        .clip(upper_bound=NO_EVENT)
        .alias("days_since_msg"),
        pl.col("numeric_avg").alias("num_avg_1"),
        (pl.col("numeric_avg") - pl.col("numeric_avg").rolling_mean(7, min_samples=1).over(KEYS)).alias(
            "num_delta_7"
        ),
        pl.col("numeric_avg").rolling_std(7, min_samples=2).over(KEYS).alias("num_std_7"),
        (pl.col("numeric_max") - pl.col("numeric_min")).alias("num_range_1"),
        pl.col("_node_faults").alias("node_faults_1"),
        pl.col("_node_faults").rolling_sum(7, min_samples=1).over(KEYS).alias("node_faults_7"),
        pl.col("_node_power").alias("node_power_1"),
        pl.col("_node_power").rolling_sum(7, min_samples=1).over(KEYS).alias("node_power_7"),
    )
    return feats.with_columns(
        pl.col("last_state").cast(pl.Enum(STATES)),
        pl.col("sensor_type").fill_null("?"),
    )


def with_label(feats: pl.DataFrame, horizon_days: int = 1, sustained: bool = False) -> pl.DataFrame:
    """
    Метка «неисправность в ближайшие horizon_days суток» и время первой из них;
    только каналы, исправные на конец суток, и только строки с полностью наблюдаемым горизонтом.
    sustained — считать только устойчивый отказ: канал остаётся неисправным на конец суток
    (кратковременные сбои с восстановлением тогда не цель, а предвестник).
    """
    if sustained:
        fault_day = (pl.col("last_state") == "fault").cast(pl.Int32)
    else:
        fault_day = (pl.col("faults") > 0).cast(pl.Int32)
    ahead = [fault_day.shift(-k).over(KEYS) for k in range(1, horizon_days + 1)]
    first_ts = [pl.col("first_fault_ts").shift(-k).over(KEYS) for k in range(1, horizon_days + 1)]
    return (
        feats.with_columns(
            (pl.sum_horizontal(ahead) > 0).alias("y"),
            pl.coalesce(first_ts).alias("next_fault_ts"),
            pl.col("day").shift(-horizon_days).over(KEYS).alias("_horizon_end"),
        )
        .filter(pl.col("_horizon_end").is_not_null() & (pl.col("last_state") != "fault"))
        .drop("_horizon_end")
    )


def explain(values: dict, contributions: dict[str, float], top: int = 3) -> list[dict]:
    """Главные факторы, повышающие риск (вклады SHAP в логит), с человекочитаемым текстом."""
    ranked = sorted(((c, f) for f, c in contributions.items() if c > 0), reverse=True)[:top]
    factors = []
    for contribution, feature in ranked:
        value = values.get(feature)
        shown = round(value, 2) if isinstance(value, float) else value
        factors.append(
            {
                "feature": feature,
                "title": TITLES.get(feature, feature).format(v=shown),
                "value": shown,
                "contribution": round(contribution, 4),
            }
        )
    return factors

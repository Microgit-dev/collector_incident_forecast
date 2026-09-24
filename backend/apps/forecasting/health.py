"""
Data Health Score канала и детектор молчания.

Балл 0–100 — взвешенное среднее применимых составляющих (каждая 0..1):
    completeness  полнота: сообщений за 7 суток к обычному для канала числу (периодические каналы);
    freshness     свежесть: сколько «обычных интервалов» прошло с последнего сообщения (периодические);
    technical     доля суток за последние 30, в которые канал на конец дня был в техническом состоянии
                  (неисправен, обесточен, «не определено») — по времени, а не по числу сообщений;
    stability     стабильность частоты: разброс суточного числа сообщений (периодические);
    consistency   согласованность с соседями: среднее за 7 суток против каналов того же типа на объекте.
Каналы, которые шлют сообщения только при смене состояния, не бывают «неполными» или «несвежими»:
для них применимы только technical и consistency.

Молчание: периодический (числовой) канал не прислал данных дольше SILENCE_FACTOR обычных интервалов
(не меньше SILENCE_MIN). Это риск потери связи — технический контур, а не физическая угроза.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import polars as pl

from . import data
from .channel_model import MSK

# Периодический канал — числовое измерение (газ, температура), приходящее не реже раза в час.
# Дискретные каналы (движение, двери, модули) шлют сообщения по событию: их тишина — норма.
PERIODIC_MIN_PER_DAY = 24
SILENCE_FACTOR = 6
SILENCE_MIN = timedelta(hours=1)
FRESH_OUTAGE = timedelta(hours=24)  # о давних отключениях не тревожим: они уже известны
WEIGHTS = {"completeness": 0.25, "freshness": 0.25, "technical": 0.25, "stability": 0.15, "consistency": 0.10}
TECH_STATES = ["fault", "unknown", "power_loss"]


@dataclass(frozen=True, slots=True)
class Health:
    channel_id: int
    node_id: int
    score: int
    components: dict
    periodic: bool
    expected_interval_s: int | None
    last_seen_at: datetime | None
    silent: bool


def _clip01(expr: pl.Expr) -> pl.Expr:
    return expr.clip(0.0, 1.0)


def score_frame(
    daily: pl.DataFrame, last_seen: pl.DataFrame, meta: pl.DataFrame, as_of: datetime
) -> pl.DataFrame:
    """Чистое вычисление по суточным строкам за 90 суток (последняя — скользящие 24 часа)."""
    from .domain.features import build_grid

    end = daily["day"].max()
    # Календарная сетка: состояние переносится на дни без сообщений — так считается время в состоянии
    d = build_grid(daily, end).with_columns((pl.lit(end) - pl.col("day")).dt.total_days().alias("age"))
    per_channel = d.group_by("channel_id").agg(
        pl.col("readings").filter(pl.col("readings") > 0).median().alias("median_daily"),
        # Интервал — по «тихим» суткам (10-й процентиль), а не по медиане: ночью и в выходные
        # числовые датчики шлют реже, и порог по медиане давал бы ложное «молчание»
        pl.col("readings").filter(pl.col("readings") > 0).quantile(0.1).alias("low_daily"),
        pl.col("readings").filter(pl.col("age") < 7).sum().alias("readings_7"),
        pl.col("readings").filter(pl.col("age") < 30).sum().alias("readings_30"),
        pl.col("last_state").is_in(TECH_STATES).filter(pl.col("age") < 30).mean().alias("tech_share_30"),
        pl.col("readings").filter((pl.col("age") < 30) & (pl.col("readings") > 0)).std().alias("std_30"),
        pl.col("readings").filter((pl.col("age") < 30) & (pl.col("readings") > 0)).mean().alias("mean_30"),
        pl.col("numeric_avg").filter(pl.col("age") < 7).mean().alias("num_7"),
    )
    f = per_channel.join(
        meta.select("channel_id", "node_id", "sensor_type", "value_kind"), on="channel_id"
    ).join(last_seen, on="channel_id", how="left")
    f = f.with_columns(
        (pl.col("value_kind").is_in(["numeric", "mixed"]) & (pl.col("median_daily") >= PERIODIC_MIN_PER_DAY))
        .fill_null(False)
        .alias("periodic"),
        (86400 / pl.col("low_daily").clip(lower_bound=1)).round().cast(pl.Int64).alias("interval_s"),
    ).with_columns(
        ((pl.lit(as_of) - pl.col("last_seen_at")).dt.total_seconds()).alias("gap_s"),
    )
    # Соседи: каналы того же типа на объекте, если их не меньше трёх
    group = ["node_id", "sensor_type"]
    f = f.with_columns(
        pl.col("num_7").median().over(group).alias("_med"),
        (pl.col("num_7") - pl.col("num_7").median().over(group)).abs().median().over(group).alias("_mad"),
        pl.col("num_7").count().over(group).alias("_n"),
    )
    periodic = pl.col("periodic")
    f = f.with_columns(
        pl.when(periodic)
        .then(_clip01(pl.col("readings_7") / (7 * pl.col("median_daily"))))
        .alias("completeness"),
        pl.when(periodic)
        .then(_clip01(1 - (pl.col("gap_s") / pl.col("interval_s") - 3) / 21).fill_null(0.0))
        .alias("freshness"),
        pl.when(pl.col("tech_share_30").is_not_null())
        .then(_clip01(1 - pl.col("tech_share_30")))
        .alias("technical"),
        pl.when(periodic & (pl.col("mean_30") > 0))
        .then(_clip01(1 - pl.col("std_30").fill_null(0) / pl.col("mean_30")))
        .alias("stability"),
        pl.when(pl.col("num_7").is_not_null() & (pl.col("_n") >= 3))
        .then(
            _clip01(1 - ((pl.col("num_7") - pl.col("_med")).abs() / (1.4826 * pl.col("_mad") + 0.5) - 3) / 3)
        )
        .alias("consistency"),
        (
            periodic
            & (
                pl.col("gap_s")
                > pl.max_horizontal(pl.col("interval_s") * SILENCE_FACTOR, SILENCE_MIN.total_seconds())
            )
        )
        .fill_null(False)
        .alias("silent"),
    )
    weighted = [pl.col(k) * w for k, w in WEIGHTS.items()]
    present = [pl.col(k).is_not_null().cast(pl.Float64) * w for k, w in WEIGHTS.items()]
    return f.with_columns(
        (100 * pl.sum_horizontal(weighted) / pl.sum_horizontal(present))
        .fill_nan(None)
        .fill_null(0)
        .round()
        .cast(pl.Int16)
        .alias("score")
    )


def compute(as_of: datetime) -> list[Health]:
    meta = data.load_meta()
    today = as_of.astimezone(MSK).date()
    history = data.load_daily(today - timedelta(days=90), today)
    window = data.load_window(as_of)
    frames = [
        f
        for f in (history, window.select(history.columns) if not window.is_empty() else window)
        if not f.is_empty()
    ]
    if not frames:
        return []
    daily = pl.concat(frames, how="vertical_relaxed")
    # Последнее сообщение — из самих данных до as_of: так расчёт верен и для исторического момента
    last_seen = daily.group_by("channel_id").agg(pl.col("last_ts").max().alias("last_seen_at"))
    frame = score_frame(daily, last_seen, meta, as_of)
    result = []
    for r in frame.iter_rows(named=True):
        result.append(
            Health(
                channel_id=r["channel_id"],
                node_id=r["node_id"],
                score=int(r["score"]),
                components={k: (round(r[k], 3) if r[k] is not None else None) for k in WEIGHTS},
                periodic=r["periodic"],
                expected_interval_s=r["interval_s"] if r["periodic"] else None,
                last_seen_at=r["last_seen_at"],
                silent=r["silent"],
            )
        )
    return result

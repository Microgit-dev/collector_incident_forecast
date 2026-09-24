"""
Применение разметки диспетчеров к обучающей выборке. Чистые функции над Polars.

Метка относится к каналу и дате события L. Строка выборки «канал на конец суток d»
прогнозирует события в сутки d+1 … d+h, поэтому метка затрагивает строки с d ∈ [L−h, L−1]:
    positive — это был отказ датчика: y = 1, вес × weight;
    negative — это не отказ датчика (сбой питания, связи): y = 0, вес × weight;
    exclude  — строка не годится для обучения (плановые работы, санкционированный доступ,
               предотвращённый отказ): строка удаляется.
Если на одну строку попали разные метки, приоритет: exclude > negative > positive.
Исходная метка сохраняется в y_orig — по ней обучается контрольная модель «без разметки».
"""

from __future__ import annotations

from datetime import timedelta

import polars as pl

PRIORITY = {"exclude": 3, "negative": 2, "positive": 1}
LABEL_SCHEMA = {
    "label_id": pl.Int64,
    "channel_id": pl.Int64,
    "label_date": pl.Date,
    "effect": pl.String,
    "weight": pl.Float64,
}


def empty_labels() -> pl.DataFrame:
    return pl.DataFrame(schema=LABEL_SCHEMA)


def label_rows(frame: pl.DataFrame, labels: pl.DataFrame, horizon_days: int) -> pl.DataFrame:
    """Какие строки (channel_id, day) затрагивает каждая метка: label_id, channel_id, day, effect, weight."""
    if labels.is_empty() or frame.is_empty():
        return pl.DataFrame(schema=LABEL_SCHEMA | {"day": pl.Date})
    rows = frame.select("channel_id", "day").join(labels, on="channel_id")
    return rows.filter(
        (pl.col("day") >= pl.col("label_date") - timedelta(days=horizon_days))
        & (pl.col("day") <= pl.col("label_date") - timedelta(days=1))
    )


def apply_labels(
    frame: pl.DataFrame, labels: pl.DataFrame, horizon_days: int
) -> tuple[pl.DataFrame, dict, dict]:
    """
    frame — строки с y (до прореживания). Возвращает (новая выборка, статистика по эффектам,
    число затронутых строк по каждой метке). Добавляет колонки y_orig и fb_weight, fb (bool).
    """
    base = frame.with_columns(
        pl.col("y").alias("y_orig"), pl.lit(1.0).alias("fb_weight"), pl.lit(False).alias("fb")
    )
    hits = label_rows(frame, labels, horizon_days)
    if hits.is_empty():
        return base, {}, {}
    per_label = dict(hits.group_by("label_id").len().iter_rows())
    # Одна итоговая метка на строку: самый «сильный» эффект, вес — максимальный среди меток этого эффекта
    resolved = (
        hits.with_columns(pl.col("effect").replace_strict(PRIORITY, return_dtype=pl.Int8).alias("_p"))
        .sort("_p", "weight", descending=True)
        .group_by("channel_id", "day")
        .agg(pl.col("effect").first().alias("fb_effect"), pl.col("weight").first().alias("fb_w"))
    )
    joined = base.join(resolved, on=["channel_id", "day"], how="left")
    stats = {}
    for effect in PRIORITY:
        part = joined.filter(pl.col("fb_effect") == effect)
        stats[effect] = {
            "rows": len(part),
            "flipped": int((part["y"] != (effect == "positive")).sum()) if effect != "exclude" else 0,
            "positives_removed": int(part["y"].sum()) if effect == "exclude" else 0,
        }
    out = (
        joined.filter(pl.col("fb_effect").is_null() | (pl.col("fb_effect") != "exclude"))
        .with_columns(
            pl.when(pl.col("fb_effect") == "positive")
            .then(True)
            .when(pl.col("fb_effect") == "negative")
            .then(False)
            .otherwise(pl.col("y"))
            .alias("y"),
            pl.col("fb_w").fill_null(1.0).alias("fb_weight"),
            pl.col("fb_effect").is_not_null().alias("fb"),
        )
        .drop("fb_effect", "fb_w")
    )
    return out, stats, per_label


def merge_stats(total: dict, part: dict) -> dict:
    for effect, values in part.items():
        acc = total.setdefault(effect, {k: 0 for k in values})
        for k, v in values.items():
            acc[k] += v
    return total

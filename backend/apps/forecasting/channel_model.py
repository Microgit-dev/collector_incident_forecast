"""
Прогноз события по каналу на горизонт 24 ч (или больше) — LightGBM. Общий конвейер для задач
из specs.py: отказ датчика, превышение 1 % метана, подтопление.

Обучение — на суточной витрине за всю историю, валидация строго по времени:
обучение до 2025 года, 2025 год — подбор порогов и ранняя остановка, 2026 год — отложенный тест.
Отрицательных примеров в сотни раз больше, чем положительных, поэтому они прореживаются
(детерминированно по хешу канал-сутки) с весом 1/доля: метрики и вероятности остаются
несмещёнными относительно полной выборки.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl
from django.conf import settings

from . import data
from .domain import features as F
from .domain.contracts import Factor, ForecastResult
from .specs import SENSOR_FAILURE, TaskSpec

logger = logging.getLogger(__name__)

MSK = ZoneInfo("Europe/Moscow")
HORIZON_HOURS = 24
HISTORY_DAYS = 100  # глубина истории для признаков при прогнозе (окна до 90 суток)
CHUNK = 1500  # каналов за проход при сборке выборки — ограничивает пиковую память
NEG_RATE = 0.05
VALID_FROM, TEST_FROM = date(2025, 1, 1), date(2026, 1, 1)
TARGET_PRECISION, TARGET_RECALL = 0.7, 0.5


PARAMS = {
    "objective": "binary",
    "metric": "average_precision",
    "learning_rate": 0.03,
    "num_leaves": 31,
    "min_data_in_leaf": 1000,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l2": 1.0,
    "verbose": -1,
    "num_threads": 4,
    "seed": 42,
}

Progress = Callable[[float, str], None]


def _noop(fraction: float, stage: str) -> None:
    pass


# ---------- выборка ----------


def _keep_negative(frame: pl.DataFrame, rate: float) -> pl.Expr:
    """Все положительные, все размеченные диспетчерами и доля rate отрицательных (по хешу)."""
    bucket = (pl.col("channel_id") * 1_000_003 + pl.col("day").dt.epoch("d")) % 1000
    return pl.col("y") | pl.col("y_orig") | pl.col("fb") | (bucket < int(rate * 1000))


def _task_meta(meta: pl.DataFrame, spec: TaskSpec) -> pl.DataFrame:
    return meta.filter(pl.col("sensor_type").is_in(spec.sensor_types)) if spec.sensor_types else meta


def build_dataset(
    spec: TaskSpec = SENSOR_FAILURE,
    progress: Progress = _noop,
    neg_rate: float | None = None,
    horizon_days: int = 1,
    use_cache: bool = True,
    labels: pl.DataFrame | None = None,
) -> tuple[pl.DataFrame, dict, dict]:
    """
    Выборка кешируется в artifacts/models: повторное обучение на тех же данных и той же разметке
    её не пересобирает. Возвращает (выборка, статистика разметки по эффектам, строк по каждой метке).
    """
    from .domain.feedback import empty_labels
    from .feedback import labels_fingerprint

    labels = labels if labels is not None else empty_labels()
    neg_rate = neg_rate or spec.neg_rate
    # Конец выборки — последние полные сутки: одиночные сутки после них (тестовый прогон) дали бы
    # месяцы «пустых» дней без событий и завысили бы метрики
    last = data.last_complete_day() or data.last_daily_day()
    name = f"dataset_{spec.task}_{last:%Y%m%d}_{neg_rate:g}_h{horizon_days}_{labels_fingerprint(labels)}"
    cache = settings.ARTIFACTS_DIR / "models" / f"{name}.parquet"
    stats_file = cache.with_suffix(".json")
    if use_cache and cache.exists() and stats_file.exists():
        progress(1, "Выборка взята из кеша")
        saved = json.loads(stats_file.read_text(encoding="utf-8"))
        return pl.read_parquet(cache), saved["stats"], {int(k): v for k, v in saved["per_label"].items()}
    frame, stats, per_label = _collect(spec, progress, neg_rate, last, horizon_days, labels)
    cache.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(cache)
    stats_file.write_text(json.dumps({"stats": stats, "per_label": per_label}), encoding="utf-8")
    return frame, stats, per_label


def _collect(
    spec: TaskSpec, progress: Progress, neg_rate: float, last: date, horizon_days: int, labels: pl.DataFrame
) -> tuple[pl.DataFrame, dict, dict]:
    from .domain.feedback import apply_labels, merge_stats

    all_meta = data.load_meta()
    meta = _task_meta(all_meta, spec)
    excluded = data.excluded_range()
    first = meta["first_day"].min()
    nodes = data.load_node_daily()
    ids = sorted(meta.filter(pl.col("first_day").is_not_null())["channel_id"].to_list())
    chunks = [ids[i : i + CHUNK] for i in range(0, len(ids), CHUNK)]
    parts, stats, per_label = [], {}, {}
    for i, chunk in enumerate(chunks):
        progress(i / len(chunks), f"Признаки: каналы {i * CHUNK + 1}–{i * CHUNK + len(chunk)} из {len(ids)}")
        daily = data.load_daily(first, last + timedelta(days=1), chunk)
        if daily.is_empty():
            continue
        grid = F.build_grid(daily, last, excluded)
        feats = F.compute_features(grid, nodes, meta.filter(pl.col("channel_id").is_in(chunk)))
        labelled = F.with_label(feats, horizon_days, spec.event(), spec.healthy(), spec.event_ts)
        chunk_labels = labels.filter(pl.col("channel_id").is_in(chunk))
        labelled, part_stats, part_rows = apply_labels(labelled, chunk_labels, horizon_days)
        merge_stats(stats, part_stats)
        per_label.update(part_rows)
        # Вес прореживания считается по исходной метке: строки, которые попали бы в выборку и без
        # разметки, весят так же; размеченные дополнительно умножаются на вес правила
        sampled = (
            labelled.filter(_keep_negative(labelled, neg_rate))
            .with_columns(
                pl.when(pl.col("y_orig") | pl.col("fb"))
                .then(1.0)
                .otherwise(1 / neg_rate)
                .alias("weight_orig")
            )
            .with_columns((pl.col("weight_orig") * pl.col("fb_weight")).alias("weight"))
        )
        parts.append(
            sampled.select(
                "channel_id",
                "day",
                "y",
                "y_orig",
                "fb",
                "weight",
                "weight_orig",
                "next_fault_ts",
                *spec.features,
            )
        )
    progress(1, "Выборка собрана")
    return pl.concat(parts), stats, per_label


# ---------- матрица признаков ----------


def matrix_columns(features: list[str] = F.FEATURES) -> list[str]:
    return [f for f in features if f not in F.CATEGORICAL] + F.CATEGORICAL


def to_matrix(frame: pl.DataFrame, sensor_types: list[str], columns: list[str] | None = None) -> np.ndarray:
    columns = columns or matrix_columns()
    codes = {name: i for i, name in enumerate(sensor_types)}
    return frame.select(
        *[pl.col(f).cast(pl.Float32) for f in columns if f not in F.CATEGORICAL],
        pl.col("last_state").to_physical().cast(pl.Float32),
        pl.col("sensor_type").replace_strict(codes, default=-1).cast(pl.Float32),
    ).to_numpy()


# ---------- метрики ----------


def _pr(y: np.ndarray, pred: np.ndarray, w: np.ndarray) -> tuple[float, float]:
    tp = float((w * (pred & y)).sum())
    predicted, actual = float((w * pred).sum()), float((w * y).sum())
    return (tp / predicted if predicted else 0.0), (tp / actual if actual else 0.0)


def pick_threshold(y: np.ndarray, p: np.ndarray, w: np.ndarray, precision: float) -> float | None:
    """Наименьший порог с точностью не ниже заданной, т. е. максимальная полнота при ограничении."""
    order = np.argsort(-p)
    ys, ws, ps = y[order], w[order], p[order]
    tp = np.cumsum(ws * ys)
    predicted = np.cumsum(ws)
    prec = tp / predicted
    ok = np.where(prec >= precision)[0]
    ok = ok[ok >= 20]  # не меньше 20 срабатываний, иначе порог случаен
    return float(ps[ok.max()]) if len(ok) else None


def evaluate(y, p, w, threshold: float, frame: pl.DataFrame | None = None) -> dict:
    from sklearn.metrics import average_precision_score, roc_auc_score

    pred = p >= threshold
    precision, recall = _pr(y, pred, w)
    result = {
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(2 * precision * recall / (precision + recall), 3) if precision + recall else 0.0,
        "pr_auc": round(float(average_precision_score(y, p, sample_weight=w)), 3),
        "roc_auc": round(float(roc_auc_score(y, p, sample_weight=w)), 3),
        "base_rate": round(float((w * y).sum() / w.sum()), 5),
        "alerts_per_day": None,
        "onsets": int(y.sum()),
    }
    if frame is not None:
        days = frame["day"].n_unique()
        result["alerts_per_day"] = round(float((w * pred).sum()) / max(days, 1), 1)
        # Упреждение: от момента прогноза (конец суток d) до первого события в горизонте
        issued = frame["day"].cast(pl.Datetime("us")).dt.replace_time_zone(str(MSK)).dt.convert_time_zone(
            "UTC"
        ) + timedelta(days=1)
        lead = ((frame["next_fault_ts"] - issued).dt.total_minutes() / 60).fill_null(np.nan).to_numpy()
        hits = pred & y & ~np.isnan(lead)
        if hits.any():
            result["lead_time_hours"] = {
                "median": round(float(np.median(lead[hits])), 1),
                "p25": round(float(np.percentile(lead[hits], 25)), 1),
                "p75": round(float(np.percentile(lead[hits], 75)), 1),
            }
    return result


# ---------- обучение ----------


@dataclass
class TrainResult:
    version: str
    artifact: Path
    metrics: dict
    params: dict
    train_period: dict
    sensor_types: list[str]
    columns: list[str]
    per_label: dict | None = None


def _fit(xy: dict, columns: list[str], params: dict):
    import lightgbm as lgb

    cat_idx = [columns.index(c) for c in F.CATEGORICAL]
    train_set = lgb.Dataset(
        *xy["train"][:2], weight=xy["train"][2], feature_name=columns, categorical_feature=cat_idx
    )
    valid_set = lgb.Dataset(*xy["valid"][:2], weight=xy["valid"][2], reference=train_set)
    return lgb.train(
        params,
        train_set,
        num_boost_round=2000,
        valid_sets=[valid_set],
        callbacks=[lgb.early_stopping(100, verbose=False), lgb.log_evaluation(0)],
    )


def _pr_auc(y, p, w) -> float:
    from sklearn.metrics import average_precision_score

    return round(float(average_precision_score(y, p, sample_weight=w)), 4)


def champion_score(champion_artifact: str | None, frame: pl.DataFrame, y, w) -> float | None:
    """PR-AUC действующей версии на той же валидации, что и новая: сравнение на равных."""
    if not champion_artifact or not Path(champion_artifact).exists():
        return None
    booster, meta = _load(champion_artifact)
    missing = [c for c in meta["columns"] if c not in frame.columns]
    if missing:
        return None
    return _pr_auc(y, booster.predict(to_matrix(frame, meta["sensor_types"], meta["columns"])), w)


def train(
    spec: TaskSpec = SENSOR_FAILURE,
    progress: Progress = _noop,
    neg_rate: float | None = None,
    horizon_hours: int = HORIZON_HOURS,
    labels: pl.DataFrame | None = None,
    champion_artifact: str | None = None,
) -> TrainResult:
    started = time.monotonic()
    horizon_days = max(1, horizon_hours // 24)
    params = PARAMS | spec.params
    neg_rate = neg_rate or spec.neg_rate
    dataset, fb_stats, per_label = build_dataset(
        spec, lambda f, s: progress(f * 0.6, s), neg_rate, horizon_days, labels=labels
    )
    sensor_types = sorted(dataset["sensor_type"].unique().to_list())
    columns = matrix_columns(spec.features)
    parts = {
        "train": dataset.filter(pl.col("day") < VALID_FROM),
        "valid": dataset.filter(pl.col("day").is_between(VALID_FROM, TEST_FROM, closed="left")),
        "test": dataset.filter(pl.col("day") >= TEST_FROM),
    }
    xy = {
        k: (to_matrix(v, sensor_types, columns), v["y"].to_numpy(), v["weight"].to_numpy())
        for k, v in parts.items()
    }
    progress(0.62, f"Обучение LightGBM: {len(parts['train']):,} примеров".replace(",", " "))
    booster = _fit(xy, columns, params)
    progress(0.9, "Подбор порогов и оценка на отложенном 2026 году")
    scores = {k: booster.predict(v[0], num_iteration=booster.best_iteration) for k, v in xy.items()}

    yv, wv = xy["valid"][1], xy["valid"][2]
    # Порог уровня — наименьший, при котором точность на 2025 годе не ниже заданной
    found = {k: pick_threshold(yv, scores["valid"], wv, prec) for k, prec in spec.level_precision.items()}
    fallback = float(np.quantile(scores["valid"], 0.999))
    levels = {"medium": found["medium"] or fallback / 4}
    levels["high"] = max(found["high"] or fallback / 2, levels["medium"])
    levels["critical"] = max(found["critical"] or fallback, levels["high"])
    levels = {k: round(v, 4) for k, v in levels.items()}
    high = levels["high"]
    target_met = found["critical"] is not None

    test = parts["test"]
    base_p, base_r = _pr(xy["test"][1], spec.baseline(test), xy["test"][2])
    importance = dict(zip(columns, booster.feature_importance("gain").tolist(), strict=True))
    by_type = {}
    for stype in sensor_types:
        mask = (test["sensor_type"] == stype).to_numpy()
        if xy["test"][1][mask].sum() >= 10:
            p, r = _pr(xy["test"][1][mask], scores["test"][mask] >= high, xy["test"][2][mask])
            by_type[stype] = {
                "precision": round(p, 3),
                "recall": round(r, 3),
                "onsets": int(xy["test"][1][mask].sum()),
            }

    metrics = {
        "task": spec.task,
        "event": spec.event_title,
        "threshold": levels["high"],
        "levels": levels,
        "level_precision": spec.level_precision,
        "target": {
            "precision": TARGET_PRECISION,
            "recall": TARGET_RECALL,
            "precision_reached_on_valid": target_met,
        },
        "horizon_hours": horizon_hours,
        "valid": evaluate(yv, scores["valid"], wv, high, parts["valid"]),
        "test": evaluate(xy["test"][1], scores["test"], xy["test"][2], high, test),
        # Реализованные точность и полнота каждого уровня на отложенном годе
        "levels_test": {
            k: evaluate(xy["test"][1], scores["test"], xy["test"][2], t, test) for k, t in levels.items()
        },
        "baseline_test": {
            "rule": spec.baseline_rule,
            "precision": round(base_p, 3),
            "recall": round(base_r, 3),
        },
        "by_sensor_type_test": by_type,
        "feature_importance": dict(sorted(importance.items(), key=lambda kv: -kv[1])[:15]),
        "rows": {k: len(v) for k, v in parts.items()},
        "channels": int(dataset["channel_id"].n_unique()),
        "negative_sampling": neg_rate,
        "best_iteration": booster.best_iteration,
        "train_seconds": round(time.monotonic() - started),
    }
    metrics["feedback"] = _feedback_metrics(
        parts, xy, scores, columns, params, fb_stats, per_label, labels, progress
    )
    champion = champion_score(champion_artifact, parts["valid"], xy["valid"][1], xy["valid"][2])
    metrics["comparison"] = {
        "valid_pr_auc": _pr_auc(xy["valid"][1], scores["valid"], xy["valid"][2]),
        "champion_valid_pr_auc": champion,
    }
    version = datetime.now(MSK).strftime("%Y.%m.%d-%H%M") + f"-h{horizon_hours}"
    folder = settings.ARTIFACTS_DIR / "models"
    folder.mkdir(parents=True, exist_ok=True)
    artifact = folder / f"{spec.task}_{version}.txt"
    booster.save_model(str(artifact), num_iteration=booster.best_iteration)
    artifact.with_suffix(".json").write_text(
        json.dumps(
            {
                "task": spec.task,
                "columns": columns,
                "sensor_types": sensor_types,
                "levels": levels,
                "horizon_hours": horizon_hours,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    period = {
        "train": [str(parts["train"]["day"].min()), str(VALID_FROM - timedelta(days=1))],
        "valid": [str(VALID_FROM), str(TEST_FROM - timedelta(days=1))],
        "test": [str(TEST_FROM), str(test["day"].max())],
        "excluded": "2021 — переход на новую систему мониторинга",
    }
    progress(1, "Модель обучена")
    return TrainResult(
        version,
        artifact,
        metrics,
        params | {"rounds": booster.best_iteration},
        period,
        sensor_types,
        columns,
        per_label=per_label,
    )


def _feedback_metrics(parts, xy, scores, columns, params, fb_stats, per_label, labels, progress) -> dict:
    """
    Что дала разметка диспетчеров: контрольная модель на тех же строках, но с исходными
    (слабыми) метками. Обе модели оцениваются на выборках с учётом разметки — это лучшая
    доступная «правда», поэтому разница показывает вклад решений диспетчеров.
    """
    used = int(labels.height) if labels is not None else 0
    result = {"labels": used, "labels_matched": len(per_label), "effects": fb_stats}
    changed = sum(v.get("rows", 0) for v in fb_stats.values())
    if not used or not changed:
        result["ablation"] = None
        return result
    progress(0.95, "Контрольная модель без разметки диспетчеров")
    xy_orig = {
        k: (xy[k][0], parts[k]["y_orig"].to_numpy(), parts[k]["weight_orig"].to_numpy())
        for k in ("train", "valid")
    }
    control = _fit(xy_orig, columns, params)
    result["ablation"] = {
        part: {
            "with_feedback": _pr_auc(xy[part][1], scores[part], xy[part][2]),
            "without_feedback": _pr_auc(
                xy[part][1], control.predict(xy[part][0], num_iteration=control.best_iteration), xy[part][2]
            ),
        }
        for part in ("valid", "test")
    }
    return result


# ---------- прогноз ----------


@lru_cache(maxsize=8)
def _load(artifact: str):
    import lightgbm as lgb

    meta = json.loads(Path(artifact).with_suffix(".json").read_text(encoding="utf-8"))
    return lgb.Booster(model_file=artifact), meta


def inference_features(
    as_of: datetime, node_ids: list[int] | None = None, spec: TaskSpec = SENSOR_FAILURE
) -> pl.DataFrame:
    """Признаки на момент as_of: суточная витрина до вчера + скользящие последние 24 часа."""
    all_meta = data.load_meta()
    meta = _task_meta(all_meta, spec)
    if node_ids:
        meta = meta.filter(pl.col("node_id").is_in(node_ids))
    if meta.is_empty():
        return pl.DataFrame()
    today = as_of.astimezone(MSK).date()
    restrict = meta["channel_id"].to_list() if (node_ids or spec.sensor_types) else None
    history = data.load_daily(today - timedelta(days=HISTORY_DAYS), today, restrict)
    window_all = data.load_window(as_of)
    window = window_all
    if not window.is_empty():
        window = window.with_columns(pl.lit(today).alias("day")).select(
            history.columns if not history.is_empty() else window.columns
        )
    frames = [f for f in (history, window) if not f.is_empty()]
    if not frames:
        return pl.DataFrame()
    daily = pl.concat(frames, how="vertical_relaxed").filter(
        pl.col("channel_id").is_in(meta["channel_id"].implode())
    )
    if daily.is_empty():
        return pl.DataFrame()
    end_day = today if not window.is_empty() else today - timedelta(days=1)
    grid = F.build_grid(daily, end_day, data.excluded_range())
    # Каскадные признаки объекта — по всем его каналам, как при обучении, а не только по каналам задачи
    nodes = data.load_node_daily(today - timedelta(days=HISTORY_DAYS), today)
    if not window_all.is_empty():
        nodes = pl.concat(
            [nodes, data.node_daily(window_all.with_columns(pl.lit(today).alias("day")), all_meta)],
            how="vertical_relaxed",
        )
    nodes = nodes.with_columns(pl.col("node_faults").cast(pl.Int32), pl.col("node_power").cast(pl.Int32))
    feats = F.compute_features(grid, nodes, meta)
    return feats.filter((pl.col("day") == end_day) & spec.healthy().fill_null(True))


class ChannelForecaster:
    def __init__(self, spec: TaskSpec, artifact: str, medium_threshold: float):
        self.spec = spec
        self.task = spec.task
        self.booster, self.meta = _load(artifact)
        self.medium_threshold = medium_threshold
        self.horizon_hours = self.meta.get("horizon_hours", HORIZON_HOURS)

    def predict(self, as_of: datetime, node_ids: list[int] | None = None) -> list[ForecastResult]:
        feats = inference_features(as_of, node_ids, self.spec)
        if feats.is_empty():
            return []
        columns = self.meta["columns"]
        x = to_matrix(feats, self.meta["sensor_types"], columns)
        p = self.booster.predict(x)
        # Вклады признаков (SHAP) считаем только там, где риск заметен: карточку откроют только для них
        risky = np.where(p >= self.medium_threshold)[0]
        contrib = self.booster.predict(x[risky], pred_contrib=True) if len(risky) else np.empty((0, 0))
        names = [c for c in columns if c in feats.columns]
        rows = feats.select("channel_id", "node_id", *names).with_columns(
            pl.col("last_state").cast(pl.String)
        )
        by_row = {int(i): c for i, c in zip(risky, contrib, strict=True)}
        results = []
        for i, row in enumerate(rows.iter_rows(named=True)):
            factors = []
            if i in by_row:
                values = {k: row[k] for k in names}
                factors = [
                    Factor(**f)
                    for f in F.explain(values, dict(zip(columns, by_row[i][:-1].tolist(), strict=True)))
                ]
            results.append(
                ForecastResult(
                    node_id=row["node_id"],
                    channel_id=row["channel_id"],
                    probability=float(p[i]),
                    horizon_hours=self.horizon_hours,
                    factors=factors,
                )
            )
        return results

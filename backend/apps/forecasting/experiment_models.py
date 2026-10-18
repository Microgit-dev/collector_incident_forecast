"""Shared experiment estimators; optional CatBoost itself is loaded only by its runner."""

import numpy as np
import polars as pl
from sklearn.metrics import average_precision_score

from . import channel_model as M
from .domain import features as F
from .experiments import budget_threshold

CATBOOST_PARAMS = {
    "iterations": 400,
    "learning_rate": 0.05,
    "l2_leaf_reg": 3,
    "loss_function": "Logloss",
    "eval_metric": "Logloss",
    "use_best_model": False,
    "random_seed": 42,
    "thread_count": 4,
    "task_type": "CPU",
    "allow_writing_files": False,
    "verbose": 50,
}
TREE_CHECKPOINTS = [50, 100, 200, 400]


def predict_batches(model, x, batch=100_000):
    return np.concatenate([model.predict_proba(x[i : i + batch])[:, 1] for i in range(0, len(x), batch)])


def logistic_pipeline(columns):
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    from .domain.features import CATEGORICAL

    cat = [columns.index(name) for name in CATEGORICAL]
    numeric = [i for i in range(len(columns)) if i not in cat]
    return Pipeline(
        [
            (
                "features",
                ColumnTransformer(
                    [
                        (
                            "numeric",
                            Pipeline(
                                [
                                    ("impute", SimpleImputer(keep_empty_features=True)),
                                    ("scale", StandardScaler()),
                                ]
                            ),
                            numeric,
                        ),
                        ("category", OneHotEncoder(handle_unknown="ignore"), cat),
                    ]
                ),
            ),
            ("classifier", LogisticRegression(max_iter=500, tol=1e-4, random_state=42)),
        ]
    )


def cat_frame(frame, columns):
    result = frame.select(
        *[pl.col(c).cast(pl.Float32) for c in columns if c not in F.CATEGORICAL],
        *[pl.col(c).cast(pl.String) for c in F.CATEGORICAL],
    ).to_pandas()
    for col in F.CATEGORICAL:
        result[col] = result[col].astype("category")
    return result


def choose_trial(trials):
    return max(trials, key=lambda r: (r["validation_recall_at_20"], r["validation_ap"]))


def validation_trial(y, p, days, depth, trees):
    threshold = budget_threshold(p, 20 * days)
    _, recall = M._pr(y, p >= threshold, np.ones(len(y)))
    return {
        "depth": depth,
        "trees": trees,
        "validation_recall_at_20": recall,
        "validation_ap": float(average_precision_score(y, p)),
    }

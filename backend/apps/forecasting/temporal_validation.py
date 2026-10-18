"""H10 retrospective rolling validation. No 2026 observations in any fold."""

import hashlib
from dataclasses import dataclass
from datetime import date, timedelta

import polars as pl

from .offline import ParquetHistory


@dataclass(frozen=True)
class TemporalFold:
    year: int

    @property
    def valid_from(self):
        return date(self.year, 1, 1)

    @property
    def test_from(self):
        return date(self.year, 7, 1)

    @property
    def end(self):
        return date(self.year + 1, 1, 1)

    def split(self, frame, horizon_days=1):
        if horizon_days < 1:
            raise ValueError("Positive horizon required")
        day = pl.col("day")
        target_end = day + timedelta(days=horizon_days)
        return {
            "train": frame.filter(target_end < self.valid_from),
            "valid": frame.filter((day >= self.valid_from) & (target_end < self.test_from)),
            "test": frame.filter((day >= self.test_from) & (target_end < self.end)),
        }


class TemporalHistory(ParquetHistory):
    """Restrict all daily, node, metadata and coverage scans before assembling features."""

    def __init__(self, folder, cutoff):
        super().__init__(folder)
        self.cutoff = cutoff
        self.paths = [path for path, year in zip(self.paths, self.years, strict=True) if year <= cutoff.year]
        self.years = [year for year in self.years if year <= cutoff.year]
        if not self.paths:
            raise ValueError("No history before cutoff")
        self.cache_key = hashlib.sha256(f"{self.cache_key}:{cutoff.isoformat()}".encode()).hexdigest()[:20]

    def _scan(self):
        return super()._scan().filter(pl.col("day") <= self.cutoff)


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

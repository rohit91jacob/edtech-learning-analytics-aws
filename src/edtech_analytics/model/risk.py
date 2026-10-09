"""Baseline withdrawal-risk model: logistic regression, evaluated on a held-out presentation.

Design choices, all deliberate and stated on the results site:

* **Temporal hold-out, not a random split.** Train on every presentation except
  ``holdout_presentation`` (default 2014J, the last one in the release) and report metrics only on
  it. A random split would leak presentation-level effects between train and test.
* **As-of features.** The feature table (dbt ``mart_dropout_risk_features``) only uses activity and
  submissions before the cut-off day, and excludes students who had already left.
* **No protected attributes as inputs.** Age band, IMD band, disability, gender and region are kept
  out of the feature set and used only to slice the evaluation.
* **Honest comparison.** The model is reported next to a clicks-only baseline and the base rate,
  with a bootstrap confidence interval on the test AUC.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import duckdb
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler

from edtech_analytics.config import Settings

log = logging.getLogger(__name__)

SEED = 20171128  # publication date of the OULAD data descriptor
COUNT_FEATURES = [
    "clicks_pre_start",
    "clicks_to_cutoff",
    "clicks_last_week",
    "forum_clicks_to_cutoff",
    "quiz_clicks_to_cutoff",
]
NUMERIC_FEATURES = [
    "num_of_prev_attempts",
    "studied_credits",
    "registration_lead_days",
    "active_days_to_cutoff",
    "active_weeks_to_cutoff",
    "activity_types_to_cutoff",
    "days_since_last_activity",
    "assessments_due_by_cutoff",
    "submitted_by_cutoff",
    "on_time_by_cutoff",
    "avg_score_by_cutoff",
    "missed_by_cutoff",
]
FLAG_FEATURES = ["no_activity_before_cutoff", "no_score_before_cutoff", "registration_day_missing"]
CATEGORICAL_FEATURES = ["code_module", "highest_education"]
SLICE_COLUMNS = ["age_band", "imd_band", "disability"]
LABEL = "label_withdrawn"


class ModelError(RuntimeError):
    """Training data is unusable (e.g. a split has a single class)."""


@dataclass
class ModelReport:
    metrics: dict
    slices: pd.DataFrame
    coefficients: pd.DataFrame
    per_module: pd.DataFrame


def load_features(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    # A stable row order keeps the seeded bootstrap (and the whole report) reproducible.
    return con.execute(
        "SELECT * FROM marts.mart_dropout_risk_features ORDER BY presentation_key, id_student"
    ).df()


def build_pipeline() -> Pipeline:
    pre = ColumnTransformer(
        [
            (
                "counts",
                Pipeline(
                    [
                        ("log1p", FunctionTransformer(np.log1p, feature_names_out="one-to-one")),
                        ("scale", StandardScaler()),
                    ]
                ),
                COUNT_FEATURES,
            ),
            ("numeric", StandardScaler(), NUMERIC_FEATURES),
            ("flags", "passthrough", FLAG_FEATURES),
            (
                "categorical",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                CATEGORICAL_FEATURES,
            ),
        ]
    )
    return Pipeline([("pre", pre), ("clf", LogisticRegression(C=1.0, max_iter=2000))])


def _prepare(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    for col in FLAG_FEATURES:
        frame[col] = frame[col].astype(int)
    for col in COUNT_FEATURES + NUMERIC_FEATURES:
        frame[col] = pd.to_numeric(frame[col]).astype(float)
    frame[LABEL] = frame[LABEL].astype(int)
    return frame


def _bootstrap_auc(y: np.ndarray, p: np.ndarray, reps: int = 500) -> tuple[float, float]:
    rng = np.random.default_rng(SEED)
    scores = []
    n = len(y)
    for _ in range(reps):
        idx = rng.integers(0, n, n)
        if y[idx].min() == y[idx].max():
            continue
        scores.append(roc_auc_score(y[idx], p[idx]))
    return float(np.percentile(scores, 2.5)), float(np.percentile(scores, 97.5))


def _best_f1_threshold(y: np.ndarray, p: np.ndarray) -> float:
    best, best_t = -1.0, 0.5
    for t in np.linspace(0.05, 0.95, 91):
        pred = p >= t
        tp = float(np.sum(pred & (y == 1)))
        fp = float(np.sum(pred & (y == 0)))
        fn = float(np.sum(~pred & (y == 1)))
        f1 = 2 * tp / (2 * tp + fp + fn) if tp else 0.0
        if f1 > best:
            best, best_t = f1, float(t)
    return best_t


def _rates(y: np.ndarray, pred: np.ndarray) -> dict[str, float | None]:
    tp = int(np.sum(pred & (y == 1)))
    fp = int(np.sum(pred & (y == 0)))
    fn = int(np.sum(~pred & (y == 1)))
    tn = int(np.sum(~pred & (y == 0)))
    return {
        "tpr": tp / (tp + fn) if tp + fn else None,
        "fpr": fp / (fp + tn) if fp + tn else None,
        "precision": tp / (tp + fp) if tp + fp else None,
        "flag_rate": (tp + fp) / len(y) if len(y) else None,
    }


def train_and_evaluate(frame: pd.DataFrame, holdout: str) -> ModelReport:
    frame = _prepare(frame)
    train = frame[frame["split"] == "train"]
    test = frame[frame["split"] == "test"]
    for name, part in (("train", train), ("test", test)):
        if part.empty or part[LABEL].nunique() < 2:
            raise ModelError(f"{name} split needs both withdrawn and retained enrolments")

    model = build_pipeline().fit(train, train[LABEL])
    p_train = model.predict_proba(train)[:, 1]
    p_test = model.predict_proba(test)[:, 1]
    y_train = train[LABEL].to_numpy()
    y_test = test[LABEL].to_numpy()

    clicks_only = Pipeline(
        [
            (
                "pre",
                ColumnTransformer([("c", FunctionTransformer(np.log1p), ["clicks_to_cutoff"])]),
            ),
            ("clf", LogisticRegression(max_iter=1000)),
        ]
    ).fit(train, train[LABEL])
    p_clicks = clicks_only.predict_proba(test)[:, 1]

    threshold = _best_f1_threshold(y_train, p_train)
    pred_test = p_test >= threshold
    lo, hi = _bootstrap_auc(y_test, p_test)
    metrics = {
        "model": "logistic_regression",
        "trained_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "holdout_presentation": holdout,
        "train_rows": len(train),
        "test_rows": len(test),
        "train_presentations": sorted(train["presentation_key"].unique().tolist()),
        "test_presentations": sorted(test["presentation_key"].unique().tolist()),
        "train_base_rate": float(y_train.mean()),
        "test_base_rate": float(y_test.mean()),
        "train_auc": float(roc_auc_score(y_train, p_train)),
        "test_auc": float(roc_auc_score(y_test, p_test)),
        "test_auc_ci95": [lo, hi],
        "test_average_precision": float(average_precision_score(y_test, p_test)),
        "test_brier": float(brier_score_loss(y_test, p_test)),
        "baseline_clicks_only_test_auc": float(roc_auc_score(y_test, p_clicks)),
        "baseline_base_rate_test_auc": 0.5,
        "threshold": threshold,
        "threshold_rule": "maximises F1 on the training split",
        **{f"test_{k}": v for k, v in _rates(y_test, pred_test).items()},
        "features": COUNT_FEATURES + NUMERIC_FEATURES + FLAG_FEATURES + CATEGORICAL_FEATURES,
        "excluded_from_features": ["gender", "region", *SLICE_COLUMNS],
        "seed": SEED,
    }

    names = model.named_steps["pre"].get_feature_names_out()
    coefs = model.named_steps["clf"].coef_[0]
    coefficients = (
        pd.DataFrame({"feature": names, "coefficient": coefs})
        .assign(abs_coefficient=lambda d: d["coefficient"].abs())
        .sort_values("abs_coefficient", ascending=False)
        .reset_index(drop=True)
    )

    test = test.assign(p=p_test, flagged=pred_test)
    slices = _slice_metrics(test)
    per_module = (
        test.groupby("code_module")
        .apply(_group_metrics, include_groups=False)
        .reset_index()
        .rename(columns={"code_module": "slice_value"})
    )
    return ModelReport(metrics, slices, coefficients, per_module)


def _group_metrics(group: pd.DataFrame) -> pd.Series:
    y = group[LABEL].to_numpy()
    p = group["p"].to_numpy()
    pred = group["flagged"].to_numpy()
    auc = float(roc_auc_score(y, p)) if len(set(y)) == 2 and len(y) >= 50 else None
    return pd.Series(
        {
            "n": len(group),
            "base_rate": float(y.mean()),
            "mean_predicted": float(p.mean()),
            "auc": auc,
            **_rates(y, pred),
        }
    )


def _slice_metrics(test: pd.DataFrame) -> pd.DataFrame:
    frames = []
    overall = _group_metrics(test).to_frame().T.assign(slice_dimension="overall", slice_value="all")
    frames.append(overall)
    for col in SLICE_COLUMNS:
        part = (
            test.groupby(col)
            .apply(_group_metrics, include_groups=False)
            .reset_index()
            .rename(columns={col: "slice_value"})
            .assign(slice_dimension=col)
        )
        frames.append(part)
    out = pd.concat(frames, ignore_index=True)
    out["calibration_gap"] = out["mean_predicted"] - out["base_rate"]
    cols = ["slice_dimension", "slice_value", "n", "base_rate", "mean_predicted"]
    cols += ["calibration_gap", "auc", "tpr", "fpr", "precision", "flag_rate"]
    return out[cols]


def persist(settings: Settings, report: ModelReport) -> None:
    con = duckdb.connect(str(settings.duckdb_path))
    try:
        con.execute("CREATE SCHEMA IF NOT EXISTS ml")
        metrics_rows = pd.DataFrame(
            [
                {"metric": k, "value": json.dumps(v) if not isinstance(v, str) else v}
                for k, v in report.metrics.items()
            ]
        )
        for name, frame in (
            ("risk_model_metrics", metrics_rows),
            ("risk_model_slices", report.slices),
            ("risk_model_coefficients", report.coefficients),
            ("risk_model_per_module", report.per_module),
        ):
            con.register("frame_view", frame)
            con.execute(f"CREATE OR REPLACE TABLE ml.{name} AS SELECT * FROM frame_view")
            con.unregister("frame_view")
    finally:
        con.close()
    settings.ops_dir.mkdir(parents=True, exist_ok=True)
    (settings.ops_dir / "risk_model.json").write_text(
        json.dumps(report.metrics, indent=2), encoding="utf-8"
    )


def train(settings: Settings) -> ModelReport:
    con = duckdb.connect(str(settings.duckdb_path), read_only=True)
    try:
        frame = load_features(con)
    finally:
        con.close()
    report = train_and_evaluate(frame, settings.holdout_presentation)
    persist(settings, report)
    log.info(
        "trained withdrawal-risk model",
        extra={
            "test_auc": round(report.metrics["test_auc"], 4),
            "baseline_clicks_only_test_auc": round(
                report.metrics["baseline_clicks_only_test_auc"], 4
            ),
        },
    )
    return report

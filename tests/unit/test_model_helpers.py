from __future__ import annotations

import numpy as np

from edtech_analytics.model import risk


def test_rates():
    y = np.array([1, 1, 0, 0])
    pred = np.array([True, False, True, False])
    rates = risk._rates(y, pred)
    assert rates == {"tpr": 0.5, "fpr": 0.5, "precision": 0.5, "flag_rate": 0.5}


def test_best_threshold_separates_perfect_scores():
    y = np.array([0, 0, 1, 1])
    p = np.array([0.1, 0.2, 0.8, 0.9])
    t = risk._best_f1_threshold(y, p)
    assert 0.2 < t <= 0.8


def test_bootstrap_is_seeded():
    rng = np.random.default_rng(0)
    y = rng.integers(0, 2, 200)
    p = rng.random(200)
    assert risk._bootstrap_auc(y, p, reps=50) == risk._bootstrap_auc(y, p, reps=50)


def test_protected_attributes_are_not_features():
    features = set(risk.COUNT_FEATURES + risk.NUMERIC_FEATURES + risk.FLAG_FEATURES)
    features |= set(risk.CATEGORICAL_FEATURES)
    assert not features & {"gender", "region", "age_band", "imd_band", "disability"}

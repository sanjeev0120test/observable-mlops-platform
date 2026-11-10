"""Registry-level checks for the eval framework: every UC is defined and gated."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from eval.metrics import THRESHOLDS, UC_METRICS  # noqa: E402
from eval.scorer import compute_score  # noqa: E402

EXPECTED_UCS = {f"UC{i}" for i in range(1, 24)}


def test_all_23_ucs_registered():
    assert set(UC_METRICS) == EXPECTED_UCS
    assert set(THRESHOLDS) == EXPECTED_UCS


def test_thresholds_in_range():
    for uc, threshold in THRESHOLDS.items():
        assert 0 <= threshold <= 100, f"{uc} threshold {threshold} out of range"


def test_uc1_drift_detected_passes():
    result = compute_score(
        "UC1",
        {
            "psi_score": 1.2,
            "ks_statistic": 0.45,
            "alibi_lsdd_p_value": 0.001,
            "retrain_triggered": True,
            "nannyml_performance_estimate": 0.1,
        },
    )
    assert result.passed, result.score
    assert {"uc", "score", "passed"} <= set(result.to_dict())


def test_uc1_no_drift_fails():
    result = compute_score(
        "UC1",
        {
            "psi_score": 0.01,
            "ks_statistic": 0.02,
            "alibi_lsdd_p_value": 0.9,
            "retrain_triggered": False,
            "nannyml_performance_estimate": 0.0,
        },
    )
    assert not result.passed, result.score

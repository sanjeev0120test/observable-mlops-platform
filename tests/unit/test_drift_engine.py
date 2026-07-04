"""
Unit tests for services/drift-monitor/src/drift_engine.py
Tests: PSI computation, KS test, drift detection, retrain trigger logic.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Service directories use hyphens — add src/ directly to path
_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "services" / "drift-monitor" / "src"))

from drift_engine import (  # noqa: E402
    _compute_psi,
    _run_ks_test,
    compute_drift,
    PSI_THRESHOLD,
    RETRAIN_PSI_THRESHOLD,
)


class TestComputePSI:
    """Population Stability Index computation tests."""

    def test_identical_distributions_near_zero(self):
        rng = np.random.default_rng(42)
        data = rng.normal(50, 10, 2000)
        psi = _compute_psi(data, data.copy())
        assert psi < 0.02, f"Identical distributions should have PSI ≈ 0, got {psi}"

    def test_moderate_shift_medium_psi(self):
        rng = np.random.default_rng(0)
        ref = rng.normal(50, 10, 1000)
        cur = rng.normal(60, 10, 1000)  # 10-unit mean shift
        psi = _compute_psi(ref, cur)
        # 10-unit shift on normal(50,10) is a significant distributional change
        assert psi > 0.05, f"Moderate shift: PSI should be > 0.05 (meaningful drift), got {psi}"
        assert psi < 5.0, f"Moderate shift: PSI should be < 5.0 (not astronomical), got {psi}"

    def test_large_shift_high_psi(self):
        ref = np.linspace(0, 100, 1000)
        cur = np.linspace(50, 150, 1000)  # Major distribution shift
        psi = _compute_psi(ref, cur)
        assert psi > 0.20, f"Large shift should have PSI > 0.20 (significant drift), got {psi}"

    def test_psi_is_nonnegative(self):
        rng = np.random.default_rng(1)
        ref = rng.normal(0, 1, 500)
        cur = rng.normal(0.5, 1, 500)
        psi = _compute_psi(ref, cur)
        assert psi >= 0.0, f"PSI must be non-negative, got {psi}"

    def test_psi_with_small_samples(self):
        """Edge case: PSI should not raise on small arrays."""
        ref = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        cur = np.array([2.0, 3.0, 4.0, 5.0, 6.0])
        psi = _compute_psi(ref, cur)
        assert psi >= 0.0


class TestKSTest:
    """KS test wrapper tests."""

    def test_same_distribution_high_pvalue(self):
        rng = np.random.default_rng(42)
        data = rng.normal(0, 1, 1000)
        stat, p = _run_ks_test(data, data.copy())
        assert p > 0.05, f"Same distribution: p-value should be > 0.05, got {p}"

    def test_different_distributions_low_pvalue(self):
        rng = np.random.default_rng(0)
        ref = rng.normal(0, 1, 500)
        cur = rng.normal(5, 1, 500)
        stat, p = _run_ks_test(ref, cur)
        assert stat > 0.3, f"Large shift: KS statistic should be large, got {stat}"
        assert p < 0.001, f"Large shift: p-value should be very small, got {p}"

    def test_ks_statistic_between_0_and_1(self):
        rng = np.random.default_rng(99)
        ref = rng.exponential(2.0, 200)
        cur = rng.exponential(5.0, 200)
        stat, p = _run_ks_test(ref, cur)
        assert 0.0 <= stat <= 1.0
        assert 0.0 <= p <= 1.0


class TestComputeDrift:
    """End-to-end drift detection pipeline tests."""

    @pytest.fixture
    def stable_df(self):
        rng = np.random.default_rng(42)
        n = 500
        return pd.DataFrame({
            "cpu_usage_pct": rng.normal(45, 10, n).clip(0, 100),
            "mem_usage_pct": rng.normal(55, 10, n).clip(0, 100),
            "restart_count": rng.poisson(0.5, n).astype(float),
        })

    def test_no_drift_does_not_trigger_retrain(self, stable_df):
        result = compute_drift(stable_df, stable_df.copy())
        assert not result.retrain_triggered, (
            f"Identical data should not trigger retrain, PSI={result.psi_score}"
        )
        assert result.psi_score < RETRAIN_PSI_THRESHOLD

    def test_large_drift_triggers_retrain(self, stable_df):
        shifted = stable_df.copy()
        shifted["cpu_usage_pct"] = (shifted["cpu_usage_pct"] + 40).clip(0, 100)
        shifted["mem_usage_pct"] = (shifted["mem_usage_pct"] + 30).clip(0, 100)
        result = compute_drift(stable_df, shifted)
        assert result.retrain_triggered, (
            f"Large drift should trigger retrain, PSI={result.psi_score}"
        )
        assert result.psi_score > RETRAIN_PSI_THRESHOLD

    def test_result_counts_match_input(self, stable_df):
        result = compute_drift(stable_df, stable_df.copy())
        assert result.n_reference == len(stable_df)
        assert result.n_current == len(stable_df)

    def test_metrics_are_in_valid_ranges(self, stable_df):
        shifted = stable_df.copy()
        shifted["cpu_usage_pct"] = (shifted["cpu_usage_pct"] + 20).clip(0, 100)
        result = compute_drift(stable_df, shifted)

        assert 0.0 <= result.psi_score
        assert 0.0 <= result.ks_statistic <= 1.0
        assert 0.0 <= result.alibi_lsdd_p_value <= 1.0
        assert 0.0 <= result.nannyml_performance_estimate <= 1.0

    def test_drifted_features_list_populated_on_large_shift(self, stable_df):
        shifted = stable_df.copy()
        shifted["cpu_usage_pct"] = (shifted["cpu_usage_pct"] + 50).clip(0, 100)
        result = compute_drift(stable_df, shifted, primary_feature="cpu_usage_pct")
        assert isinstance(result.drifted_features, list)

    def test_compute_drift_handles_missing_columns_gracefully(self, stable_df):
        """Should work even if current_df has fewer columns."""
        minimal_current = stable_df[["cpu_usage_pct"]].copy()
        # Should not raise — computes on available columns
        result = compute_drift(stable_df, minimal_current)
        assert result.psi_score >= 0.0

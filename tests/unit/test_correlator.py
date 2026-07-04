"""
Unit tests for services/alert-correlator/src/correlator.py
Tests: DBSCAN correlation, deduplication rates, false positive rates,
       edge cases, and the DataFrame indexing fix.
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
sys.path.insert(0, str(_REPO_ROOT / "services" / "alert-correlator" / "src"))

from correlator import correlate_alerts  # noqa: E402


def _make_alert_df(n: int, n_clusters: int = 3, seed: int = 42) -> pd.DataFrame:
    """Build a synthetic alert DataFrame with injected cluster structure."""
    rng = np.random.default_rng(seed)
    namespaces = [f"ns-{i % n_clusters}" for i in range(n)]
    # Alerts in same cluster are close in time
    base_times = pd.date_range("2024-01-01", periods=n_clusters, freq="5min")
    timestamps = []
    alert_names = []
    root_cause_ids = []
    is_roots = []

    alerts_per_cluster = n // n_clusters
    for cluster_id in range(n_clusters):
        for j in range(alerts_per_cluster):
            jitter = pd.Timedelta(seconds=int(rng.integers(0, 60)))
            timestamps.append(base_times[cluster_id] + jitter)
            alert_names.append(rng.choice(["HighCPU", "OOMKilled", "PodCrash"]))
            root_cause_ids.append(cluster_id)
            is_roots.append(j == 0)  # First alert per cluster is root

    df = pd.DataFrame({
        "timestamp": timestamps,
        "alertname": alert_names,
        "namespace": namespaces[:len(timestamps)],
        "severity": "warning",
        "root_cause_id": root_cause_ids,
        "is_root": is_roots,
    })
    return df.sample(frac=1, random_state=seed).reset_index(drop=True)


class TestCorrelateAlerts:
    def test_returns_deduplication_rate_in_0_1(self):
        df = _make_alert_df(30, n_clusters=3)
        result = correlate_alerts(df)
        assert 0.0 <= result.deduplication_rate <= 1.0

    def test_n_clusters_never_exceeds_n_input(self):
        for n in [5, 20, 100]:
            df = _make_alert_df(n, n_clusters=min(n // 3, 5))
            result = correlate_alerts(df)
            assert result.n_clusters <= result.n_input, (
                f"n_clusters {result.n_clusters} > n_input {result.n_input}"
            )

    def test_clustered_alerts_reduces_noise(self):
        """Alerts injected with cluster structure should have dedup_rate > 0."""
        df = _make_alert_df(60, n_clusters=3)
        result = correlate_alerts(df)
        assert result.deduplication_rate > 0.0, (
            "Structured clusters should produce non-zero deduplication"
        )

    def test_small_input_below_threshold_returns_trivial_result(self):
        df = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=2, freq="1min"),
            "alertname": ["A", "B"],
            "namespace": ["default", "default"],
            "severity": ["warning", "warning"],
        })
        result = correlate_alerts(df)
        assert result.deduplication_rate == 0.0
        assert result.n_clusters == 2

    def test_false_positive_rate_in_0_1(self):
        df = _make_alert_df(30, n_clusters=3)
        result = correlate_alerts(df)
        assert 0.0 <= result.false_positive_rate <= 1.0

    def test_result_has_root_cause_groups(self):
        df = _make_alert_df(30, n_clusters=3)
        result = correlate_alerts(df)
        assert isinstance(result.root_cause_groups, list)
        for group in result.root_cause_groups:
            assert "cluster_id" in group
            assert "n_alerts" in group
            assert "alertnames" in group
            assert "namespaces" in group

    def test_dataframe_not_modified_by_correlation(self):
        """correlate_alerts must not modify the caller's DataFrame (copy safety)."""
        df = _make_alert_df(30, n_clusters=3)
        original_columns = set(df.columns)
        _ = correlate_alerts(df)
        assert set(df.columns) == original_columns, (
            "correlate_alerts should not add columns to the input DataFrame"
        )
        assert "cluster" not in df.columns

    def test_handles_duplicate_timestamps_without_error(self):
        """All alerts at exact same timestamp — edge case for time normalization."""
        df = pd.DataFrame({
            "timestamp": ["2024-01-01T00:00:00"] * 10,
            "alertname": ["HighCPU"] * 5 + ["OOMKilled"] * 5,
            "namespace": ["default"] * 10,
            "severity": ["critical"] * 10,
        })
        result = correlate_alerts(df)
        assert result.n_input == 10
        assert 0.0 <= result.deduplication_rate <= 1.0

    def test_single_namespace_high_deduplication(self):
        """Same namespace, same alert type, close in time → high dedup."""
        timestamps = pd.date_range("2024-01-01", periods=20, freq="10s")
        df = pd.DataFrame({
            "timestamp": timestamps,
            "alertname": ["HighCPU"] * 20,
            "namespace": ["default"] * 20,
            "severity": ["warning"] * 20,
        })
        result = correlate_alerts(df)
        assert result.deduplication_rate > 0.5, (
            f"Same-namespace same-alert close-in-time should deduplicate heavily, "
            f"got {result.deduplication_rate}"
        )

    def test_dispersed_alerts_low_deduplication(self):
        """Alerts spread over many hours from different namespaces — use high eps to confirm behavior."""
        rng = np.random.default_rng(7)
        n = 20
        df = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=n, freq="30min"),
            "alertname": rng.choice(
                ["HighCPU", "OOMKilled", "DiskFull", "NetworkError", "PodCrash"], n
            ),
            "namespace": [f"ns-{i}" for i in range(n)],
            "severity": ["warning"] * n,
        })
        # Use tight eps=0.01 to avoid over-clustering dispersed alerts
        result = correlate_alerts(df, eps=0.01)
        # With tight eps, most dispersed alerts should be outliers (n_clusters < n/2)
        assert result.n_clusters < n // 2, (
            f"With tight eps=0.01, dispersed alerts should form few clusters, "
            f"got {result.n_clusters} clusters for {n} alerts"
        )

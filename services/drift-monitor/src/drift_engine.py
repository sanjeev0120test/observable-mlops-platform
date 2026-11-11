"""
UC1 — Drift detection engine.
Runs KS test, PSI, a CBPE-style performance estimate, and a kernel MMD two-sample
test on pod metrics. Generates an Evidently HTML drift report and returns DriftMetrics.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)


@dataclass
class DriftMetrics:
    ks_statistic: float
    psi_score: float
    nannyml_performance_estimate: float
    # Kept under its original name: the UC1 eval gate and MLflow history key on it.
    alibi_lsdd_p_value: float
    retrain_triggered: bool
    report_path: str | None
    n_reference: int
    n_current: int
    drifted_features: list[str]


PSI_THRESHOLD = 0.20
KS_THRESHOLD = 0.30
RETRAIN_PSI_THRESHOLD = 0.10  # Lower threshold triggers retraining


def _compute_psi(reference: np.ndarray, current: np.ndarray, n_bins: int = 10) -> float:
    """Population Stability Index: 0=identical, 0.1=slight shift, 0.2=significant."""
    eps = 1e-8
    r_hist, bin_edges = np.histogram(reference, bins=n_bins)
    c_hist, _ = np.histogram(current, bins=bin_edges)

    r_pct = (r_hist + eps) / (len(reference) + n_bins * eps)
    c_pct = (c_hist + eps) / (len(current) + n_bins * eps)

    return float(np.sum((c_pct - r_pct) * np.log(c_pct / r_pct)))


def _run_ks_test(reference: np.ndarray, current: np.ndarray) -> tuple[float, float]:
    """Two-sample KS test. Returns (statistic, p_value)."""
    stat, p_val = stats.ks_2samp(reference, current)
    return float(stat), float(p_val)


def _estimate_performance_nannyml(
    reference: pd.DataFrame, current: pd.DataFrame, feature_cols: list[str]
) -> float:
    """
    Simplified CBPE (Confidence-Based Performance Estimation) stub.
    NannyML proper requires model probability predictions. This approximation
    estimates performance degradation via feature distribution shift magnitude.
    Phase 1 wires in full nannyml.CBPE when model artifacts are available.
    """
    total_psi = 0.0
    for col in feature_cols:
        if col in reference.columns and col in current.columns:
            psi = _compute_psi(reference[col].values, current[col].values)
            total_psi += psi
    avg_psi = total_psi / max(len(feature_cols), 1)
    estimated_accuracy = max(0.0, 1.0 - avg_psi * 2)
    return float(estimated_accuracy)


def _run_mmd_test(
    reference: np.ndarray,
    current: np.ndarray,
    n_permutations: int = 100,
    max_samples: int = 400,
    seed: int = 0,
) -> float:
    """
    Kernel two-sample test: Gaussian-kernel MMD^2 with a permutation p-value.
    Returns p-value: >0.05 = no drift, <0.05 = drift detected.

    Replaces Alibi Detect LSDD (now BSL-licensed and pinned to numpy<2); same
    hypothesis test family, numpy only, deterministic for a fixed seed.
    """
    rng = np.random.default_rng(seed)
    ref = np.asarray(reference, dtype=float).ravel()
    cur = np.asarray(current, dtype=float).ravel()
    if len(ref) < 2 or len(cur) < 2:
        return 1.0
    if len(ref) > max_samples:
        ref = rng.choice(ref, max_samples, replace=False)
    if len(cur) > max_samples:
        cur = rng.choice(cur, max_samples, replace=False)

    pooled = np.concatenate([ref, cur])
    dists = (pooled[:, None] - pooled[None, :]) ** 2
    median = np.median(dists[dists > 0]) if np.any(dists > 0) else 1.0
    kernel = np.exp(-dists / median)
    n = len(ref)

    def mmd2(idx: np.ndarray) -> float:
        x, y = idx[:n], idx[n:]
        return float(
            kernel[np.ix_(x, x)].mean()
            + kernel[np.ix_(y, y)].mean()
            - 2 * kernel[np.ix_(x, y)].mean()
        )

    order = np.arange(len(pooled))
    observed = mmd2(order)
    exceed = sum(mmd2(rng.permutation(order)) >= observed for _ in range(n_permutations))
    return float((exceed + 1) / (n_permutations + 1))


def _generate_evidently_report(
    reference_df: pd.DataFrame,
    current_df: pd.DataFrame,
    feature_cols: list[str],
    output_path: Path,
) -> None:
    """Generate Evidently (0.7+) HTML drift report."""
    try:
        from evidently import Report
        from evidently.presets import DataDriftPreset

        report = Report([DataDriftPreset()])
        snapshot = report.run(
            current_data=current_df[feature_cols], reference_data=reference_df[feature_cols]
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot.save_html(str(output_path))
        logger.info("Evidently report saved to %s", output_path)
    except Exception as e:
        logger.warning("Evidently report generation failed: %s", e)


def compute_drift(
    reference_df: pd.DataFrame,
    current_df: pd.DataFrame,
    primary_feature: str = "cpu_usage_pct",
    report_output_dir: Path = Path("services/drift-monitor/reports"),
    model_name: str = "pod-failure-prediction",
) -> DriftMetrics:
    """
    Run full drift detection pipeline on reference vs current data.

    Returns DriftMetrics with all UC1 eval metrics populated.
    """
    feature_cols = [
        c
        for c in ["cpu_usage_pct", "mem_usage_pct", "restart_count"]
        if c in reference_df.columns and c in current_df.columns
    ]

    ref_primary = reference_df[primary_feature].dropna().values
    cur_primary = current_df[primary_feature].dropna().values

    ks_stat, _ = _run_ks_test(ref_primary, cur_primary)
    psi = _compute_psi(ref_primary, cur_primary)
    perf_est = _estimate_performance_nannyml(reference_df, current_df, feature_cols)
    mmd_p = _run_mmd_test(ref_primary, cur_primary)

    drifted = []
    for col in feature_cols:
        col_ks, _ = _run_ks_test(reference_df[col].dropna().values, current_df[col].dropna().values)
        if col_ks > KS_THRESHOLD:
            drifted.append(col)

    report_path = None
    try:
        report_file = report_output_dir / f"drift_report_{model_name}.html"
        _generate_evidently_report(reference_df, current_df, feature_cols, report_file)
        report_path = str(report_file)
    except Exception as e:
        logger.warning("Report generation skipped: %s", e)

    retrain_triggered = psi > RETRAIN_PSI_THRESHOLD

    return DriftMetrics(
        ks_statistic=round(ks_stat, 4),
        psi_score=round(psi, 4),
        nannyml_performance_estimate=round(perf_est, 4),
        alibi_lsdd_p_value=round(mmd_p, 4),
        retrain_triggered=retrain_triggered,
        report_path=report_path,
        n_reference=len(reference_df),
        n_current=len(current_df),
        drifted_features=drifted,
    )

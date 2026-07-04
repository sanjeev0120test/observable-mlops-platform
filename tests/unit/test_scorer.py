"""
Unit tests for eval/scorer.py and eval/metrics.py.
Verifies: scoring logic, metric directions, threshold consistency, serialisation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from eval.metrics import THRESHOLDS, UC_METRICS, EvalResult, MetricSpec
from eval.scorer import _score_metric, compute_score


class TestScoreMetric:
    """Unit tests for the single-metric scoring function."""

    def test_higher_better_at_threshold_scores_100(self):
        spec = MetricSpec("x", "higher_better", 0.70, 1.0)
        assert _score_metric(spec, 0.70) == pytest.approx(100.0, abs=0.1)

    def test_higher_better_above_threshold_capped_100(self):
        spec = MetricSpec("x", "higher_better", 0.70, 1.0)
        assert _score_metric(spec, 1.50) == 100.0

    def test_higher_better_below_threshold_scales_linearly(self):
        spec = MetricSpec("x", "higher_better", 1.0, 1.0)
        score = _score_metric(spec, 0.5)
        assert 40.0 < score < 60.0

    def test_lower_better_at_threshold_scores_100(self):
        spec = MetricSpec("x", "lower_better", 0.05, 1.0)
        assert _score_metric(spec, 0.05) == pytest.approx(100.0, abs=0.1)

    def test_lower_better_above_threshold_penalised(self):
        spec = MetricSpec("x", "lower_better", 0.05, 1.0)
        assert _score_metric(spec, 0.50) < 50.0

    def test_bool_true_truthy_scores_100(self):
        spec = MetricSpec("x", "bool_true", True, 1.0)
        assert _score_metric(spec, True) == 100.0
        assert _score_metric(spec, 1) == 100.0
        assert _score_metric(spec, "yes") == 100.0

    def test_bool_true_falsy_scores_0(self):
        spec = MetricSpec("x", "bool_true", True, 1.0)
        assert _score_metric(spec, False) == 0.0
        assert _score_metric(spec, 0) == 0.0
        assert _score_metric(spec, "") == 0.0

    def test_exact_match_scores_100(self):
        spec = MetricSpec("x", "exact", 27, 1.0)
        assert _score_metric(spec, 27) == 100.0

    def test_exact_mismatch_scores_0(self):
        spec = MetricSpec("x", "exact", 27, 1.0)
        assert _score_metric(spec, 26) == 0.0


class TestUCMetricsDefinitions:
    """Validates the UC_METRICS registry is complete and internally consistent."""

    def test_all_23_ucs_defined(self):
        expected = {f"UC{i}" for i in range(1, 24)}
        assert expected == set(UC_METRICS.keys()), (
            f"Missing UCs: {expected - set(UC_METRICS.keys())}"
        )

    def test_all_23_thresholds_defined(self):
        expected = {f"UC{i}" for i in range(1, 24)}
        assert expected == set(THRESHOLDS.keys())

    def test_all_thresholds_in_valid_range(self):
        for uc, threshold in THRESHOLDS.items():
            assert 0 <= threshold <= 100, f"{uc} threshold {threshold} out of range [0, 100]"

    def test_all_metric_directions_valid(self):
        valid_directions = {"higher_better", "lower_better", "bool_true", "exact"}
        for uc, specs in UC_METRICS.items():
            for spec in specs:
                assert spec.direction in valid_directions, (
                    f"{uc}.{spec.name} has invalid direction: {spec.direction}"
                )

    def test_all_metric_weights_positive(self):
        for uc, specs in UC_METRICS.items():
            for spec in specs:
                assert spec.weight > 0, f"{uc}.{spec.name} has non-positive weight"

    def test_each_uc_has_at_least_one_metric(self):
        for uc, specs in UC_METRICS.items():
            assert len(specs) >= 1, f"{uc} has no metric specs"


class TestComputeScore:
    """Tests for the composite score computation."""

    def test_uc1_drift_detected_should_pass(self):
        result = compute_score("UC1", {
            "psi_score": 1.2,
            "ks_statistic": 0.45,
            "alibi_lsdd_p_value": 0.001,
            "retrain_triggered": True,
            "nannyml_performance_estimate": 0.1,
        })
        assert result.passed, f"UC1 drift-detected should PASS, got score={result.score}"

    def test_uc1_no_drift_should_fail(self):
        result = compute_score("UC1", {
            "psi_score": 0.01,
            "ks_statistic": 0.01,
            "alibi_lsdd_p_value": 0.95,
            "retrain_triggered": False,
            "nannyml_performance_estimate": 0.0,
        })
        assert not result.passed, f"UC1 no-drift should FAIL, got score={result.score}"

    def test_missing_metric_scores_zero_for_that_metric(self):
        result = compute_score("UC1", {})
        assert result.score == 0.0
        for metric_info in result.details.values():
            assert metric_info["status"] == "MISSING"

    def test_unknown_uc_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown use case"):
            compute_score("UC99", {})

    def test_score_bounded_0_to_100(self):
        for uc in UC_METRICS:
            # Perfect metrics
            perfect = {}
            for spec in UC_METRICS[uc]:
                if spec.direction == "bool_true":
                    perfect[spec.name] = True
                elif spec.direction == "higher_better":
                    perfect[spec.name] = float(spec.pass_threshold) * 2
                elif spec.direction == "lower_better":
                    perfect[spec.name] = 0.0
                elif spec.direction == "exact":
                    perfect[spec.name] = spec.pass_threshold
            result = compute_score(uc, perfect)
            assert 0.0 <= result.score <= 100.0, f"{uc}: score {result.score} out of [0, 100]"

    def test_uc6_opa_gate_must_be_exact_1(self):
        """UC6: opa_gate_pass_rate is 'exact' direction — must equal 1.0 to score 100."""
        result_pass = compute_score("UC6", {
            "remediation_success_rate": 0.95,
            "opa_gate_pass_rate": 1.0,
            "false_remediation_rate": 0.02,
            "mttr_seconds": 200.0,
        })
        result_fail = compute_score("UC6", {
            "remediation_success_rate": 0.95,
            "opa_gate_pass_rate": 0.9,  # Not exactly 1.0
            "false_remediation_rate": 0.02,
            "mttr_seconds": 200.0,
        })
        assert result_pass.details["opa_gate_pass_rate"]["score"] == 100.0
        assert result_fail.details["opa_gate_pass_rate"]["score"] == 0.0

    def test_eval_result_serialization(self):
        result = compute_score("UC3", {
            "deduplication_rate": 0.80,
            "silhouette_score": 0.45,
            "false_positive_rate": 0.05,
        })
        d = result.to_dict()
        assert "uc" in d
        assert "score" in d
        assert "passed" in d
        assert "details" in d
        # Verify round-trip via JSON
        json_str = json.dumps(d, default=str)
        loaded = json.loads(json_str)
        assert loaded["uc"] == "UC3"

    def test_eval_result_save_creates_file(self, tmp_path):
        result = compute_score("UC1", {
            "psi_score": 0.5,
            "ks_statistic": 0.3,
            "alibi_lsdd_p_value": 0.02,
            "retrain_triggered": True,
            "nannyml_performance_estimate": 0.7,
        })
        path = result.save(tmp_path)
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["uc"] == "UC1"
        assert "score" in data

"""EU AI Act checker output is what the trust score's governance cap reads."""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).parent.parent.parent
_CHECKER = _REPO / "governance" / "eu-ai-act" / "compliance_check.py"
_TRUST_SRC = _REPO / "services" / "model-trust" / "src"
sys.path.insert(0, str(_TRUST_SRC))

from assemble import assemble_signals  # noqa: E402
from trust_engine import compute_trust_score  # noqa: E402


def _load_checker():
    spec = importlib.util.spec_from_file_location("eu_ai_act_compliance_check", _CHECKER)
    module = importlib.util.module_from_spec(spec)
    sys.modules["eu_ai_act_compliance_check"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checker():
    return _load_checker()


_HEALTHY = {
    "accuracy": 0.95,
    "f1_score": 0.94,
    "roc_auc": 0.97,
    "psi_score": 0.02,
    "ks_statistic": 0.02,
    "estimated_performance_drop": 0.0,
    "error_budget_remaining": 0.9,
    "p99_latency_ms": 80,
    "cost_per_1k_predictions_usd": 0.01,
    "critical_cves": 0,
    "high_cves": 0,
    "policy_violations": 0,
    "image_signed": True,
}


def _score(compliance: dict, extra: dict | None = None):
    evidence = {
        "metrics": _HEALTHY,
        "signals": {
            k: v
            for k, v in _HEALTHY.items()
            if k
            in {
                "critical_cves",
                "high_cves",
                "policy_violations",
                "image_signed",
                "error_budget_remaining",
                "p99_latency_ms",
                "cost_per_1k_predictions_usd",
                "estimated_performance_drop",
                "ks_statistic",
                "roc_auc",
            }
        },
        "compliance": compliance,
    }
    # metrics already carry accuracy/f1/psi; security numbers are in metrics too
    # and the assembler reads them from metrics. Keep compliance authoritative.
    if extra:
        evidence["signals"].update(extra)
    return compute_trust_score("pod-failure-prediction", "1", assemble_signals(evidence))


class TestComplianceFeedsTrust:
    def test_checker_exports_trust_evidence(self, checker):
        assert callable(checker.check_eu_ai_act_compliance)
        assert callable(checker.to_trust_evidence)

    def test_incomplete_model_is_noncompliant_and_capped(self, checker):
        report = checker.check_eu_ai_act_compliance(
            "pod-failure-prediction",
            "1",
            run_tags={},
            run_metrics={},
            model_card_path=None,
        )
        assert report.is_compliant is False
        evidence = checker.to_trust_evidence(report)
        assert evidence["is_compliant"] is False
        scored = _score(evidence)
        assert any(c["rule"] == "eu_ai_act_non_compliant" for c in scored.caps_applied)
        assert scored.score <= 849
        assert scored.band != "PRIME"

    def test_complete_model_clears_the_cap_and_can_be_prime(self, checker, tmp_path):
        card = tmp_path / "model_card.md"
        card.write_text("# card\n\n## Risk\nFalse negatives miss failing pods.\n", encoding="utf-8")
        report = checker.check_eu_ai_act_compliance(
            "pod-failure-prediction",
            "2",
            run_tags={
                "eu_ai_act_risk_level": "high",
                "training_dataset": "feast/pod_metrics_features",
                "shap_values_logged": "true",
                "human_review_approved": "true",
                "bias_check_completed": "true",
            },
            run_metrics={"accuracy": 0.91, "f1_score": 0.88, "drift_psi": 0.04},
            model_card_path=card,
        )
        assert report.is_compliant is True
        scored = _score(checker.to_trust_evidence(report))
        assert scored.caps_applied == [] or not any(
            c["rule"] == "eu_ai_act_non_compliant" for c in scored.caps_applied
        )
        assert scored.band == "PRIME"
        assert scored.score == 1000

    def test_shipped_model_card_documents_the_shap_gap(self):
        card = (_REPO / "mlops" / "models" / "pod-failure-prediction" / "model_card.md").read_text(
            encoding="utf-8"
        )
        assert "Risk" in card
        assert "SHAP" in card

    def test_retrain_dag_parses(self):
        source = (
            _REPO / "mlops" / "pipelines" / "airflow" / "dags" / "pod_failure_prediction_retrain.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        names = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        assert "_eu_ai_act_evidence" in names
        assert "compute_trust_score" in names

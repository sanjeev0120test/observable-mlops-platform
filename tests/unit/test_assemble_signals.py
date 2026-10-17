"""Evidence -> trust-signal assembly. Missing sources must stay missing."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).parent.parent.parent / "services" / "model-trust" / "src"
sys.path.insert(0, str(_SRC))

from assemble import EvidenceError, assemble_signals  # noqa: E402
from trust_engine import compute_trust_score  # noqa: E402

TRIVY = {
    "Results": [
        {
            "Vulnerabilities": [
                {"Severity": "CRITICAL", "VulnerabilityID": "CVE-1"},
                {"Severity": "HIGH", "VulnerabilityID": "CVE-2"},
                {"Severity": "HIGH", "VulnerabilityID": "CVE-3"},
                {"Severity": "LOW", "VulnerabilityID": "CVE-4"},
            ]
        }
    ]
}


class TestAssemble:
    def test_empty_evidence_emits_nothing(self):
        assert assemble_signals(None) == {}
        assert assemble_signals({}) == {}

    def test_rejects_non_object(self):
        with pytest.raises(EvidenceError):
            assemble_signals(["not", "a", "dict"])  # type: ignore[arg-type]

    def test_metric_aliases_and_tag_numbers(self):
        signals = assemble_signals(
            {
                "metrics": {"val_accuracy": "0.91", "drift_psi": 0.04, "f1": 0.88},
                "tags": {"ks_statistic": "0.03"},
            }
        )
        assert signals["accuracy"] == 0.91
        assert signals["psi_score"] == 0.04
        assert signals["f1_score"] == 0.88
        assert signals["ks_statistic"] == 0.03
        assert "critical_cves" not in signals
        assert "image_signed" not in signals

    def test_unobserved_security_is_not_invented_as_clean(self):
        signals = assemble_signals({"metrics": {"accuracy": 0.9}})
        for key in ("critical_cves", "high_cves", "policy_violations", "image_signed"):
            assert key not in signals

    def test_trivy_counts_and_explicit_override(self):
        counted = assemble_signals({"security": {"trivy": TRIVY}})
        assert counted["critical_cves"] == 1
        assert counted["high_cves"] == 2

        clean = assemble_signals({"security": {"trivy": {"Results": []}}})
        assert clean["critical_cves"] == 0 and clean["high_cves"] == 0

        overridden = assemble_signals(
            {"security": {"trivy": TRIVY, "critical_cves": 0, "high_cves": 0}}
        )
        assert overridden["critical_cves"] == 0 and overridden["high_cves"] == 0

    def test_kyverno_failures_and_cosign(self):
        signals = assemble_signals(
            {
                "security": {
                    "kyverno": {
                        "results": [
                            {"result": "pass"},
                            {"result": "fail"},
                            {"status": "fail"},
                        ]
                    },
                    "cosign": {"verified": False},
                }
            }
        )
        assert signals["policy_violations"] == 2
        assert signals["image_signed"] is False

    def test_bad_number_is_rejected(self):
        with pytest.raises(EvidenceError):
            assemble_signals({"security": {"critical_cves": "many"}})

    def test_tags_set_governance_only_when_explicit(self):
        observed = assemble_signals(
            {
                "tags": {
                    "shap_values_logged": "true",
                    "training_dataset": "feast/pod_metrics",
                    "human_review_approved": "false",
                    "model_card_present": "yes",
                }
            }
        )
        assert observed["shap_logged"] is True
        assert observed["lineage_recorded"] is True
        assert observed["human_oversight_defined"] is False
        assert observed["model_card_present"] is True
        assert "eu_ai_act_compliant" not in observed

    def test_shap_metric_counts_as_logged(self):
        signals = assemble_signals({"metrics": {"shap_mean_abs_impact": 0.2}})
        assert signals["shap_logged"] is True

    def test_compliance_report_maps_checks_and_overrides_tags(self):
        signals = assemble_signals(
            {
                "tags": {"eu_ai_act_compliant": "true", "shap_values_logged": "true"},
                "compliance": {
                    "is_compliant": False,
                    "checks": [
                        {"name": "explainability_logged", "passed": False},
                        {"name": "model_card_exists", "passed": False},
                        {"name": "training_data_documented", "passed": True},
                        {"name": "human_oversight_gate", "passed": True},
                        {"name": "not_a_trust_signal", "passed": False},
                    ],
                },
            }
        )
        assert signals["eu_ai_act_compliant"] is False
        assert signals["shap_logged"] is False
        assert signals["model_card_present"] is False
        assert signals["lineage_recorded"] is True
        assert signals["human_oversight_defined"] is True

    def test_explicit_signals_win(self):
        signals = assemble_signals({"metrics": {"accuracy": 0.4}, "signals": {"accuracy": 0.99}})
        assert signals["accuracy"] == 0.99

    def test_noncompliant_evidence_applies_the_prime_cap(self):
        signals = assemble_signals(
            {
                "metrics": {
                    "accuracy": 0.95,
                    "f1_score": 0.94,
                    "roc_auc": 0.97,
                    "psi_score": 0.02,
                    "ks_statistic": 0.02,
                    "estimated_performance_drop": 0.0,
                    "error_budget_remaining": 0.9,
                    "p99_latency_ms": 80,
                    "cost_per_1k_predictions_usd": 0.01,
                },
                "security": {
                    "critical_cves": 0,
                    "high_cves": 0,
                    "policy_violations": 0,
                    "image_signed": True,
                },
                "compliance": {"is_compliant": False, "checks": []},
                "model_card_present": True,
            }
        )
        report = compute_trust_score("m", "1", signals)
        assert any(c["rule"] == "eu_ai_act_non_compliant" for c in report.caps_applied)
        assert report.score <= 849
        assert report.band != "PRIME"

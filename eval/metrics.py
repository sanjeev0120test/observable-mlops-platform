"""
Unified eval metrics definitions for all 23 use cases.
Every UC workflow calls compute_score() and writes the result to eval-results/<uc>.json.
GitHub Actions fails the job if result.passed == False.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Eval thresholds — CI fails if score < threshold
# ---------------------------------------------------------------------------
THRESHOLDS: dict[str, int] = {
    "UC1": 70,
    "UC2": 65,
    "UC3": 50,
    "UC4": 70,
    "UC5": 75,
    "UC6": 85,
    "UC7": 60,
    "UC8": 60,
    "UC9": 75,
    "UC10": 65,
    "UC11": 65,
    "UC12": 70,
    "UC13": 80,
    "UC14": 65,
    "UC15": 60,
    "UC16": 65,
    "UC17": 65,
    "UC18": 65,
    "UC19": 65,
    "UC20": 90,
    "UC21": 60,
    "UC22": 70,
    "UC23": 60,
}


@dataclass
class MetricSpec:
    """Definition of a single metric: direction, pass condition, weight in composite score."""

    name: str
    direction: str  # "higher_better" | "lower_better" | "exact" | "bool_true"
    pass_threshold: Any  # Value at which this metric contributes full weight
    weight: float = 1.0
    description: str = ""


# ---------------------------------------------------------------------------
# Metric specifications per UC
# ---------------------------------------------------------------------------
UC_METRICS: dict[str, list[MetricSpec]] = {
    "UC1": [
        MetricSpec(
            "psi_score", "higher_better", 0.25, 2.0, "PSI > 0.25 = significant drift detected"
        ),
        MetricSpec(
            "ks_statistic", "higher_better", 0.20, 1.5, "KS stat > 0.20 = feature drift detected"
        ),
        MetricSpec(
            "alibi_lsdd_p_value", "lower_better", 0.05, 1.0, "LSDD p-value < 0.05 = drift confirmed"
        ),
        MetricSpec(
            "retrain_triggered",
            "bool_true",
            True,
            3.0,
            "Retrain DAG fired when drift breaches threshold",
        ),
        MetricSpec(
            "nannyml_performance_estimate",
            "higher_better",
            0.0,
            0.5,
            "NannyML returned an estimate (>0 = healthy)",
        ),
    ],
    "UC2": [
        MetricSpec(
            "reconstruction_loss_threshold",
            "lower_better",
            0.05,
            1.0,
            "95th-pct reconstruction loss on normal data",
        ),
        MetricSpec(
            "anomaly_precision_at_10",
            "higher_better",
            0.70,
            2.0,
            "Precision@10 on injected anomalies",
        ),
        MetricSpec("anomaly_recall_at_10", "higher_better", 0.60, 2.0, "Recall@10"),
        MetricSpec(
            "qdrant_similar_incidents_found",
            "higher_better",
            1,
            1.0,
            "Qdrant returned >= 1 similar past incident",
        ),
    ],
    "UC3": [
        MetricSpec(
            "deduplication_rate", "higher_better", 0.70, 2.0, "Fraction of duplicate alerts removed"
        ),
        MetricSpec("silhouette_score", "higher_better", 0.30, 1.5, "DBSCAN cluster quality"),
        MetricSpec(
            "false_positive_rate", "lower_better", 0.10, 2.0, "Real alerts incorrectly suppressed"
        ),
    ],
    "UC4": [
        MetricSpec("forecast_mae", "lower_better", 0.15, 1.5, "Forecast MAE as pct of mean load"),
        MetricSpec(
            "pre_scale_lead_time_seconds",
            "higher_better",
            300,
            2.0,
            "Seconds BEFORE load peak that scaling fires",
        ),
        MetricSpec(
            "p99_latency_delta_pct",
            "lower_better",
            -0.10,
            1.5,
            "p99 latency improvement (negative = better)",
        ),
    ],
    "UC5": [
        MetricSpec(
            "offline_online_psi",
            "lower_better",
            0.10,
            2.0,
            "PSI between offline and online feature values",
        ),
        MetricSpec(
            "ge_validation_success_pct", "higher_better", 0.99, 2.0, "Great Expectations pass rate"
        ),
        MetricSpec(
            "feature_freshness_seconds",
            "lower_better",
            3600,
            1.0,
            "Age of most recent online store row",
        ),
    ],
    "UC6": [
        MetricSpec(
            "remediation_success_rate",
            "higher_better",
            0.90,
            2.0,
            "Fraction of incidents auto-remediated",
        ),
        MetricSpec(
            "opa_gate_pass_rate", "exact", 1.0, 3.0, "All actions must go through OPA (=1.0)"
        ),
        MetricSpec(
            "false_remediation_rate", "lower_better", 0.05, 2.0, "Actions taken on non-incidents"
        ),
        MetricSpec("mttr_seconds", "lower_better", 300, 1.5, "Mean time to remediate"),
    ],
    "UC7": [
        MetricSpec(
            "trivy_critical_cves",
            "lower_better",
            25,
            3.0,
            "Critical fixable CVEs (python:3.11-slim baseline ~20)",
        ),
        MetricSpec(
            "kyverno_violations_blocked",
            "higher_better",
            1,
            2.0,
            "At least one policy violation blocked in test",
        ),
        MetricSpec(
            "falco_rules_triggered",
            "higher_better",
            1,
            2.0,
            "At least one Falco rule fired in test",
        ),
    ],
    "UC8": [
        MetricSpec(
            "retrieval_precision_at_5",
            "higher_better",
            0.70,
            2.0,
            "Fraction of top-5 chunks that are relevant",
        ),
        MetricSpec(
            "answer_groundedness_score",
            "higher_better",
            0.60,
            1.5,
            "Answer uses context (citation present)",
        ),
        MetricSpec(
            "qdrant_collection_size",
            "higher_better",
            40,
            1.0,
            "Minimum chunk count in runbook_chunks",
        ),
    ],
    "UC9": [
        MetricSpec(
            "accuracy_delta_vs_baseline",
            "higher_better",
            0.02,
            2.0,
            "New model beats baseline by >= 2%",
        ),
        MetricSpec(
            "drift_score_on_holdout",
            "lower_better",
            0.10,
            1.5,
            "No drift on held-out validation set",
        ),
        MetricSpec(
            "opa_promotion_gate_passed",
            "bool_true",
            True,
            3.0,
            "OPA policy approved model for production",
        ),
        MetricSpec(
            "kserve_canary_error_rate", "lower_better", 0.01, 2.0, "Canary endpoint error rate"
        ),
    ],
    "UC10": [
        MetricSpec(
            "anomaly_detection_f1", "higher_better", 0.70, 2.0, "F1 on cost anomaly test set"
        ),
        MetricSpec(
            "idle_resource_pct_identified",
            "higher_better",
            0.20,
            1.5,
            "Fraction of idle resources correctly flagged",
        ),
        MetricSpec(
            "namespace_attribution_coverage",
            "higher_better",
            0.95,
            1.5,
            "Fraction of cost attributed to a team",
        ),
    ],
    "UC11": [
        MetricSpec(
            "trace_completeness_pct",
            "higher_better",
            0.90,
            2.0,
            "Fraction of spans present in trace",
        ),
        MetricSpec(
            "rca_span_identified", "bool_true", True, 2.0, "Anomalous span correctly identified"
        ),
        MetricSpec(
            "anomalous_span_precision",
            "higher_better",
            0.60,
            1.5,
            "Precision of anomalous span detection",
        ),
    ],
    "UC12": [
        MetricSpec(
            "drift_detected_when_injected",
            "bool_true",
            True,
            3.0,
            "Injected drift caught by ArgoCD diff",
        ),
        MetricSpec(
            "reconcile_success", "bool_true", True, 2.0, "ArgoCD reconcile returns clean state"
        ),
        MetricSpec(
            "policy_violations_caught",
            "higher_better",
            1,
            2.0,
            "Kyverno/OPA caught test violations",
        ),
    ],
    "UC13": [
        MetricSpec(
            "ge_expectations_passed_pct",
            "higher_better",
            0.95,
            2.0,
            "GE expectation pass rate on good data",
        ),
        MetricSpec(
            "bad_data_blocked", "bool_true", True, 3.0, "Injected bad data blocked by sensor"
        ),
        MetricSpec(
            "schema_validation_pass",
            "bool_true",
            True,
            2.0,
            "Schema matches Great Expectations suite",
        ),
    ],
    "UC14": [
        MetricSpec(
            "best_trial_improvement",
            "higher_better",
            0.0,
            2.0,
            "Best Optuna trial beats default params",
        ),
        MetricSpec(
            "n_trials_completed", "higher_better", 15, 1.0, "Minimum number of HPO trials run"
        ),
        MetricSpec(
            "study_persisted_to_mlflow", "bool_true", True, 2.0, "Study logged to MLflow on DagsHub"
        ),
    ],
    "UC15": [
        MetricSpec(
            "four_keys_all_computed", "bool_true", True, 3.0, "All 4 DORA keys present in output"
        ),
        MetricSpec(
            "deployment_freq_tracked", "bool_true", True, 2.0, "Deploy events captured from GHA"
        ),
        MetricSpec(
            "mttr_computed", "bool_true", True, 2.0, "MTTR computed from incident → resolution"
        ),
    ],
    "UC16": [
        MetricSpec("classification_f1", "higher_better", 0.70, 2.0, "Error taxonomy classifier F1"),
        MetricSpec("n_error_classes", "higher_better", 5, 1.0, "Minimum distinct error classes"),
        MetricSpec(
            "taxonomy_coverage_pct", "higher_better", 0.80, 1.5, "Fraction of logs classified"
        ),
    ],
    "UC17": [
        MetricSpec(
            "shap_values_generated", "bool_true", True, 2.0, "SHAP values computed and logged"
        ),
        MetricSpec(
            "top_features_logged", "higher_better", 1, 1.5, "Number of top features in MLflow"
        ),
        MetricSpec(
            "explanation_coverage_pct",
            "higher_better",
            0.90,
            1.5,
            "Fraction of predictions explained",
        ),
    ],
    "UC18": [
        MetricSpec(
            "rate_limit_precision", "higher_better", 0.70, 2.0, "Precision: bot correctly throttled"
        ),
        MetricSpec(
            "false_throttle_rate",
            "lower_better",
            0.10,
            2.0,
            "Legitimate users incorrectly throttled",
        ),
        MetricSpec("window_accuracy", "higher_better", 0.90, 1.5, "Sliding window count accuracy"),
    ],
    "UC19": [
        MetricSpec("profiles_generated", "bool_true", True, 2.0, "WhyLogs profiles written"),
        MetricSpec(
            "constraint_violations_detected", "higher_better", 1, 3.0, "Injected violation caught"
        ),
        MetricSpec("drift_flagged", "bool_true", True, 2.0, "WhyLogs drift flag set"),
    ],
    "UC20": [
        MetricSpec(
            "catalog_entities_valid", "bool_true", True, 3.0, "All entities pass backstage-cli lint"
        ),
        MetricSpec(
            "n_entities_correct",
            "exact",
            27,
            2.0,
            "Exactly 27 entities (23 services + 3 ML models + 1 system)",
        ),
        MetricSpec("schema_lint_pass", "bool_true", True, 2.0, "catalog-info.yaml schema valid"),
    ],
    "UC21": [
        MetricSpec(
            "slo_compliance_pct", "higher_better", 0.999, 2.0, "SLO met for >= 99.9% of time window"
        ),
        MetricSpec(
            "error_budget_remaining_pct",
            "higher_better",
            0.0,
            2.0,
            "Error budget not exhausted (>= 0%)",
        ),
        MetricSpec(
            "fast_burn_rate_alerts",
            "higher_better",
            1,
            2.0,
            "Fast-burn alert fired in breach window",
        ),
    ],
    "UC22": [
        MetricSpec(
            "ab_test_p_value", "lower_better", 0.05, 2.0, "Statistical significance of A/B result"
        ),
        MetricSpec(
            "winning_version_promoted",
            "bool_true",
            True,
            2.0,
            "Winner automatically promoted to 100%",
        ),
        MetricSpec(
            "traffic_split_accuracy", "higher_better", 0.98, 1.0, "Actual split within 2% of 50/50"
        ),
    ],
    "UC23": [
        MetricSpec(
            "postmortem_generated", "bool_true", True, 2.0, "Post-mortem document generated"
        ),
        MetricSpec("github_issue_created", "bool_true", True, 2.0, "GitHub Issue created by n8n"),
        MetricSpec(
            "similar_incidents_referenced",
            "higher_better",
            1,
            2.0,
            "At least 1 similar incident cited",
        ),
    ],
}


# ---------------------------------------------------------------------------
# EvalResult dataclass
# ---------------------------------------------------------------------------
@dataclass
class EvalResult:
    uc: str
    score: float = 0.0
    passed: bool = False
    threshold: int = 0
    metrics: dict[str, Any] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, output_dir: Path = Path("eval-results")) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{self.uc.lower()}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2, default=str))
        return path

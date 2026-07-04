"""
EU AI Act Compliance Checker — UC7 (Security Policy Enforcement) / Governance.
Validates ML models against EU AI Act Article 9 requirements before promotion.

High-risk AI system requirements checked:
- Risk assessment documentation (model cards)
- Data governance validation (training data sources, bias checks)
- Transparency requirements (SHAP/feature importance logged)
- Human oversight controls (dry-run modes, approval gates)
- Technical robustness (drift monitoring in place)
- Accuracy and performance documentation

References:
- EU AI Act (2024/1689) Article 9, 10, 13, 14, 17
- NIST AI RMF (NIST AI 100-1)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("eu-ai-act-checker")

MLFLOW_URL = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")


@dataclass
class ComplianceCheck:
    name: str
    article: str
    passed: bool
    details: str
    severity: str = "error"  # error | warning | info


@dataclass
class ComplianceReport:
    model_name: str
    version: str
    checks: list[ComplianceCheck] = field(default_factory=list)
    passed: bool = False
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_compliant(self) -> bool:
        return all(
            c.passed for c in self.checks if c.severity == "error"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "version": self.version,
            "is_compliant": self.is_compliant,
            "errors": [c.details for c in self.checks if not c.passed and c.severity == "error"],
            "warnings": [c.details for c in self.checks if not c.passed and c.severity == "warning"],
            "checks": [
                {
                    "name": c.name,
                    "article": c.article,
                    "passed": c.passed,
                    "severity": c.severity,
                    "details": c.details,
                }
                for c in self.checks
            ],
        }


def _get_run_tags_and_metrics(run_id: str) -> tuple[dict, dict]:
    """Fetch tags and metrics from an MLflow run."""
    try:
        resp = httpx.get(
            f"{MLFLOW_URL}/api/2.0/mlflow/runs/get",
            params={"run_id": run_id},
            timeout=10.0,
        )
        resp.raise_for_status()
        run_data = resp.json().get("run", {}).get("data", {})
        tags = {t["key"]: t["value"] for t in run_data.get("tags", [])}
        metrics = {m["key"]: m["value"] for m in run_data.get("metrics", [])}
        return tags, metrics
    except Exception as exc:
        logger.warning("Could not fetch MLflow run %s: %s", run_id, exc)
        return {}, {}


def check_eu_ai_act_compliance(
    model_name: str,
    version: str,
    run_tags: dict[str, str],
    run_metrics: dict[str, float],
    model_card_path: Path | None = None,
) -> ComplianceReport:
    """
    Run EU AI Act compliance checks for a model version.

    Args:
        model_name: Registered model name in MLflow
        version: Model version being checked
        run_tags: MLflow run tags (from the version's run)
        run_metrics: MLflow run metrics
        model_card_path: Path to model card markdown file (optional)

    Returns:
        ComplianceReport with all check results
    """
    report = ComplianceReport(model_name=model_name, version=version)

    # ── Article 9: Risk Management ────────────────────────────────────────────
    has_risk_doc = bool(
        run_tags.get("risk_assessment") or
        run_tags.get("eu_ai_act_risk_level") or
        (model_card_path and model_card_path.exists() and
         "risk" in model_card_path.read_text().lower())
    )
    report.checks.append(ComplianceCheck(
        name="risk_assessment_documented",
        article="Art. 9 — Risk Management",
        passed=has_risk_doc,
        details=(
            "Risk assessment documented in MLflow tags or model card"
            if has_risk_doc
            else "MISSING: Tag 'eu_ai_act_risk_level' or model card with risk section required"
        ),
        severity="error",
    ))

    # ── Article 10: Data Governance ────────────────────────────────────────────
    has_data_lineage = bool(
        run_tags.get("training_dataset") or
        run_tags.get("data_source") or
        run_tags.get("openlineage_run_id")
    )
    report.checks.append(ComplianceCheck(
        name="training_data_documented",
        article="Art. 10 — Data Governance",
        passed=has_data_lineage,
        details=(
            f"Training data source documented: {run_tags.get('training_dataset', run_tags.get('data_source'))}"
            if has_data_lineage
            else "MISSING: Tag 'training_dataset' or 'data_source' required for data governance"
        ),
        severity="error",
    ))

    # ── Article 13: Transparency (Explainability) ─────────────────────────────
    has_shap = bool(
        run_tags.get("shap_values_logged") == "true" or
        run_metrics.get("shap_mean_abs_impact")
    )
    report.checks.append(ComplianceCheck(
        name="explainability_logged",
        article="Art. 13 — Transparency",
        passed=has_shap,
        details=(
            "SHAP values logged — model is explainable (UC17)"
            if has_shap
            else "MISSING: SHAP values must be logged for high-risk AI transparency (UC17)"
        ),
        severity="error",
    ))

    # ── Article 14: Human Oversight ────────────────────────────────────────────
    has_human_oversight = bool(
        run_tags.get("human_review_approved") == "true" or
        run_tags.get("approval_gate_passed") == "true" or
        run_tags.get("requestor") not in (None, "anonymous", "ci-pipeline")
    )
    report.checks.append(ComplianceCheck(
        name="human_oversight_gate",
        article="Art. 14 — Human Oversight",
        passed=has_human_oversight,
        details=(
            f"Human oversight gate passed by: {run_tags.get('requestor', 'unknown')}"
            if has_human_oversight
            else "WARNING: No human review approval tag found — autonomous promotion to production"
        ),
        severity="warning",
    ))

    # ── Article 17: Technical Documentation ───────────────────────────────────
    has_model_card = model_card_path is not None and model_card_path.exists()
    report.checks.append(ComplianceCheck(
        name="model_card_exists",
        article="Art. 17 — Technical Documentation",
        passed=has_model_card,
        details=(
            f"Model card found at {model_card_path}"
            if has_model_card
            else "MISSING: Model card required at mlops/models/<model_name>/model_card.md"
        ),
        severity="error",
    ))

    # ── Drift Monitoring (Recital 47, Art. 9): Continuous monitoring ──────────
    accuracy = run_metrics.get("accuracy", run_metrics.get("val_accuracy", 0.0))
    drift_psi = run_metrics.get("drift_psi", run_metrics.get("psi_score", 0.0))
    has_performance_metrics = accuracy > 0.0
    report.checks.append(ComplianceCheck(
        name="performance_metrics_logged",
        article="Art. 9 — Continuous Monitoring",
        passed=has_performance_metrics,
        details=(
            f"Performance metrics: accuracy={accuracy:.4f}, drift_psi={drift_psi:.4f}"
            if has_performance_metrics
            else "MISSING: Performance metrics (accuracy, F1) must be logged to MLflow"
        ),
        severity="error",
    ))

    # ── Minimum accuracy threshold for high-risk AI ────────────────────────────
    accuracy_sufficient = accuracy >= 0.70 or not has_performance_metrics
    report.checks.append(ComplianceCheck(
        name="minimum_accuracy_threshold",
        article="Art. 9 — Technical Robustness",
        passed=accuracy_sufficient,
        details=(
            f"Accuracy {accuracy:.4f} meets minimum 0.70 threshold"
            if accuracy_sufficient
            else f"FAIL: Accuracy {accuracy:.4f} < 0.70 minimum for production deployment"
        ),
        severity="error",
    ))

    # ── Bias / Fairness check tag ──────────────────────────────────────────────
    has_bias_check = bool(run_tags.get("bias_check_completed") or run_tags.get("fairness_report"))
    report.checks.append(ComplianceCheck(
        name="bias_fairness_check",
        article="Art. 10 — Bias & Fairness",
        passed=has_bias_check,
        details=(
            "Bias/fairness check completed"
            if has_bias_check
            else "WARNING: No bias check documented — consider adding tag 'bias_check_completed'"
        ),
        severity="warning",
    ))

    error_count = sum(1 for c in report.checks if not c.passed and c.severity == "error")
    warning_count = sum(1 for c in report.checks if not c.passed and c.severity == "warning")
    report.passed = report.is_compliant
    report.errors = [c.details for c in report.checks if not c.passed and c.severity == "error"]
    report.warnings = [c.details for c in report.checks if not c.passed and c.severity == "warning"]

    logger.info(
        "EU AI Act compliance for %s v%s: %s (%d errors, %d warnings)",
        model_name,
        version,
        "PASS" if report.is_compliant else "FAIL",
        error_count,
        warning_count,
    )
    return report


def generate_model_card(
    model_name: str,
    version: str,
    run_tags: dict[str, str],
    run_metrics: dict[str, float],
    output_path: Path | None = None,
) -> str:
    """Generate a model card markdown file from MLflow run metadata."""
    accuracy = run_metrics.get("accuracy", run_metrics.get("val_accuracy", "N/A"))
    f1 = run_metrics.get("f1_score", "N/A")
    drift_psi = run_metrics.get("drift_psi", run_metrics.get("psi_score", "N/A"))
    training_data = run_tags.get("training_dataset", run_tags.get("data_source", "Not specified"))
    risk_level = run_tags.get("eu_ai_act_risk_level", "Not assessed")

    card = f"""# Model Card: {model_name} v{version}

## Model Overview
| Field | Value |
|-------|-------|
| Model Name | `{model_name}` |
| Version | {version} |
| Framework | {run_tags.get("mlflow.source.name", "Unknown")} |
| Training Date | {run_tags.get("mlflow.runName", "Unknown")} |

## Performance Metrics
| Metric | Value |
|--------|-------|
| Accuracy | {accuracy:.4f if isinstance(accuracy, float) else accuracy} |
| F1 Score | {f1:.4f if isinstance(f1, float) else f1} |
| Drift PSI | {drift_psi:.4f if isinstance(drift_psi, float) else drift_psi} |

## Data Governance
- **Training Data**: {training_data}
- **Data Source Tags**: {run_tags.get("data_source", "Not specified")}
- **Bias Check**: {run_tags.get("bias_check_completed", "Not completed")}

## EU AI Act Compliance
- **Risk Level**: {risk_level}
- **Human Review**: {run_tags.get("requestor", "Not specified")}
- **SHAP Explainability**: {"✅ Logged" if run_tags.get("shap_values_logged") == "true" else "❌ Not logged"}
- **Drift Monitoring**: {"✅ Active (UC1)" if drift_psi != "N/A" else "❌ Not configured"}

## Intended Use
- **Primary use case**: {run_tags.get("use_case", "Platform AIOps — see README.md")}
- **Out-of-scope**: Production systems without proper oversight approval

## Limitations and Risks
- Model trained on synthetic data — requires revalidation on production data
- Drift detection active via UC1 pipeline
- Rollback automation configured in platform/rollback/auto_rollback.py

## Contact
- **Model Owner**: MLOps Platform Team
- **Review Process**: OPA policy gate + human approval required for production

*Generated automatically by governance/eu-ai-act/compliance_check.py*
*Run ID: {run_tags.get("mlflow.source.git.commit", "unknown")}*
"""

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(card)
        logger.info("Model card written to %s", output_path)

    return card


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    report = check_eu_ai_act_compliance(
        model_name="pod-failure-prediction",
        version="1",
        run_tags={
            "eu_ai_act_risk_level": "limited",
            "training_dataset": "data/synthetic/pod_metrics.parquet",
            "shap_values_logged": "true",
            "requestor": "mlops-engineer",
            "bias_check_completed": "false",
        },
        run_metrics={"accuracy": 0.88, "f1_score": 0.82, "drift_psi": 0.05},
    )
    print(json.dumps(report.to_dict(), indent=2))

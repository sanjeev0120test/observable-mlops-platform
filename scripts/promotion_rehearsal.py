#!/usr/bin/env python3
"""Promotion rehearsal: evidence -> EU AI Act check -> trust score -> ledger -> OPA.

Unlike the trust demo, every candidate is built the way the retrain DAG builds
it (metrics, tags, a Trivy summary, a compliance report from the real checker)
and the OPA gate sees that candidate's own accuracy, drift and SHAP flag.
A model that looks accurate but is unsigned does not get a free pass.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "services" / "model-trust" / "src"))

from assemble import assemble_signals  # noqa: E402
from trust_engine import TrustLedger, compute_trust_score  # noqa: E402


def _checker():
    path = REPO / "governance" / "eu-ai-act" / "compliance_check.py"
    spec = importlib.util.spec_from_file_location("eu_ai_act_compliance_check", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["eu_ai_act_compliance_check"] = module
    spec.loader.exec_module(module)
    return module


def _card(directory: Path) -> Path:
    path = directory / "model_card.md"
    path.write_text(
        "# Model card\n\n## Risk\nFalse negatives miss failing pods.\n",
        encoding="utf-8",
    )
    return path


def _scenarios(card: Path) -> list[dict]:
    checker = _checker()
    complete_tags = {
        "eu_ai_act_risk_level": "high",
        "training_dataset": "feast/pod_metrics_features",
        "shap_values_logged": "true",
        "human_review_approved": "true",
        "bias_check_completed": "true",
    }
    bare_tags = {"requestor": "ci-rehearsal"}

    def compliance(name: str, version: str, tags: dict, metrics: dict, card_path: Path | None):
        report = checker.check_eu_ai_act_compliance(name, version, tags, metrics, card_path)
        return checker.to_trust_evidence(report)

    return [
        {
            "model_name": "pod-failure-prediction",
            "model_version": "12",
            "environment_expect": {"staging": True, "production": True},
            "band": "PRIME",
            "evidence": {
                "metrics": {
                    "accuracy": 0.91,
                    "f1_score": 0.88,
                    "roc_auc": 0.94,
                    "psi_score": 0.04,
                    "ks_statistic": 0.03,
                    "estimated_performance_drop": 0.0,
                    "error_budget_remaining": 0.8,
                    "p99_latency_ms": 120,
                    "cost_per_1k_predictions_usd": 0.02,
                },
                "tags": complete_tags,
                "security": {
                    "critical_cves": 0,
                    "high_cves": 0,
                    "policy_violations": 0,
                    "image_signed": True,
                },
                "compliance": compliance(
                    "pod-failure-prediction",
                    "12",
                    complete_tags,
                    {"accuracy": 0.91, "f1_score": 0.88, "drift_psi": 0.04},
                    card,
                ),
            },
        },
        {
            "model_name": "pod-failure-prediction",
            "model_version": "13",
            "environment_expect": {"staging": False, "production": False},
            "band_in": {"FAIR", "GOOD", "SUBPRIME"},
            "evidence": {
                "metrics": {
                    "accuracy": 0.72,
                    "f1_score": 0.68,
                    "psi_score": 0.35,
                    "estimated_performance_drop": 0.12,
                    "error_budget_remaining": 0.4,
                    "p99_latency_ms": 260,
                    "cost_per_1k_predictions_usd": 0.03,
                },
                "tags": complete_tags,
                "security": {
                    "critical_cves": 0,
                    "high_cves": 1,
                    "policy_violations": 0,
                    "image_signed": True,
                },
                "compliance": compliance(
                    "pod-failure-prediction",
                    "13",
                    complete_tags,
                    {"accuracy": 0.72, "f1_score": 0.68, "drift_psi": 0.35},
                    card,
                ),
            },
        },
        {
            "model_name": "cost-anomaly-detector",
            "model_version": "4",
            "environment_expect": {"staging": False, "production": False},
            "max_score": 599,
            "evidence": {
                "metrics": {
                    "accuracy": 0.93,
                    "f1_score": 0.91,
                    "psi_score": 0.05,
                    "error_budget_remaining": 0.8,
                    "p99_latency_ms": 90,
                    "cost_per_1k_predictions_usd": 0.01,
                },
                "tags": bare_tags,
                "security": {
                    "trivy": {
                        "Results": [
                            {
                                "Vulnerabilities": [
                                    {"Severity": "CRITICAL"},
                                    {"Severity": "CRITICAL"},
                                    {"Severity": "CRITICAL"},
                                ]
                            }
                        ]
                    },
                    "image_signed": False,
                    "policy_violations": 2,
                },
                "compliance": compliance(
                    "cost-anomaly-detector",
                    "4",
                    bare_tags,
                    {"accuracy": 0.93},
                    None,
                ),
            },
        },
    ]


def opa_allow(
    opa_bin: str, policy_dir: Path, report: dict, evidence: dict, environment: str
) -> bool:
    metrics = evidence.get("metrics") or {}
    tags = evidence.get("tags") or {}
    shap = str(tags.get("shap_values_logged", "")).lower() == "true"
    payload = {
        "model_name": report["model_name"],
        "new_version": report["model_version"],
        "metrics": {
            "accuracy": float(metrics.get("accuracy") or 0.0),
            "drift_score": float(metrics.get("psi_score") or 0.0),
            "test_dataset_size": 500,
            "shap_values_logged": shap,
        },
        "requestor": "ci-rehearsal",
        "environment": environment,
        "trust": {
            "score": report["score"],
            "band": report["band"],
            "ledger_integrity_ok": True,
        },
    }
    out = subprocess.run(
        [
            opa_bin,
            "eval",
            "-f",
            "json",
            "-d",
            str(policy_dir),
            "--stdin-input",
            "data.platform.model_promotion",
        ],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=True,
    )
    value = json.loads(out.stdout)["result"][0]["expressions"][0]["value"]
    return bool(value.get("allow"))


def rehearse(out: Path, opa_bin: str | None) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    card = _card(out)
    ledger_path = out / "trust_ledger.jsonl"
    ledger_path.unlink(missing_ok=True)
    ledger = TrustLedger(ledger_path)
    policy_dir = REPO / "aiops" / "policies" / "opa"
    rows: list[dict] = []

    for scenario in _scenarios(card):
        signals = assemble_signals(scenario["evidence"])
        report = compute_trust_score(
            scenario["model_name"], scenario["model_version"], signals, target_band="GOOD"
        )
        ledger.append(report)
        body = report.to_dict()
        body["signals_used"] = signals
        if opa_bin:
            body["opa_staging"] = opa_allow(
                opa_bin, policy_dir, body, scenario["evidence"], "staging"
            )
            body["opa_production"] = opa_allow(
                opa_bin, policy_dir, body, scenario["evidence"], "production"
            )
        name = f"{scenario['model_name']}-v{scenario['model_version']}.json"
        (out / name).write_text(json.dumps(body, indent=2), encoding="utf-8")
        rows.append({"scenario": scenario, "report": body})
        print(
            f"{scenario['model_name']} v{scenario['model_version']}: "
            f"score={report.score} band={report.band} "
            f"prod={body.get('opa_production', 'n/a')}"
        )

    verification = ledger.verify()
    if not verification.ok:
        raise AssertionError(f"fresh ledger failed verification: {verification}")

    tampered = out / "trust_ledger.TAMPERED.jsonl"
    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    # The champion is already 1000, so edit a later entry's score. The stored
    # hash was computed over the original body and must no longer match.
    entry = json.loads(lines[1])
    entry["score"] = 300
    entry["band"] = "SUBPRIME"
    lines[1] = json.dumps(entry, sort_keys=True)
    tampered.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tampered_verification = TrustLedger(tampered).verify()
    if tampered_verification.ok or tampered_verification.first_bad_seq != 2:
        raise AssertionError(f"tamper was not caught at seq 2: {tampered_verification}")

    for row in rows:
        scenario = row["scenario"]
        report = row["report"]
        if "band" in scenario and report["band"] != scenario["band"]:
            raise AssertionError(
                f"{report['model_name']} band {report['band']} != {scenario['band']}"
            )
        if "band_in" in scenario and report["band"] not in scenario["band_in"]:
            raise AssertionError(
                f"{report['model_name']} band {report['band']} not in {scenario['band_in']}"
            )
        if "max_score" in scenario and report["score"] > scenario["max_score"]:
            raise AssertionError(
                f"{report['model_name']} score {report['score']} above cap {scenario['max_score']}"
            )
        if opa_bin:
            for env, expected in scenario["environment_expect"].items():
                actual = report[f"opa_{env}"]
                if actual is not expected:
                    raise AssertionError(
                        f"{report['model_name']} {env} allow={actual}, expected {expected}"
                    )
    (out / "attestation.json").write_text(
        json.dumps(ledger.attestation(), indent=2), encoding="utf-8"
    )
    print(f"ledger ok, tamper caught at seq {tampered_verification.first_bad_seq}")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="rehearsal-results")
    parser.add_argument("--opa", default=shutil.which("opa"))
    parser.add_argument("--require-opa", action="store_true")
    args = parser.parse_args()
    if args.require_opa and not args.opa:
        print("opa binary not found", file=sys.stderr)
        return 2
    rehearse(Path(args.out), args.opa)
    print("promotion rehearsal passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

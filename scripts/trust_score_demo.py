#!/usr/bin/env python3
"""
End-to-end Model Trust Score demo. Runs in CI (workflow 30) and locally (`make trust-demo`).

1. Scores three realistic model versions (healthy / drifting / compromised image).
2. Appends each to a hash-chained ledger and verifies the chain.
3. Tampers with a *copy* of the ledger and shows verification pinpoints the entry.
4. Evaluates every result against the OPA model_promotion policy (if `opa` is installed).
5. Writes attestation + per-model reports to --out and a Markdown summary to --summary.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "services" / "model-trust" / "src"))

from trust_engine import TrustLedger, compute_trust_score  # noqa: E402

SCENARIOS = {
    # Healthy champion: everything measured, everything green.
    "pod-failure-prediction@v12 (champion)": (
        "pod-failure-prediction",
        "12",
        {
            "psi_score": 0.04,
            "ks_statistic": 0.05,
            "accuracy": 0.89,
            "f1_score": 0.86,
            "estimated_performance_drop": 0.01,
            "error_budget_remaining": 0.72,
            "p99_latency_ms": 180,
            "availability_30d": 0.9995,
            "cost_per_1k_predictions_usd": 0.02,
            "critical_cves": 0,
            "high_cves": 1,
            "policy_violations": 0,
            "image_signed": True,
            "shap_logged": True,
            "model_card_present": True,
            "lineage_recorded": True,
            "eu_ai_act_compliant": True,
            "human_oversight_defined": True,
        },
    ),
    # Drifting challenger: inputs moved, accuracy sliding, nobody logged SHAP yet.
    "pod-failure-prediction@v13 (challenger)": (
        "pod-failure-prediction",
        "13",
        {
            "psi_score": 0.31,
            "ks_statistic": 0.22,
            "accuracy": 0.74,
            "estimated_performance_drop": 0.09,
            "error_budget_remaining": 0.55,
            "p99_latency_ms": 240,
            "cost_per_1k_predictions_usd": 0.03,
            "critical_cves": 0,
            "high_cves": 3,
            "policy_violations": 0,
            "image_signed": True,
            "shap_logged": False,
            "model_card_present": True,
            "lineage_recorded": True,
            "eu_ai_act_compliant": False,
            "human_oversight_defined": True,
        },
    ),
    # Compromised build: great accuracy, but unsigned image with critical CVEs and a
    # privileged-pod policy violation. Accuracy dashboards would call this model "fine".
    "cost-anomaly-detector@v4": (
        "cost-anomaly-detector",
        "4",
        {
            "psi_score": 0.06,
            "accuracy": 0.93,
            "error_budget_remaining": 0.80,
            "p99_latency_ms": 90,
            "cost_per_1k_predictions_usd": 0.01,
            "critical_cves": 3,
            "high_cves": 11,
            "policy_violations": 2,
            "image_signed": False,
            "shap_logged": True,
            "model_card_present": False,
            "lineage_recorded": False,
            "eu_ai_act_compliant": False,
            "human_oversight_defined": False,
        },
    ),
}


def opa_decision(opa_bin: str, policy_dir: Path, report: dict, environment: str) -> dict | None:
    inp = {
        "model_name": report["model_name"],
        "new_version": report["model_version"],
        "metrics": {
            "accuracy": 0.90,
            "drift_score": 0.05,
            "test_dataset_size": 1000,
            "shap_values_logged": True,
        },
        "requestor": "ci-demo",
        "environment": environment,
        "trust": {"score": report["score"], "band": report["band"], "ledger_integrity_ok": True},
    }
    try:
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
            input=json.dumps(inp),
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(out.stdout)["result"][0]["expressions"][0]["value"]
    except (subprocess.CalledProcessError, KeyError, IndexError, json.JSONDecodeError) as exc:
        print(f"[warn] opa eval failed: {exc}", file=sys.stderr)
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="trust-results")
    ap.add_argument("--summary", default=None, help="Markdown file to append summary to")
    ap.add_argument("--opa", default=shutil.which("opa"), help="Path to opa binary")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ledger_path = out / "trust_ledger.jsonl"
    ledger_path.unlink(missing_ok=True)
    ledger = TrustLedger(ledger_path)
    policy_dir = REPO / "aiops" / "policies" / "opa"

    rows: list[str] = []
    reports: list[dict] = []
    for label, (name, version, signals) in SCENARIOS.items():
        r = compute_trust_score(name, version, signals, target_band="GOOD")
        ledger.append(r)
        d = r.to_dict()
        d["opa_staging"] = opa_decision(args.opa, policy_dir, d, "staging") if args.opa else None
        d["opa_production"] = (
            opa_decision(args.opa, policy_dir, d, "production") if args.opa else None
        )
        reports.append(d)
        (out / f"{name}-v{version}.json").write_text(json.dumps(d, indent=2), encoding="utf-8")

        top = r.recommendations[0] if r.recommendations else None
        gate = "n/a"
        if d["opa_production"] is not None:
            gate = "ALLOW" if d["opa_production"].get("allow") else "DENY"
        rows.append(
            f"| {label} | **{r.score}** | {r.band} | "
            f"{(top.action + f' (+{top.points_recoverable} pts, {top.effort_hours}h)') if top else 'none needed'} | "
            f"{r.plan_to_target_hours}h | {gate} |"
        )
        print(f"{label:48s} score={r.score:4d} band={r.band:8s} prod-gate={gate}")

    v = ledger.verify()
    assert v.ok, f"fresh ledger must verify: {v}"

    # Tamper-evidence proof on a copy.
    tampered_path = out / "trust_ledger.TAMPERED.jsonl"
    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    e = json.loads(lines[1])
    e["score"] = 999
    e["band"] = "PRIME"
    lines[1] = json.dumps(e, sort_keys=True)
    tampered_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tv = TrustLedger(tampered_path).verify()
    assert not tv.ok and tv.first_bad_seq == 2, f"tampering must be detected at seq 2: {tv}"
    print(f"\nledger verify: ok={v.ok} entries={v.entries} head={v.head_hash[:16]}…")
    print(f"tampered copy: ok={tv.ok} first_bad_seq={tv.first_bad_seq} reason={tv.reason}")

    att = ledger.attestation()
    (out / "attestation.json").write_text(json.dumps(att, indent=2), encoding="utf-8")

    md = [
        "## Model Trust Score — CI demo",
        "",
        "| Model version | Score | Band | Cheapest high-ROI fix | Hours to GOOD | OPA prod gate |",
        "|---|---:|---|---|---:|---|",
        *rows,
        "",
        f"Ledger: {v.entries} entries, chain **{'VERIFIED' if v.ok else 'BROKEN'}**, head `{v.head_hash[:16]}…`  ",
        f"Tamper test: edited seq 2 in a copy → verification fails at seq **{tv.first_bad_seq}** ({tv.reason}).",
        "",
    ]
    text = "\n".join(md)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    (out / "summary.md").write_text(text, encoding="utf-8")

    # Sanity assertions that make this a real gate, not a printout.
    by_name = {f"{r['model_name']}:{r['model_version']}": r for r in reports}
    assert by_name["pod-failure-prediction:12"]["band"] == "PRIME"
    assert by_name["pod-failure-prediction:13"]["band"] in {"GOOD", "FAIR"}
    assert by_name["cost-anomaly-detector:4"]["band"] in {"FAIR", "SUBPRIME"}
    if args.opa:
        assert by_name["pod-failure-prediction:12"]["opa_production"]["allow"] is True
        assert by_name["cost-anomaly-detector:4"]["opa_production"]["allow"] is False
    print("\nall demo assertions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Static repository contracts: layout, observability coverage, manifests, CI wiring."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parent.parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"

REQUIRED_DIRS = [
    "infra/docker-compose",
    "infra/kind",
    "infra/terraform/aws-eks",
    "infra/kubernetes/base/model-trust",
    "mlops/feature-store/feature_repo",
    "mlops/pipelines/airflow/dags",
    "mlops/experiments/pod_failure_prediction",
    "mlops/experiments/log_anomaly",
    "aiops/n8n-workflows",
    "aiops/policies/opa",
    "aiops/policies/kyverno",
    "aiops/falco",
    "observability/dashboards/grafana",
    "observability/alerts",
    "observability/otel",
    "data/synthetic",
    "eval",
] + [
    f"services/{s}/src"
    for s in (
        "anomaly-detector",
        "drift-monitor",
        "alert-correlator",
        "predictive-scaler",
        "self-healing",
        "runbook-agent",
        "cost-optimizer",
        "model-trust",
    )
]


@pytest.mark.parametrize("path", REQUIRED_DIRS)
def test_required_directory(path):
    assert (ROOT / path).is_dir(), f"missing directory: {path}"


def _alert_rules() -> list[dict]:
    rules = yaml.safe_load((ROOT / "observability/alerts/rules/platform.yml").read_text())
    return [r for g in rules["groups"] for r in g["rules"]]


def test_critical_ucs_have_alerts():
    ucs = {r.get("labels", {}).get("uc") for r in _alert_rules() if "alert" in r}
    missing = {"UC1", "UC2", "UC4", "UC10", "UC21"} - ucs
    assert not missing, f"missing Prometheus alerts for {missing}"


def test_required_alerts_and_routes():
    names = {r["alert"] for r in _alert_rules() if "alert" in r}
    required = {
        "MLModelDriftDetected",
        "PodCrashLoopBackOff",
        "HighCPUPreScale",
        "IdleResourceWaste",
        "SLOFastBurnRate",
    }
    assert required <= names, f"missing alerts: {required - names}"
    routes = str(yaml.safe_load((ROOT / "observability/alerts/alertmanager.yml").read_text()))
    assert "UC6" in routes and "UC23" in routes


def test_otel_collector_pipelines():
    cfg = yaml.safe_load((ROOT / "observability/otel/otelcol.yml").read_text())
    pipelines = cfg["service"]["pipelines"]
    assert {"traces", "metrics", "logs"} <= set(pipelines)
    exporters = set(cfg["exporters"])
    assert {"otlp/tempo", "otlphttp/loki", "prometheusremotewrite"} <= exporters
    for name, pipe in pipelines.items():
        for exp in pipe["exporters"]:
            assert exp in exporters, f"pipeline {name} uses undefined exporter {exp}"


def test_grafana_overview_panels():
    dash = json.loads((ROOT / "observability/dashboards/grafana/overview.json").read_text())
    titles = " ".join(p.get("title", "") for p in dash.get("panels", []))
    for uc in ("UC21", "UC1", "UC10", "UC3"):
        assert uc in titles, f"Grafana overview missing panel for {uc}"


def test_chaos_manifests():
    files = sorted((ROOT / "platform/chaos").glob("*.y*ml"))
    assert files and (ROOT / "platform/chaos/opa-unavailable.yaml").exists()
    for f in files:
        docs = [d for d in yaml.safe_load_all(f.read_text()) if d]
        assert docs, f"{f} is empty"
        for d in docs:
            assert "kind" in d and "metadata" in d, f"{f}: incomplete document"


@pytest.mark.parametrize(
    "script", ["k6_self_healing.js", "k6_drift_monitor.js", "k6_runbook_agent.js"]
)
def test_k6_scripts_present(script):
    assert (ROOT / "tests/load" / script).is_file()


def test_kubernetes_deployments_hardened():
    deployments = 0
    for f in sorted((ROOT / "infra/kubernetes/base").rglob("*.yaml")):
        for d in (d for d in yaml.safe_load_all(f.read_text()) if d):
            assert d.get("kind"), f"{f}: document missing kind"
            if d["kind"] != "Deployment":
                continue
            deployments += 1
            pod = d["spec"]["template"]["spec"]
            assert pod["securityContext"].get("runAsNonRoot") is True, f
            c = pod["containers"][0]
            csc = c["securityContext"]
            assert csc.get("allowPrivilegeEscalation") is False, f
            assert csc.get("readOnlyRootFilesystem") is True, f
            assert "ALL" in csc["capabilities"]["drop"], f
            assert c["resources"]["limits"]["memory"], f
    assert deployments, "expected at least one hardened Deployment"


def test_falco_rules():
    docs = list(yaml.safe_load_all((ROOT / "aiops/falco/custom_rules.yml").read_text()))
    items = docs[0] if docs and isinstance(docs[0], list) else docs
    assert sum(1 for d in items if isinstance(d, dict) and "rule" in d) >= 5


def test_backstage_catalog_entities():
    entities = [
        e for e in yaml.safe_load_all((ROOT / "backstage/catalog-info.yaml").read_text()) if e
    ]
    assert entities
    for e in entities:
        assert {"apiVersion", "kind"} <= set(e) and "name" in e.get("metadata", {}), e
        if e["kind"] in ("Component", "Resource"):
            assert "owner" in e.get("spec", {}), e["metadata"]["name"]


def _on(workflow: dict) -> dict:
    # PyYAML parses the bare key `on` as boolean True.
    return workflow.get("on", workflow.get(True)) or {}


def test_every_uc_workflow_is_orchestrated():
    orchestrator = yaml.safe_load((WORKFLOWS / "uc-evals.yml").read_text())
    called = {Path(job["uses"]).name for job in orchestrator["jobs"].values() if "uses" in job}
    reusable = {
        f.name
        for f in WORKFLOWS.glob("[0-9][0-9]-*.yml")
        if "workflow_call" in _on(yaml.safe_load(f.read_text()))
    }
    assert reusable, "no reusable UC workflows found"
    assert reusable == called, (
        f"not orchestrated: {reusable - called}; dangling: {called - reusable}"
    )


def test_workflows_pin_third_party_actions():
    files = [*WORKFLOWS.glob("*.yml"), *(ROOT / ".github/actions").glob("*/action.yml")]
    for f in files:
        for line in f.read_text().splitlines():
            line = line.strip().removeprefix("- ")
            if not line.startswith("uses:") or "./" in line:
                continue
            ref = line.split("@", 1)[1].split()[0]
            assert len(ref) == 40, f"{f}: unpinned action {line}"


def test_ci_container_matrix_covers_every_service():
    ci = yaml.safe_load((WORKFLOWS / "ci.yml").read_text())
    steps = {s.get("id"): s for s in ci["jobs"]["changes"]["steps"]}
    filtered = set(yaml.safe_load(steps["svc"]["with"]["filters"]))
    fallback = set(json.loads(steps["out"]["env"]["ALL_SERVICES"]))
    services = {p.parent.name for p in (ROOT / "services").glob("*/Dockerfile")}
    assert filtered == fallback == services


def test_ci_ok_requires_every_ci_job():
    jobs = yaml.safe_load((WORKFLOWS / "ci.yml").read_text())["jobs"]
    assert set(jobs["ci-ok"]["needs"]) == set(jobs) - {"ci-ok"}

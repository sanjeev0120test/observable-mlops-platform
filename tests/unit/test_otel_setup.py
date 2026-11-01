"""The platform services share one OpenTelemetry bootstrap.

The canonical module lives in platform/observability. Each service image
build context is its own directory, so the same file is copied into
services/*/src. This test keeps those copies identical and checks that a
business route produces a span while probes do not.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CANONICAL = REPO / "platform" / "observability" / "otel_setup.py"
COPIES = sorted((REPO / "services").glob("*/src/otel_setup.py"))
COLLECTOR = REPO / "observability" / "otel" / "otelcol.yml"


def test_every_service_ships_the_canonical_bootstrap():
    canonical = CANONICAL.read_bytes()
    assert COPIES, "expected otel_setup.py beside each service main.py"
    assert len(COPIES) == 8
    for copy in COPIES:
        assert copy.read_bytes() == canonical, copy


def test_collector_fans_traces_metrics_and_logs_out():
    text = COLLECTOR.read_text(encoding="utf-8")
    assert "exporters: [otlp/tempo, debug]" in text
    assert "exporters: [prometheusremotewrite]" in text
    assert "exporters: [otlphttp/loki]" in text
    assert "endpoint: http://loki:3100/otlp" in text
    assert 'value: "ci"' not in text
    assert "\n  logging:" not in text


def test_business_route_is_traced_and_probes_are_not():
    pytest.importorskip("fastapi")
    pytest.importorskip("opentelemetry")
    os.environ.pop("OTEL_SDK_DISABLED", None)

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    spec = importlib.util.spec_from_file_location("platform_otel_setup", CANONICAL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    app = FastAPI(title="Anomaly Detector", version="0.1.0")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/api/v1/detect")
    def detect():
        return {"anomalies_detected": 0}

    spans = InMemorySpanExporter()
    module.configure_telemetry(
        app,
        service_namespace="observable-mlops",
        service_name="anomaly-detector",
        service_version="0.1.0",
        span_exporter=spans,
        metric_reader=InMemoryMetricReader(),
        log_exporter=InMemoryLogRecordExporter(),
    )

    transport = ASGITransport(app=app)
    with __import__("asyncio").Runner() as runner:

        async def exercise():
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                health_response = await client.get("/health")
                detect_response = await client.post("/api/v1/detect")
            return health_response, detect_response

        health_response, detect_response = runner.run(exercise())

    assert health_response.status_code == 200
    assert detect_response.status_code == 200
    finished = spans.get_finished_spans()
    described = [f"{span.name} {dict(span.attributes or {})}" for span in finished]
    assert any("detect" in item for item in described), described
    assert all("health" not in item for item in described), described
    assert finished[0].resource.attributes["service.name"] == "anomaly-detector"
    assert finished[0].resource.attributes["service.namespace"] == "observable-mlops"
    module.shutdown_telemetry()

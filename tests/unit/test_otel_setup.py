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


@pytest.fixture
def otel_enabled():
    """Enable the SDK for one test, then put the process back how we found it.

    The unit-test conftest disables export. Leaving the flag unset makes every
    later service import open OTLP exporters against localhost.
    """
    previous = os.environ.pop("OTEL_SDK_DISABLED", None)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("OTEL_SDK_DISABLED", None)
        else:
            os.environ["OTEL_SDK_DISABLED"] = previous


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


@pytest.mark.usefixtures("otel_enabled")
def test_business_route_is_traced_and_probes_are_not():
    pytest.importorskip("fastapi")
    pytest.importorskip("opentelemetry")

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


@pytest.mark.usefixtures("otel_enabled")
def test_init_telemetry_survives_without_add_event_handler():
    pytest.importorskip("fastapi")
    pytest.importorskip("opentelemetry")

    from fastapi import FastAPI
    from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    spec = importlib.util.spec_from_file_location("platform_otel_setup_init", CANONICAL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    real_configure = module.configure_telemetry

    def configure_in_memory(app, **kwargs):
        kwargs["span_exporter"] = InMemorySpanExporter()
        kwargs["metric_reader"] = InMemoryMetricReader()
        kwargs["log_exporter"] = InMemoryLogRecordExporter()
        return real_configure(app, **kwargs)

    # init_telemetry looks this name up on the module. The wrapper keeps the
    # real function so it does not recurse and does not open an OTLP socket.
    module.configure_telemetry = configure_in_memory

    original = getattr(FastAPI, "add_event_handler", None)

    def removed(*_args, **_kwargs):
        raise AssertionError("add_event_handler is not available on current FastAPI")

    FastAPI.add_event_handler = removed  # type: ignore[method-assign]
    try:
        app = FastAPI(title="Anomaly Detector", version="0.1.0")
        module.init_telemetry(app, service_namespace="observable-mlops")
        assert app.router.lifespan_context.__name__ == "_otel_lifespan"
    finally:
        if original is None:
            del FastAPI.add_event_handler
        else:
            FastAPI.add_event_handler = original  # type: ignore[method-assign]
        module.shutdown_telemetry()

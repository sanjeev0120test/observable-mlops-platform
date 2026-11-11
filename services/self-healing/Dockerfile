FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_NO_CACHE=1

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Versions track uv.lock; only what src/ actually imports.
RUN uv pip install \
    fastapi==0.162.2 \
    "uvicorn[standard]==0.54.0" \
    pydantic==2.14.3 \
    prometheus-client==0.26.0 \
    httpx==0.28.1

RUN uv pip install \
    opentelemetry-api==1.45.2 \
    opentelemetry-sdk==1.45.2 \
    opentelemetry-exporter-otlp-proto-http==1.45.2 \
    opentelemetry-instrumentation-fastapi==0.66b2 \
    opentelemetry-instrumentation-logging==0.66b2 \
    opentelemetry-instrumentation-httpx==0.66b2

COPY src/ /app/src/

# Run as an unprivileged user (satisfies Kyverno require-run-as-nonroot / OPA gates).
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER 10001

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TRUST_LEDGER_PATH=/app/data/trust_ledger.jsonl

WORKDIR /app

# mlflow-skinny: registry client only (no server/UI deps) for score write-back.
RUN pip install --no-cache-dir \
    fastapi==0.111.0 \
    uvicorn[standard]==0.30.1 \
    pydantic==2.7.4 \
    prometheus-client==0.20.0 \
    mlflow-skinny==3.17.1

COPY src/ /app/src/

RUN mkdir -p /app/data \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER 10001

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=4)"

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]

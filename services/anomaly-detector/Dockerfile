FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi==0.111.0 \
    uvicorn[standard]==0.30.1 \
    numpy==1.26.4 \
    pandas==2.2.2 \
    torch==2.3.0 --index-url https://download.pytorch.org/whl/cpu \
    qdrant-client==1.9.1 \
    mlflow==2.13.0 \
    prometheus-client==0.20.0 \
    opentelemetry-api==1.24.0 \
    opentelemetry-sdk==1.24.0 \
    opentelemetry-exporter-otlp==1.24.0 \
    httpx==0.27.0

COPY src/ /app/src/

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]

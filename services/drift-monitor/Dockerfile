FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi==0.111.0 \
    uvicorn[standard]==0.30.1 \
    numpy==1.26.4 \
    pandas==2.2.2 \
    pyarrow==15.0.2 \
    evidently==0.4.30 \
    nannyml==0.12.3 \
    alibi-detect==0.12.0 \
    mlflow==3.17.1 \
    prometheus-client==0.20.0 \
    httpx==0.27.0

COPY src/ /app/src/

RUN mkdir -p /app/reports \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER 10001

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=4)"

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]

# MLflow 3 tracking server with the Postgres driver and S3 client the upstream image omits.
# The upstream ghcr.io/mlflow/mlflow image only supports sqlite/file backends out of the box.
FROM ghcr.io/mlflow/mlflow:v3.17.1

RUN pip install --no-cache-dir psycopg2-binary==2.9.10 boto3==1.40.49

RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin mlflow \
    && mkdir -p /mlflow/artifacts \
    && chown -R mlflow:mlflow /mlflow
USER 10001

EXPOSE 5000

HEALTHCHECK --interval=15s --timeout=10s --start-period=30s --retries=8 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health', timeout=8)"

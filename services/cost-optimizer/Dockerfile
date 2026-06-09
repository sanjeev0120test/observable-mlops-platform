FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi==0.111.0 \
    uvicorn[standard]==0.30.1 \
    numpy==1.26.4 \
    pandas==2.2.2 \
    pyarrow==16.0.0 \
    scikit-learn==1.5.0 \
    mlflow==2.13.0 \
    httpx==0.27.0 \
    prometheus-client==0.20.0

COPY src/ /app/src/

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]

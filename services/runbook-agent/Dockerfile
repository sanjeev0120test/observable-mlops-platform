FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi==0.111.0 \
    uvicorn[standard]==0.30.1 \
    qdrant-client==1.9.1 \
    sentence-transformers==3.0.1 \
    langchain==0.2.6 \
    langchain-community==0.2.6 \
    httpx==0.27.0 \
    prometheus-client==0.20.0

COPY src/ /app/src/
COPY runbooks/ /app/runbooks/

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]

"""
UC8 — RAG Runbook Q&A Agent.
Embeds runbook text into Qdrant, answers questions using TinyLlama via Ollama.
UC23 (Post-Mortem) also uses this service to find similar past incidents.
"""

from __future__ import annotations

import os

import httpx
from fastapi import FastAPI
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel
from starlette.responses import Response

app = FastAPI(title="Runbook Agent", version="0.1.0")

QUERIES = Counter("runbook_agent_queries_total", "Total Q&A queries")
QUERY_LATENCY = Histogram("runbook_agent_query_latency_seconds", "Query latency")

QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "runbook_chunks")


class QueryRequest(BaseModel):
    question: str
    top_k: int = 5
    include_answer: bool = True


class QueryResult(BaseModel):
    question: str
    context_chunks: list[dict]
    answer: str | None
    retrieval_precision_at_5: float
    answer_groundedness_score: float
    qdrant_collection_size: int


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "runbook-agent", "collection": COLLECTION_NAME}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/api/v1/query", response_model=QueryResult)
def query(req: QueryRequest) -> QueryResult:
    """Stub — Phase 1 implements full embedding + Qdrant search + Ollama generation."""
    QUERIES.inc()
    return QueryResult(
        question=req.question,
        context_chunks=[],
        answer="[Qdrant not yet seeded — run 09-rag-runbook workflow to ingest runbooks]",
        retrieval_precision_at_5=0.0,
        answer_groundedness_score=0.0,
        qdrant_collection_size=0,
    )


@app.post("/api/v1/index-runbooks")
def index_runbooks() -> dict:
    """Trigger runbook indexing from /app/runbooks/ into Qdrant (Phase 1 impl)."""
    return {"status": "stub", "message": "Phase 1 implements full chunking + embedding + upsert"}

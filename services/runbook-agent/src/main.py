"""
UC8 — RAG Runbook Q&A Agent.
ENHANCED: Wires real Qdrant search + Ollama generation (removes stub).
Embeds runbook text into Qdrant, answers questions using TinyLlama via Ollama.
UC23 (Post-Mortem) also uses this service to find similar past incidents.

Endpoints:
  POST /api/v1/query          — Q&A with retrieval + LLM generation
  POST /api/v1/index-runbooks — Index /app/runbooks/ into Qdrant
  GET  /health
  GET  /metrics
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, BackgroundTasks, HTTPException
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel
from starlette.responses import Response

logger = logging.getLogger(__name__)

app = FastAPI(title="Runbook Agent", version="0.2.0")

QUERIES = Counter("runbook_agent_queries_total", "Total Q&A queries", ["status"])
QUERY_LATENCY = Histogram(
    "runbook_agent_query_latency_seconds",
    "Query latency",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0],
)
COLLECTION_SIZE = Gauge("runbook_agent_collection_size", "Number of chunks in Qdrant collection")
INDEXING_RUNS = Counter("runbook_agent_indexing_runs_total", "Times runbooks were indexed")

QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "runbook_chunks")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "tinyllama")
EMBEDDING_DIM = 384  # sentence-transformers/all-MiniLM-L6-v2 dimension
RUNBOOK_DIR = Path(os.getenv("RUNBOOK_DIR", "/app/runbooks"))
CHUNK_SIZE = 400       # characters per chunk
CHUNK_OVERLAP = 80     # character overlap between chunks


def _get_embedding(text: str) -> list[float]:
    """Get sentence embedding from Ollama or fallback to simple hash-based vector."""
    try:
        resp = httpx.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={"model": OLLAMA_MODEL, "prompt": text},
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json().get("embedding", [])
    except Exception as exc:
        logger.warning("Ollama embedding failed (%s) — using fallback", exc)
        # Deterministic hash-based embedding for CI/testing (not semantic, but functional)
        import hashlib
        import struct
        h = hashlib.md5(text.encode()).digest()
        base = [struct.unpack("b", bytes([h[i % 16]]))[0] / 128.0 for i in range(EMBEDDING_DIM)]
        return base


def _ensure_collection() -> bool:
    """Create Qdrant collection if it doesn't exist. Returns True if ready."""
    try:
        resp = httpx.get(f"{QDRANT_URL}/collections/{COLLECTION_NAME}", timeout=5.0)
        if resp.status_code == 200:
            size = resp.json().get("result", {}).get("vectors_count", 0)
            COLLECTION_SIZE.set(size)
            return True
        # Create collection
        create_resp = httpx.put(
            f"{QDRANT_URL}/collections/{COLLECTION_NAME}",
            json={
                "vectors": {
                    "size": EMBEDDING_DIM,
                    "distance": "Cosine",
                }
            },
            timeout=10.0,
        )
        create_resp.raise_for_status()
        logger.info("Qdrant collection '%s' created", COLLECTION_NAME)
        return True
    except Exception as exc:
        logger.warning("Qdrant unavailable: %s", exc)
        return False


def _chunk_text(text: str, source: str) -> list[dict]:
    """Split text into overlapping chunks with metadata."""
    chunks = []
    start = 0
    idx = 0
    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        chunk_text = text[start:end].strip()
        if chunk_text:
            chunks.append({
                "text": chunk_text,
                "source": source,
                "chunk_idx": idx,
                "char_start": start,
            })
        start += CHUNK_SIZE - CHUNK_OVERLAP
        idx += 1
    return chunks


def _index_document(source: str, content: str, base_id: int) -> int:
    """Embed and upsert a document's chunks into Qdrant. Returns number of chunks indexed."""
    chunks = _chunk_text(content, source)
    if not chunks:
        return 0

    points = []
    for i, chunk in enumerate(chunks):
        embedding = _get_embedding(chunk["text"])
        if not embedding:
            continue
        points.append({
            "id": base_id + i,
            "vector": embedding,
            "payload": {
                "text": chunk["text"],
                "source": chunk["source"],
                "chunk_idx": chunk["chunk_idx"],
            },
        })

    if points:
        resp = httpx.put(
            f"{QDRANT_URL}/collections/{COLLECTION_NAME}/points",
            json={"points": points},
            timeout=30.0,
        )
        resp.raise_for_status()

    return len(points)


def _search_qdrant(query: str, top_k: int = 5) -> list[dict]:
    """Search Qdrant for relevant chunks."""
    embedding = _get_embedding(query)
    if not embedding:
        return []
    try:
        resp = httpx.post(
            f"{QDRANT_URL}/collections/{COLLECTION_NAME}/points/search",
            json={
                "vector": embedding,
                "limit": top_k,
                "with_payload": True,
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        results = resp.json().get("result", [])
        return [
            {
                "text": r["payload"].get("text", ""),
                "source": r["payload"].get("source", "unknown"),
                "score": r.get("score", 0.0),
            }
            for r in results
        ]
    except Exception as exc:
        logger.warning("Qdrant search failed: %s", exc)
        return []


def _generate_answer(question: str, context_chunks: list[dict]) -> str:
    """Generate answer using Ollama with retrieved context."""
    if not context_chunks:
        return "No relevant runbook content found. Run /api/v1/index-runbooks to seed the knowledge base."

    context_text = "\n\n".join(
        f"[{c['source']}]\n{c['text']}" for c in context_chunks[:3]
    )
    prompt = (
        f"You are an SRE expert. Answer the question based ONLY on the provided runbook context.\n\n"
        f"Context:\n{context_text}\n\n"
        f"Question: {question}\n\n"
        f"Answer (concise, actionable, step-by-step if applicable):"
    )

    try:
        resp = httpx.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=60.0,
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except Exception as exc:
        logger.warning("Ollama generation failed: %s", exc)
        # Return context directly as fallback
        return f"[Ollama unavailable — returning top context]\n\n{context_chunks[0]['text']}"


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
    latency_ms: float


@app.get("/health")
def health() -> dict:
    qdrant_ok = False
    try:
        r = httpx.get(f"{QDRANT_URL}/collections/{COLLECTION_NAME}", timeout=3.0)
        qdrant_ok = r.status_code == 200
    except Exception:
        pass
    return {
        "status": "ok",
        "service": "runbook-agent",
        "version": "0.2.0",
        "collection": COLLECTION_NAME,
        "qdrant_reachable": qdrant_ok,
        "ollama_url": OLLAMA_URL,
    }


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/api/v1/query", response_model=QueryResult)
def query(req: QueryRequest) -> QueryResult:
    """Q&A: retrieve relevant runbook chunks from Qdrant and generate answer via Ollama."""
    start = time.perf_counter()

    if not _ensure_collection():
        QUERIES.labels(status="qdrant_unavailable").inc()
        return QueryResult(
            question=req.question,
            context_chunks=[],
            answer="Qdrant is unavailable — cannot retrieve runbook context",
            retrieval_precision_at_5=0.0,
            answer_groundedness_score=0.0,
            qdrant_collection_size=0,
            latency_ms=0.0,
        )

    context_chunks = _search_qdrant(req.question, top_k=req.top_k)
    answer = None
    if req.include_answer:
        answer = _generate_answer(req.question, context_chunks)

    latency_ms = (time.perf_counter() - start) * 1000
    QUERY_LATENCY.observe(latency_ms / 1000)

    # Retrieval precision: fraction of returned chunks with score > 0.3
    precision = (
        sum(1 for c in context_chunks if c.get("score", 0) > 0.3) / max(len(context_chunks), 1)
        if context_chunks else 0.0
    )

    # Groundedness proxy: does answer contain keywords from question?
    groundedness = 0.0
    if answer and req.question:
        q_words = set(req.question.lower().split())
        a_words = set(answer.lower().split())
        groundedness = len(q_words & a_words) / max(len(q_words), 1)

    status = "success" if context_chunks else "no_context"
    QUERIES.labels(status=status).inc()

    return QueryResult(
        question=req.question,
        context_chunks=context_chunks,
        answer=answer,
        retrieval_precision_at_5=round(precision, 4),
        answer_groundedness_score=round(groundedness, 4),
        qdrant_collection_size=int(COLLECTION_SIZE._value.get()),
        latency_ms=round(latency_ms, 1),
    )


@app.post("/api/v1/index-runbooks")
def index_runbooks(background_tasks: BackgroundTasks) -> dict:
    """Index all runbook markdown files from RUNBOOK_DIR into Qdrant."""
    background_tasks.add_task(_run_indexing)
    return {
        "status": "indexing_started",
        "runbook_dir": str(RUNBOOK_DIR),
        "collection": COLLECTION_NAME,
        "message": "Indexing running in background — check /health for collection size",
    }


def _run_indexing() -> None:
    """Background task: chunk and embed all runbook files into Qdrant."""
    if not _ensure_collection():
        logger.error("Cannot index: Qdrant unavailable")
        return

    runbook_files = list(RUNBOOK_DIR.glob("**/*.md")) + list(RUNBOOK_DIR.glob("**/*.txt"))
    if not runbook_files:
        logger.warning("No runbook files found in %s", RUNBOOK_DIR)
        return

    total_chunks = 0
    base_id = int(time.time() * 1000) % (2**31)  # Unique base ID per indexing run

    for i, path in enumerate(runbook_files):
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            n = _index_document(str(path.name), content, base_id + i * 1000)
            total_chunks += n
            logger.info("Indexed %s: %d chunks", path.name, n)
        except Exception as exc:
            logger.error("Failed to index %s: %s", path, exc)

    COLLECTION_SIZE.set(total_chunks)
    INDEXING_RUNS.inc()
    logger.info("Indexing complete: %d files, %d chunks → Qdrant collection '%s'",
                len(runbook_files), total_chunks, COLLECTION_NAME)

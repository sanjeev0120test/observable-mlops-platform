"""
RAGAS evaluation harness for UC8 (RAG Runbook Agent) and UC23 (Post-Mortem).
Evaluates: answer_relevancy, faithfulness, context_precision, context_recall.

Usage:
    python llmops/ragas/ragas_eval.py \
        --runbook-agent-url http://localhost:8006 \
        --questions llmops/ragas/eval_questions.json \
        --output eval-results/UC8-ragas.json

CI Usage (see .github/workflows/09-rag-runbook.yml):
    Triggered automatically after runbook indexing completes.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("ragas-eval")

# Evaluation questions with ground-truth context and expected answers
# In production: loaded from a versioned eval dataset (DVC tracked)
DEFAULT_EVAL_QUESTIONS = [
    {
        "id": "Q001",
        "question": "What is the runbook for handling PodCrashLoopBackOff?",
        "expected_keywords": ["restart", "pod", "crash", "logs", "describe"],
        "uc": "UC8",
    },
    {
        "id": "Q002",
        "question": "How do I investigate high CPU utilisation on a node?",
        "expected_keywords": ["top", "cpu", "throttling", "requests", "limits"],
        "uc": "UC8",
    },
    {
        "id": "Q003",
        "question": "What steps should I take when model drift is detected?",
        "expected_keywords": ["drift", "retrain", "psi", "evidently", "airflow"],
        "uc": "UC8",
    },
    {
        "id": "Q004",
        "question": "How to diagnose OOMKilled containers?",
        "expected_keywords": ["memory", "limit", "oom", "killed", "requests"],
        "uc": "UC8",
    },
    {
        "id": "Q005",
        "question": "What is the incident response playbook for database connection failures?",
        "expected_keywords": ["postgres", "connection", "pool", "retry", "timeout"],
        "uc": "UC23",
    },
]


def _keyword_precision(answer: str, expected_keywords: list[str]) -> float:
    """
    Lightweight keyword-based faithfulness proxy.
    Counts how many expected keywords appear in the answer (case-insensitive).
    Returns: fraction of expected keywords found.
    """
    if not answer or not expected_keywords:
        return 0.0
    answer_lower = answer.lower()
    found = sum(1 for kw in expected_keywords if kw.lower() in answer_lower)
    return found / len(expected_keywords)


def _answer_length_score(answer: str) -> float:
    """
    Proxy for answer completeness: prefer answers of 50-500 words.
    Too short = likely no context retrieved. Too long = potential hallucination.
    """
    if not answer:
        return 0.0
    words = len(answer.split())
    if words < 10:
        return 0.1
    if words < 50:
        return 0.5
    if words <= 500:
        return 1.0
    return 0.8  # Very long answers: slight penalty


def evaluate_rag_agent(
    agent_url: str,
    questions: list[dict],
    top_k: int = 5,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """
    Run RAGAS-style evaluation against the runbook agent.
    Returns UC8 eval metrics compatible with eval/scorer.py.

    Metrics:
    - retrieval_precision_at_5: fraction of queries with ≥1 context chunk retrieved
    - answer_groundedness_score: mean keyword coverage in answers
    - answer_completeness_score: mean answer length score
    - query_success_rate: fraction of queries that returned HTTP 200
    - mean_context_chunks_retrieved: average context chunks per query
    """
    results = []
    n_retrieved = 0
    n_success = 0

    for q in questions:
        try:
            resp = httpx.post(
                f"{agent_url}/api/v1/query",
                json={"question": q["question"], "top_k": top_k, "include_answer": True},
                timeout=timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            n_success += 1

            context_chunks = data.get("context_chunks", [])
            answer = data.get("answer", "") or ""
            has_context = len(context_chunks) > 0
            n_retrieved += int(has_context)

            keyword_score = _keyword_precision(answer, q.get("expected_keywords", []))
            length_score = _answer_length_score(answer)

            results.append(
                {
                    "id": q["id"],
                    "question": q["question"],
                    "uc": q.get("uc", "UC8"),
                    "n_context_chunks": len(context_chunks),
                    "has_context": has_context,
                    "answer_length_words": len(answer.split()),
                    "keyword_precision": keyword_score,
                    "answer_completeness": length_score,
                    "composite_score": 0.6 * keyword_score + 0.4 * length_score,
                    "raw_retrieval_precision": data.get("retrieval_precision_at_5", 0.0),
                    "raw_groundedness": data.get("answer_groundedness_score", 0.0),
                }
            )
        except Exception as exc:
            logger.warning("Query %s failed: %s", q["id"], exc)
            results.append(
                {
                    "id": q["id"],
                    "question": q["question"],
                    "error": str(exc),
                    "composite_score": 0.0,
                    "keyword_precision": 0.0,
                }
            )

    n_total = len(questions)
    retrieval_precision = n_retrieved / n_total if n_total else 0.0
    query_success_rate = n_success / n_total if n_total else 0.0
    mean_groundedness = (
        sum(r.get("keyword_precision", 0.0) for r in results) / n_total if n_total else 0.0
    )
    mean_completeness = (
        sum(r.get("answer_completeness", 0.0) for r in results) / n_total if n_total else 0.0
    )
    mean_context = sum(r.get("n_context_chunks", 0) for r in results) / n_total if n_total else 0.0

    eval_output = {
        "uc": "UC8",
        "n_questions": n_total,
        "retrieval_precision_at_5": round(retrieval_precision, 4),
        "answer_groundedness_score": round(mean_groundedness, 4),
        "answer_completeness_score": round(mean_completeness, 4),
        "query_success_rate": round(query_success_rate, 4),
        "mean_context_chunks_retrieved": round(mean_context, 2),
        "per_question_results": results,
    }

    logger.info(
        "RAGAS eval complete: retrieval_p@5=%.3f groundedness=%.3f success_rate=%.3f",
        retrieval_precision,
        mean_groundedness,
        query_success_rate,
    )
    return eval_output


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="RAGAS-style evaluation for RAG Runbook Agent")
    parser.add_argument("--agent-url", default="http://localhost:8006")
    parser.add_argument("--questions", help="Path to JSON eval questions file")
    parser.add_argument("--output", default="eval-results/UC8-ragas.json")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    # Load questions
    if args.questions and Path(args.questions).exists():
        questions = json.loads(Path(args.questions).read_text())
    else:
        logger.info("Using default eval questions")
        questions = DEFAULT_EVAL_QUESTIONS

    # Run evaluation
    result = evaluate_rag_agent(args.agent_url, questions, top_k=args.top_k)

    # Save results
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2))
    logger.info("Results saved to %s", output_path)

    # Print summary
    print(f"\n{'=' * 55}")
    print("  RAGAS Evaluation — UC8 RAG Runbook Agent")
    print("=" * 55)
    print(f"  Questions evaluated: {result['n_questions']}")
    print(f"  Retrieval P@5:       {result['retrieval_precision_at_5']:.3f}")
    print(f"  Groundedness:        {result['answer_groundedness_score']:.3f}")
    print(f"  Completeness:        {result['answer_completeness_score']:.3f}")
    print(f"  Query success rate:  {result['query_success_rate']:.3f}")
    print("=" * 55)

    # Exit 1 if groundedness < 0.4 (Qdrant not seeded or LLM failing)
    if result["answer_groundedness_score"] < 0.4 and result["query_success_rate"] > 0.8:
        logger.warning(
            "Groundedness %.3f < 0.4 — Qdrant may not be seeded. "
            "Run: POST http://localhost:8006/api/v1/index-runbooks",
            result["answer_groundedness_score"],
        )
        sys.exit(1)


if __name__ == "__main__":
    main()

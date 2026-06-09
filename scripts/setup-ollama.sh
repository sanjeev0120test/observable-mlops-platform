#!/usr/bin/env bash
# Pull TinyLlama 1.1B into running Ollama container.
# Called by workflows that use the RAG agent (UC8, UC23).
# TinyLlama fits in ~700 MB RAM — safe for GitHub Actions 7 GB limit.

set -euo pipefail

OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
MODEL="${OLLAMA_MODEL:-tinyllama}"
MAX_WAIT=120

echo "[setup-ollama] Waiting for Ollama to be ready at ${OLLAMA_URL} ..."
for i in $(seq 1 $MAX_WAIT); do
    if curl -sf "${OLLAMA_URL}/api/tags" >/dev/null 2>&1; then
        echo "[setup-ollama] Ollama is ready."
        break
    fi
    sleep 1
    if [ "$i" -eq "$MAX_WAIT" ]; then
        echo "[setup-ollama] Ollama did not become ready in ${MAX_WAIT}s" >&2
        exit 1
    fi
done

echo "[setup-ollama] Pulling model: ${MODEL} ..."
curl -s -X POST "${OLLAMA_URL}/api/pull" \
    -H "Content-Type: application/json" \
    -d "{\"name\": \"${MODEL}\"}" | tail -1

echo "[setup-ollama] Verifying model is available ..."
MODELS=$(curl -s "${OLLAMA_URL}/api/tags" | python3 -c "import json,sys; models=[m['name'] for m in json.load(sys.stdin)['models']]; print(','.join(models))")
echo "[setup-ollama] Available models: ${MODELS}"

if echo "$MODELS" | grep -q "$MODEL"; then
    echo "[setup-ollama] Model ${MODEL} ready."
else
    echo "[setup-ollama] Model ${MODEL} not found after pull." >&2
    exit 1
fi

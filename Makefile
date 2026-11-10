.PHONY: help install dev down test test-unit test-opa test-ci test-self-healing install-opa \
        lint format type-check pre-commit generate-data seed-qdrant trust-demo trust-score ci-local clean \
        logs ps compose-config kind-up kind-down network

SHELL := /bin/bash
# uv manages Python 3.14 and the locked environment (uv.lock); `make install` once, then any target.
PYTHON := uv run --frozen python
OPA_VERSION := v1.22.2
COMPOSE_DIR := infra/docker-compose
# Single project: services.yml depends_on services defined in the core and observability files.
COMPOSE := docker compose -p mlops-platform --env-file .env \
	-f $(COMPOSE_DIR)/docker-compose.mlops-core.yml \
	-f $(COMPOSE_DIR)/docker-compose.observability.yml \
	-f $(COMPOSE_DIR)/docker-compose.services.yml

# â”€â”€â”€ Help â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
help: ## Show this help (default target)
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-25s\033[0m %s\n", $$1, $$2}'

# â”€â”€â”€ Local Development â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
install: ## Create .venv with the dev toolchain (lint + test groups) from uv.lock
	uv sync --frozen
	uv run --frozen pre-commit install

dev: .env ## Start all services locally (requires Docker + .env)
	@echo "Creating platform-net if it doesn't exist..."
	docker network create platform-net 2>/dev/null || true
	$(COMPOSE) up -d --build
	@echo ""
	@echo "Services starting. Check status with: make ps"
	@echo "Grafana:     http://localhost:3000"
	@echo "MLflow:      http://localhost:5000"
	@echo "Drift Mon:   http://localhost:8002/docs"
	@echo "Self Heal:   http://localhost:8005/docs"
	@echo "OPA:         http://localhost:8181"
	@echo "Trust Score: http://localhost:8008/docs"

down: ## Stop all services
	$(COMPOSE) down

ps: ## Show running platform services
	$(COMPOSE) ps

logs: ## Tail logs from all services (Ctrl-C to stop)
	$(COMPOSE) logs -f

compose-config: .env ## Validate the merged docker-compose project
	$(COMPOSE) config -q && echo "compose config OK"

.env: ## Create .env from .env.example if it doesn't exist
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo ".env created from .env.example â€” update credentials before use"; \
	fi

# â”€â”€â”€ Testing â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
test: test-unit test-opa ## Run all tests (unit + OPA policy)

test-unit: ## Run Python unit tests (parallel)
	$(PYTHON) -m pytest tests/unit/ -n auto --dist loadfile -q

test-self-healing: ## Run self-healing unit tests specifically
	$(PYTHON) -m pytest tests/unit/test_self_healing.py -v --tb=long

test-opa: ## Run OPA Rego policy unit tests
	@command -v opa >/dev/null 2>&1 || { echo "OPA not installed. Run: make install-opa"; exit 1; }
	opa test aiops/policies/opa/ -v --ignore "*.gitkeep"

test-ci: ## Run tests exactly as the ci workflow does (test group only)
	UV_PROJECT_ENVIRONMENT=.venv-ci uv sync --frozen --no-default-groups --group test
	.venv-ci/bin/python -m pytest tests/unit -n auto --dist loadfile -q -p no:cacheprovider

install-opa: ## Install OPA binary (Linux/macOS)
	@OS=$$(uname -s | tr '[:upper:]' '[:lower:]'); \
	ARCH=$$(uname -m | sed 's/x86_64/amd64/'); \
	curl -fsSL -o /usr/local/bin/opa \
		"https://github.com/open-policy-agent/opa/releases/download/$(OPA_VERSION)/opa_$${OS}_$${ARCH}_static"; \
	chmod 755 /usr/local/bin/opa; \
	echo "OPA $$(opa version) installed"

# â”€â”€â”€ Code Quality â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
lint: ## Run ruff lint + format check
	uv run --frozen ruff check .
	uv run --frozen ruff format --check .

format: ## Auto-fix lint and format code with ruff
	uv run --frozen ruff check . --fix
	uv run --frozen ruff format .

type-check: ## Run mypy type checks
	uvx mypy eval/ services/ --ignore-missing-imports

pre-commit: ## Run all pre-commit hooks
	uv run --frozen pre-commit run --all-files

# â”€â”€â”€ Data & Seeds â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
generate-data: ## Generate all synthetic datasets
	$(PYTHON) data/synthetic/generate_pod_metrics.py --hours 24 --output data/synthetic/pod_metrics.parquet
	$(PYTHON) data/synthetic/generate_container_logs.py --hours 6 --output data/synthetic/container_logs.ndjson
	$(PYTHON) data/synthetic/generate_cost_data.py --days 30 --output data/synthetic/cost_data.parquet
	$(PYTHON) data/synthetic/generate_alerts.py --hours 24 --output data/synthetic/alerts.parquet
	$(PYTHON) data/synthetic/generate_http_traffic.py --hours 24 --output data/synthetic/http_traffic.parquet
	@echo "All synthetic datasets generated"

trust-demo: ## Score 3 model versions, verify + tamper-test the ledger, run OPA gate (needs opa)
	$(PYTHON) scripts/trust_score_demo.py --out /tmp/trust-results
	@echo "Reports + attestation in /tmp/trust-results"

trust-score: ## Score a model against the running service: make trust-score MODEL=name VERSION=3 SIGNALS='{"accuracy":0.9}'
	curl -fsS -X POST http://localhost:8008/api/v1/score -H 'content-type: application/json' \
		-d '{"model_name":"$(MODEL)","model_version":"$(VERSION)","signals":$(SIGNALS)}' | $(PYTHON) -m json.tool

seed-qdrant: ## Seed Qdrant with runbook documents (requires `make dev`)
	curl -fsS -X POST http://localhost:8006/api/v1/index-runbooks
	@echo ""
	@echo "Runbook indexing started in runbook-agent (background task)"

# â”€â”€â”€ CI Simulation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
ci-local: lint test generate-data ## Run full CI checks locally before push
	@echo ""
	@echo "Local CI checks passed â€” safe to push"

# â”€â”€â”€ Cleanup â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
clean: ## Remove Python caches and build artifacts
	find . -type d -name "__pycache__" -not -path "./.git/*" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -not -path "./.git/*" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@echo "Clean complete"

# â”€â”€â”€ Infrastructure â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
KIND_PROFILE ?= policy

kind-up: ## Create local Kind cluster (KIND_PROFILE=policy|serving|pipelines) and deploy base manifests
	bash scripts/setup-kind.sh $(KIND_PROFILE)
	kubectl apply -k infra/kubernetes/base/self-healing

kind-down: ## Delete local Kind cluster
	kind delete cluster --name platform-$(KIND_PROFILE)

network: ## Create the platform-net Docker network (idempotent)
	docker network create platform-net 2>/dev/null || echo "platform-net already exists"

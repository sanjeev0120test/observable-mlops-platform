.PHONY: help dev down test test-unit test-opa lint format type-check \
        generate-data seed-qdrant ci-local clean logs ps

SHELL := /bin/bash
PYTHON := python3
PIP := pip
COMPOSE_CORE := infra/docker-compose/docker-compose.mlops-core.yml
COMPOSE_SERVICES := infra/docker-compose/docker-compose.services.yml

# ─── Help ─────────────────────────────────────────────────────────────────────
help: ## Show this help (default target)
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-25s\033[0m %s\n", $$1, $$2}'

# ─── Local Development ────────────────────────────────────────────────────────
dev: .env ## Start all services locally (requires Docker + .env)
	@echo "Creating platform-net if it doesn't exist..."
	docker network create platform-net 2>/dev/null || true
	docker compose -f $(COMPOSE_CORE) up -d
	docker compose -f $(COMPOSE_SERVICES) up -d
	@echo ""
	@echo "Services starting. Check status with: make ps"
	@echo "Grafana:     http://localhost:3000"
	@echo "MLflow:      http://localhost:5000"
	@echo "Drift Mon:   http://localhost:8002/docs"
	@echo "Self Heal:   http://localhost:8005/docs"
	@echo "OPA:         http://localhost:8181"

down: ## Stop all services
	docker compose -f $(COMPOSE_SERVICES) down
	docker compose -f $(COMPOSE_CORE) down

ps: ## Show running platform services
	docker compose -f $(COMPOSE_CORE) ps
	docker compose -f $(COMPOSE_SERVICES) ps

logs: ## Tail logs from all services (Ctrl-C to stop)
	docker compose -f $(COMPOSE_SERVICES) logs -f

.env: ## Create .env from .env.example if it doesn't exist
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo ".env created from .env.example — update credentials before use"; \
	fi

# ─── Testing ──────────────────────────────────────────────────────────────────
test: test-unit test-opa ## Run all tests (unit + OPA policy)

test-unit: ## Run Python unit tests
	$(PYTHON) -m pytest tests/unit/ -v --tb=short -q

test-self-healing: ## Run self-healing unit tests specifically
	$(PYTHON) -m pytest tests/unit/test_self_healing.py -v --tb=long

test-opa: ## Run OPA Rego policy unit tests
	@command -v opa >/dev/null 2>&1 || { echo "OPA not installed. Run: make install-opa"; exit 1; }
	opa test aiops/policies/opa/ -v --ignore "*.gitkeep"

test-ci: ## Run tests as CI would (install deps first)
	$(PIP) install pytest numpy pandas scipy scikit-learn httpx fastapi starlette pydantic prometheus-client --quiet
	$(PYTHON) -m pytest tests/unit/ -v --tb=short

install-opa: ## Install OPA binary (Linux/macOS)
	@OS=$$(uname -s | tr '[:upper:]' '[:lower:]'); \
	ARCH=$$(uname -m | sed 's/x86_64/amd64/'); \
	curl -L -o /usr/local/bin/opa \
		"https://openpolicyagent.org/downloads/v0.65.0/opa_$${OS}_$${ARCH}_static"; \
	chmod 755 /usr/local/bin/opa; \
	echo "OPA $$(opa version) installed"

# ─── Code Quality ─────────────────────────────────────────────────────────────
lint: ## Run ruff + black check
	ruff check . --output-format=github
	black --check . --diff

format: ## Auto-format code (ruff fix + black)
	ruff check . --fix
	black .

type-check: ## Run mypy type checks
	mypy eval/ services/ --ignore-missing-imports

pre-commit: ## Run all pre-commit hooks
	pre-commit run --all-files

# ─── Data & Seeds ─────────────────────────────────────────────────────────────
generate-data: ## Generate all synthetic datasets
	$(PYTHON) data/synthetic/generate_pod_metrics.py --hours 24 --output data/synthetic/pod_metrics.parquet
	$(PYTHON) data/synthetic/generate_container_logs.py --hours 6 --output data/synthetic/container_logs.ndjson
	$(PYTHON) data/synthetic/generate_cost_data.py --days 30 --output data/synthetic/cost_data.parquet
	$(PYTHON) data/synthetic/generate_alerts.py --hours 24 --output data/synthetic/alerts.parquet
	$(PYTHON) data/synthetic/generate_http_traffic.py --hours 24 --output data/synthetic/http_traffic.parquet
	@echo "All synthetic datasets generated"

seed-qdrant: ## Seed Qdrant with runbook documents (requires running Qdrant)
	$(PYTHON) scripts/seed_qdrant.py
	@echo "Qdrant runbook collection seeded"

# ─── CI Simulation ────────────────────────────────────────────────────────────
ci-local: lint test generate-data ## Run full CI checks locally before push
	@echo ""
	@echo "Local CI checks passed — safe to push"

# ─── Cleanup ──────────────────────────────────────────────────────────────────
clean: ## Remove Python caches and build artifacts
	find . -type d -name "__pycache__" -not -path "./.git/*" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -not -path "./.git/*" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@echo "Clean complete"

# ─── Infrastructure ───────────────────────────────────────────────────────────
kind-up: ## Create local Kind cluster with platform stack
	kind create cluster --config infra/kind/kind-cluster.yaml
	kubectl apply -f infra/kubernetes/

kind-down: ## Delete local Kind cluster
	kind delete cluster --name mlops-platform

network: ## Create the platform-net Docker network (idempotent)
	docker network create platform-net 2>/dev/null || echo "platform-net already exists"

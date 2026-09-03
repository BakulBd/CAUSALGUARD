# CausalGuard — developer & operator tasks
.DEFAULT_GOAL := help
SHELL := /usr/bin/env bash
VENV ?= .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
COMPOSE ?= docker compose

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | sort | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ---- local python -------------------------------------------------------
.PHONY: setup
setup: ## Create venv and install the project with dev + postgres extras
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip setuptools wheel
	$(PIP) install -e ".[dev,postgres]"
	@echo "done — activate with: source $(VENV)/bin/activate"

.PHONY: dev
dev: ## Run the API with autoreload (structured console logs)
	CAUSALGUARD_LOG_FORMAT=console CAUSALGUARD_ENVIRONMENT=development \
	  $(VENV)/bin/uvicorn backend.api.main:app --reload --host 0.0.0.0 --port 8000

.PHONY: serve
serve: ## Run the API under gunicorn (production shape)
	$(VENV)/bin/gunicorn backend.api.main:app -c deploy/gunicorn.conf.py

.PHONY: lint
lint: ## ruff check + format check
	$(VENV)/bin/ruff check backend tests
	$(VENV)/bin/ruff format --check backend tests

.PHONY: fmt
fmt: ## Auto-format + fix
	$(VENV)/bin/ruff check --fix backend tests
	$(VENV)/bin/ruff format backend tests

.PHONY: type
type: ## mypy
	$(VENV)/bin/mypy backend

.PHONY: test
test: ## Run the test suite with coverage
	PYTHONPATH=. $(VENV)/bin/pytest --cov=backend --cov-report=term-missing --cov-report=xml

.PHONY: check
check: lint type test ## lint + type + test

.PHONY: seed
seed: ## Drive a scenario and run one investigation (SCENARIO=pg-table-bloat)
	PYTHONPATH=. $(PY) -m backend.cli seed --scenario $(or $(SCENARIO),pg-table-bloat)

.PHONY: config
config: ## Print the redacted effective configuration
	PYTHONPATH=. $(PY) -m backend.cli config

# ---- frontend --------------------------------------------------------
.PHONY: frontend-build
frontend-build: ## Build the SPA
	cd frontend && npm install && npm run build

# ---- docker / compose -----------------------------------------------
.PHONY: env
env: ## Materialise deploy/env/*.env from the .example files
	@for f in backend postgres postgres-exporter; do \
	  test -f deploy/env/$$f.env || (cp deploy/env/$$f.env.example deploy/env/$$f.env && echo "created deploy/env/$$f.env"); \
	done

.PHONY: build
build: ## Build all container images
	$(COMPOSE) build

.PHONY: up
up: env ## Start the hardened stack (with dev overrides)
	$(COMPOSE) up -d --build
	@echo "UI: http://localhost:8080   API: http://localhost:8000/docs"

.PHONY: down
down: ## Stop the stack
	$(COMPOSE) down

.PHONY: logs
logs: ## Tail stack logs
	$(COMPOSE) logs -f --tail=100

.PHONY: prod-up
prod-up: env certs ## Start the production profile (TLS edge proxy)
	$(COMPOSE) -f docker-compose.yml -f docker-compose.prod.yml up -d --build

.PHONY: prod-down
prod-down: ## Stop the production profile
	$(COMPOSE) -f docker-compose.yml -f docker-compose.prod.yml down

.PHONY: certs
certs: ## Generate self-signed TLS certs for the edge proxy (dev only)
	./scripts/gen_self_signed_certs.sh

.PHONY: smoke
smoke: ## Curl the running stack's health + a full investigation
	./scripts/smoke_test.sh

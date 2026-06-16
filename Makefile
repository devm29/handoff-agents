SHELL := /bin/bash
BACKEND := backend
FRONTEND := frontend
VENV := $(BACKEND)/.venv
PY := $(VENV)/bin/python
HANDOFF := $(VENV)/bin/handoff
PYTHON ?= python3.12

.PHONY: help setup db db-stop db-init seed dev api worker mcp web test test-backend test-frontend \
        lint typecheck eval demo-crash build up down clean

help:
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "} {printf "  %-14s %s\n", $$1, $$2}'

setup: ## Create the Python venv and install backend + frontend dependencies
	test -d $(VENV) || $(PYTHON) -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e "$(BACKEND)[dev]"
	cd $(FRONTEND) && pnpm install

db: ## Start a local PostgreSQL on :5504 (data in .data/, no Docker)
	./scripts/local-postgres.sh start

db-stop: ## Stop the local PostgreSQL
	./scripts/local-postgres.sh stop

db-init: ## Create tables and LangGraph checkpoint tables
	cd $(BACKEND) && .venv/bin/handoff db init

seed: ## Load demo runs, approvals, a fork and an eval report (wipes existing runs)
	cd $(BACKEND) && .venv/bin/handoff seed --reset

dev: ## Run API (:8104), worker and web (:3104) together
	./scripts/dev.sh

api: ## Run the API on :8104
	cd $(BACKEND) && .venv/bin/handoff api

worker: ## Run a worker
	cd $(BACKEND) && .venv/bin/handoff worker

mcp: ## Serve the MCP tools over Streamable HTTP
	cd $(BACKEND) && .venv/bin/handoff mcp-tools --transport http

web: ## Run the Next.js dev server on :3104
	cd $(FRONTEND) && pnpm dev

test: test-backend test-frontend ## Run all tests

test-backend:
	cd $(BACKEND) && .venv/bin/pytest -q

test-frontend:
	cd $(FRONTEND) && pnpm test

lint: ## Ruff + ESLint
	cd $(BACKEND) && .venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests
	cd $(FRONTEND) && pnpm lint

typecheck: ## mypy --strict + tsc
	cd $(BACKEND) && .venv/bin/mypy
	cd $(FRONTEND) && pnpm typecheck

eval: ## Run trajectory evals offline and store the report
	cd $(BACKEND) && .venv/bin/handoff eval run

demo-crash: ## SIGKILL a worker mid-run and watch it resume from the checkpoint
	cd $(BACKEND) && .venv/bin/handoff demo crash

build: ## Production build of the web app
	cd $(FRONTEND) && pnpm build

up: ## Start the full stack with Docker Compose
	docker compose up --build

down:
	docker compose down

clean:
	rm -rf $(FRONTEND)/.next $(BACKEND)/.mypy_cache $(BACKEND)/.ruff_cache $(BACKEND)/.pytest_cache

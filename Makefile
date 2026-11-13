SHELL := /bin/bash
.DEFAULT_GOAL := help

ifneq (,$(wildcard ./.env))
  include .env
  export
endif

.PHONY: help install seed playground backend frontend warmup test lint

help: ## Show available commands
	@awk 'BEGIN {FS = ":.*##"; printf "\n\033[1mknowledgestudio-devfest2026\033[0m\n\n"} /^[a-zA-Z0-9_-]+:.*?##/ { printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2 } END {print ""}' $(MAKEFILE_LIST)

install: ## Install Python (uv) and Frontend (npm) dependencies
	cd backend/agent && uv sync --frozen
	cd backend && uv sync --frozen
	cd frontend && npm ci

seed: ## Seed BigQuery tables + Knowledge Studio Context Set, Policies & Glossary
	@if [ -z "$${GCP_PROJECT_ID:-}" ] || [ "$${GCP_PROJECT_ID}" = "<YOUR_GCP_PROJECT_ID>" ]; then \
	  echo "Error: Set GCP_PROJECT_ID in .env (or pass GCP_PROJECT_ID=my-project make seed)"; exit 1; fi
	GCP_PROJECT_ID="$(GCP_PROJECT_ID)" GOOGLE_CLOUD_PROJECT="$(GCP_PROJECT_ID)" \
	  uv run --directory backend/agent python ../../scripts/seed_demo.py

playground: ## Start the Google ADK Web Playground on http://127.0.0.1:8081
	@if [ -z "$${GCP_PROJECT_ID:-}" ] || [ "$${GCP_PROJECT_ID}" = "<YOUR_GCP_PROJECT_ID>" ]; then \
	  echo "Error: Set GCP_PROJECT_ID in .env first"; exit 1; fi
	cd backend/agent && \
	  GOOGLE_GENAI_USE_VERTEXAI=1 \
	  GOOGLE_CLOUD_PROJECT="$(GCP_PROJECT_ID)" \
	  GCP_PROJECT_ID="$(GCP_PROJECT_ID)" \
	  GOOGLE_CLOUD_LOCATION="$${GOOGLE_CLOUD_LOCATION:-global}" \
	  GEMINI_MODEL="$${GEMINI_MODEL:-gemini-4-hydrogen}" \
	  uv run adk web . --host 127.0.0.1 --port 8081 --reload_agents

backend: ## Start the FastAPI SSE backend (+ /dev-ui/) on http://127.0.0.1:8080
	@if [ -z "$${GCP_PROJECT_ID:-}" ] || [ "$${GCP_PROJECT_ID}" = "<YOUR_GCP_PROJECT_ID>" ]; then \
	  echo "Error: Set GCP_PROJECT_ID in .env first"; exit 1; fi
	cd backend && \
	  ENABLE_ADK_WEB_UI=true \
	  GOOGLE_GENAI_USE_VERTEXAI=1 \
	  GOOGLE_CLOUD_PROJECT="$(GCP_PROJECT_ID)" \
	  GCP_PROJECT_ID="$(GCP_PROJECT_ID)" \
	  GOOGLE_CLOUD_LOCATION="$${GOOGLE_CLOUD_LOCATION:-global}" \
	  GEMINI_MODEL="$${GEMINI_MODEL:-gemini-4-hydrogen}" \
	  uv run uvicorn api.main:app --host 127.0.0.1 --port "$${PORT:-8080}"

frontend: ## Start the Next.js side-by-side Executive Folio UI on http://localhost:3000
	cd frontend && BACKEND_API_URL="$${BACKEND_API_URL:-http://127.0.0.1:8080}" npm run dev

warmup: ## Pre-warm OAuth, Knowledge Catalog MCP, and BigQuery caches on :8081
	python3 scripts/warmup_demo.py --url "$${URL:-http://127.0.0.1:8081}"

test: ## Run all unit tests and TypeScript typechecks offline
	cd backend/agent && GCP_PROJECT_ID="$${GCP_PROJECT_ID:-example-gcp-project}" uv run --no-sync pytest -q
	cd backend && GCP_PROJECT_ID="$${GCP_PROJECT_ID:-example-gcp-project}" uv run --no-sync pytest -q
	cd frontend && npm run typecheck

lint: ## Run Ruff, mypy, and Next.js production build check
	cd backend/agent && uv run --no-sync ruff check . && uv run --no-sync mypy app
	cd backend && uv run --no-sync ruff check . && uv run --no-sync mypy src
	cd frontend && npm run build

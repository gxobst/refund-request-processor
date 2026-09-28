.PHONY: help install setup dev backend frontend seed test test-backend test-frontend build clean

.DEFAULT_GOAL := help

help: ## Show this help message
	@echo "AI Refund Request Processor - Available Make Targets:"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: install seed ## Install dependencies and seed mock DynamoDB orders

install: ## Install backend and frontend dependencies
	cd backend && uv sync
	cd frontend && npm install

backend: ## Start FastAPI backend server with auto-reload (http://127.0.0.1:8000)
	cd backend && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

frontend: ## Start Vite frontend development server (http://127.0.0.1:5173)
	cd frontend && npm run dev

dev: ## Instructions to run both backend and frontend concurrently
	@echo "Starting development environment:"
	@echo "  Option 1 (PowerShell): .\\start.ps1"
	@echo "  Option 2 (Terminals):  run 'make backend' in Terminal 1 and 'make frontend' in Terminal 2"

stop: ## Stop running services (PowerShell: .\\start.ps1 -Mode stop)
	@pwsh -File .\start.ps1 -Mode stop

seed: ## Seed mock orders in DynamoDB table
	cd backend && uv run python -m app.db.seed

test: test-backend test-frontend ## Run all backend and frontend tests

test-backend: ## Run backend unit and integration tests (pytest)
	cd backend && uv run pytest

test-frontend: ## Run frontend unit and component tests (vitest)
	cd frontend && npm run test -- --run

build: ## Build frontend production bundle into frontend/dist
	cd frontend && npm run build

clean: ## Clean cache directories and build artifacts
	rm -rf frontend/dist frontend/node_modules/.vite
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true

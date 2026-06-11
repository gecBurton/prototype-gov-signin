.DEFAULT_GOAL := help

DEV_ENV := DEBUG=true SECRET_KEY=insecure-dev-key

.PHONY: help install test run migrate makemigrations demo shell up down db integration-test install-integration format format-check

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-16s %s\n", $$1, $$2}'

install: ## Install dependencies
	uv sync

test: ## Run tests
	uv run pytest tests/ -v --cov=iam --cov-report=term-missing

format: ## Run linter
	uv run ruff check . --select I --fix && uv run ruff format .

format-check: ## Check formatting without making changes (used in CI)
	uv run ruff check . --select I && uv run ruff format --check .

run: ## Start the development server
	cd iam && $(DEV_ENV) uv run python manage.py runserver

migrate: ## Apply database migrations
	cd iam && $(DEV_ENV) uv run python manage.py migrate

makemigrations: ## Create new migrations
	cd iam && $(DEV_ENV) uv run python manage.py makemigrations

demo: ## Run the OIDC flow demo script
	cd iam && $(DEV_ENV) uv run python demo.py

shell: ## Open a Django shell
	cd iam && $(DEV_ENV) uv run python manage.py shell

up: ## Start all services (postgres + iam)
	docker compose up --build

down: ## Stop all services
	docker compose down

db: ## Start only the database
	docker compose up db -d

install-integration: ## Install integration test dependencies and browsers
	uv sync --group integration && uv run playwright install chromium

integration-test: ## Run integration tests (requires: make up)
	uv run pytest integration_tests/ -v

.DEFAULT_GOAL := help

.PHONY: help install test run migrate makemigrations demo shell up down db integration-test install-integration

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-16s %s\n", $$1, $$2}'

install: ## Install dependencies
	cd iam && uv sync

test: ## Run tests
	cd iam && uv run pytest

format: ## Run linter
	cd iam && uv run ruff check . --select I --fix && uv run ruff format .

run: ## Start the development server
	cd iam && uv run python manage.py runserver

migrate: ## Apply database migrations
	cd iam && uv run python manage.py migrate

makemigrations: ## Create new migrations
	cd iam && uv run python manage.py makemigrations

demo: ## Run the OIDC flow demo script
	cd iam && uv run python demo.py

shell: ## Open a Django shell
	cd iam && uv run python manage.py shell

up: ## Start all services (postgres + iam)
	docker compose up --build

down: ## Stop all services
	docker compose down

db: ## Start only the database
	docker compose up db -d

install-integration: ## Install integration test dependencies and browsers
	cd integration_tests && uv sync && uv run playwright install chromium

integration-test: ## Run integration tests (requires: make up)
	cd integration_tests && uv run pytest -v

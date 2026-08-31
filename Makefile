# GharOS — top-level developer entry points.
# Owned by the CTO (root config). See PHASES.md §4 for the full repo structure.

.PHONY: help emulators dev-backend dev-frontend test-backend test-frontend lint-backend lint-frontend seed-demo deploy-backend deploy-frontend teardown

help:
	@echo "GharOS developer commands:"
	@echo "  make emulators        Start Firestore + Pub/Sub emulators (scripts/emulators.sh)"
	@echo "  make dev-backend      Run backend/app with uvicorn against emulators"
	@echo "  make dev-frontend     Run the Next.js dev server"
	@echo "  make test-backend     Run backend test suite (pytest)"
	@echo "  make test-frontend    Run frontend test suite (vitest)"
	@echo "  make lint-backend     ruff check + mypy --strict"
	@echo "  make lint-frontend    eslint + tsc --noEmit"
	@echo "  make seed-demo        Load the demo household into the emulator"
	@echo "  make deploy-backend   Cloud Run source deploy — gharos-api"
	@echo "  make deploy-frontend  Cloud Run source deploy — gharos-web"
	@echo "  make teardown         Scale all Cloud Run services to zero"

emulators:
	./scripts/emulators.sh

# `--env-file .env` so backend/.env (emulator hosts, project id, OAuth
# config) reaches the process: `uv run` does NOT load .env on its own, and
# the google client libs read FIRESTORE_EMULATOR_HOST / PUBSUB_EMULATOR_HOST
# from the OS environment. Without it, local dev silently hits real Firestore.
dev-backend:
	cd backend && uv run --env-file .env uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd frontend && pnpm dev

test-backend:
	cd backend && uv run --env-file .env pytest --cov=app --cov-report=term-missing

test-frontend:
	cd frontend && pnpm test

lint-backend:
	cd backend && uv run ruff check . && uv run mypy --strict app

lint-frontend:
	cd frontend && pnpm lint && pnpm exec tsc --noEmit

seed-demo:
	./scripts/seed_demo.sh

deploy-backend:
	./infra/deploy_backend.sh

deploy-frontend:
	./infra/deploy_frontend.sh

teardown:
	./infra/teardown.sh

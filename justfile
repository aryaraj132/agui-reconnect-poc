# Default recipe
default:
    @just --list

# Install all dependencies (backend + frontend)
prepare:
    uv sync
    cd frontend && npm install

# Install all dependencies (backend + frontend-next)
prepare-next:
    uv sync
    cd frontend-next && npm install

# Install backend dependencies only
install:
    uv sync

# Run Redis in podman (port 6379)
redis:
    podman run --rm --name redis-reconnect -p 6379:6379 docker.io/redis:7-alpine

# Run the FastAPI backend server (requires ANTHROPIC_API_KEY env var)
backend:
    uv run python -m stream_reconnection_demo.main

# Run the React + webpack frontend dev server
frontend:
    cd frontend && npm run dev

# Run the Next.js + CopilotKit frontend (reference version)
frontend-next:
    cd frontend-next && npm run dev

# Run backend (alias)
run: backend

# Run linter
lint:
    uv run ruff check

# Run linter with auto-fix
lint-fix:
    uv run ruff check --fix

# Check formatting
format-check:
    uv run ruff format --check

# Fix formatting
format:
    uv run ruff format

# Run all checks (lint + format)
check: lint format-check

# Fix all issues (lint + format)
fix: lint-fix format

# Run tests
test:
    uv run pytest tests/
dev:
    just backend & just frontend-next & wait

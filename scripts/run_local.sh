#!/usr/bin/env bash
# Runs the API on your machine against the local PostgreSQL from docker-compose.
# Usage: scripts/run_local.sh [port]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${1:-8000}"
export PLATFORM_ENV=local
# The identity login until S0a (c) moves the app to app_rw (LLD-0 §4.1).
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://svc_identity:local-only@localhost:5432/saas}"
export PYTHONPATH="$ROOT/app/src:$ROOT/libs/platform_common"
exec "${PYTHON:-python3}" -m uvicorn app.api:app --reload --app-dir "$ROOT/app/src" --port "$PORT"

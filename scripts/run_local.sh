#!/usr/bin/env bash
# Runs the API on your machine against the local PostgreSQL from docker-compose.
# Usage: scripts/run_local.sh [port]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${1:-8000}"
export PLATFORM_ENV=local
# The app's one login (LLD-0 §4.1); migrator.local gives it this password.
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://app_rw:local-only@localhost:5432/saas}"
export PYTHONPATH="$ROOT/app/src:$ROOT/libs/platform_common"
exec "${PYTHON:-python3}" -m uvicorn app.api:app --reload --app-dir "$ROOT/app/src" --port "$PORT"

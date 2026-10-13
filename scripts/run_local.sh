#!/usr/bin/env bash
# Runs one service on your machine against the local PostgreSQL from docker-compose.
# Usage: scripts/run_local.sh identity [port]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SVC="${1:?service name, e.g. identity}"
PORT="${2:-8000}"
export PLATFORM_ENV=local
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://svc_${SVC}:local-only@localhost:5432/saas}"
export PYTHONPATH="$ROOT/services/$SVC:$ROOT/libs/platform_common"
cd "$ROOT/services/$SVC"
exec "${PYTHON:-python3}" -m uvicorn app.main:app --reload --port "$PORT"

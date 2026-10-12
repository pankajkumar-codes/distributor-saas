#!/usr/bin/env bash
# Builds build/<service>.zip for the arm64 Python 3.12 Lambda runtime.
# Usage: scripts/build_lambda.sh identity   (or: all)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVICES=(identity commerce imports reports documents migrator)

build() {
  local svc="$1" src="$ROOT/services/$1" out="$ROOT/build/$1"
  rm -rf "$out" "$out.zip"
  mkdir -p "$out"
  python3 -m pip install --quiet --platform manylinux2014_aarch64 --implementation cp \
    --python-version 3.12 --only-binary=:all: -r "$src/requirements.txt" -t "$out"
  if [ "$svc" = migrator ]; then
    cp -r "$src/migrator" "$out/"
    for s in "${SERVICES[@]}"; do
      if [ -d "$ROOT/services/$s/migrations" ]; then
        mkdir -p "$out/migrations/$s"
        cp "$ROOT/services/$s/migrations/"*.sql "$out/migrations/$s/" 2>/dev/null || true
      fi
    done
  else
    cp -r "$src/app" "$out/"
    cp -r "$ROOT/libs/platform_common/platform_common" "$out/"
  fi
  find "$out" -name '__pycache__' -prune -exec rm -rf {} +
  (cd "$out" && python3 -c "import shutil; shutil.make_archive('$out', 'zip', '.')")
  echo "built build/$svc.zip"
}

if [ "${1:-all}" = all ]; then
  for s in "${SERVICES[@]}"; do build "$s"; done
else
  build "$1"
fi

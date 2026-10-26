#!/usr/bin/env bash
# Builds build/<name>.zip for the arm64 Python 3.12 Lambda runtime (LLD-0 §8).
#   app.zip       the API and worker Lambdas (one artefact, two handlers:
#                 app.api.handler and app.worker.sqs_handler)
#   migrator.zip  migrator.handler.handler, with every module's migrations,
#                 platform_common's (as module "platform") and refdata/ (LLD-0 §6)
# Usage: scripts/build_lambda.sh app   (or: migrator, all)
# Terraform still names the old per-service zips until Staff 2's S0b change.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGETS=(app migrator)

deps() {
  python3 -m pip install --quiet --platform manylinux2014_aarch64 --implementation cp \
    --python-version 3.12 --only-binary=:all: -t "$1" "${@:2}"
}

build() {
  local name="$1" out="$ROOT/build/$1"
  rm -rf "$out" "$out.zip"
  mkdir -p "$out"
  if [ "$name" = migrator ]; then
    deps "$out" -r "$ROOT/migrator/requirements.txt"
    cp -r "$ROOT/migrator/migrator" "$out/"
    for d in "$ROOT"/app/src/app/modules/*/migrations; do
      mkdir -p "$out/migrations/$(basename "$(dirname "$d")")"
      cp "$d"/*.sql "$out/migrations/$(basename "$(dirname "$d")")/"
    done
    mkdir -p "$out/migrations/platform"
    cp "$ROOT"/libs/platform_common/migrations/*.sql "$out/migrations/platform/"
    cp -r "$ROOT/refdata" "$out/refdata"
  else
    # Runtime dependencies from app/pyproject.toml, without the app itself.
    deps "$out" $(python3 -c "import tomllib; print(' '.join(tomllib.load(open('$ROOT/app/pyproject.toml','rb'))['project']['dependencies']))")
    cp -r "$ROOT/app/src/app" "$out/"
    find "$out/app" -type d \( -name tests -o -name migrations \) -prune -exec rm -rf {} +
    cp -r "$ROOT/libs/platform_common/platform_common" "$out/"
    # Template files ship with the app (LLD-0 §8); the database holds only their metadata.
    mkdir -p "$out/refdata" && cp -r "$ROOT/refdata/templates" "$out/refdata/"
  fi
  find "$out" -name '__pycache__' -prune -exec rm -rf {} +
  (cd "$out" && python3 -c "import shutil; shutil.make_archive('$out', 'zip', '.')")
  echo "built build/$name.zip"
}

if [ "${1:-all}" = all ]; then
  for t in "${TARGETS[@]}"; do build "$t"; done
else
  build "$1"
fi

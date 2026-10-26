# Shortcuts for local development. See docs/TESTING.md.
PY ?= python3
LOCAL_DB := postgresql://postgres:local-only@localhost:5432/saas

.PHONY: setup openapi test isolation-local e2e-local db-up db-down db-migrate run-api smoke-local build

setup:            ## install the app, platform_common and the migrator with dev dependencies
	$(PY) -m pip install -e libs/platform_common -e "app[dev]" -r migrator/requirements.txt

openapi:          ## regenerate app/openapi.json and the web client types from it
	$(PY) scripts/export_openapi.py
	cd web && npm run gen:api

test:             ## every unit test (add PG_ADMIN_URL/PG_DSN for the PostgreSQL ones)
	cd libs/platform_common && $(PY) -m pytest -q
	cd app && $(PY) -m pytest -q
	cd migrator && $(PY) -m pytest -q
	$(PY) -m pytest -q tests/adr tests/tools

isolation-local:  ## database role guards on a fresh database (needs make db-up)
	PG_DSN=postgresql://postgres:local-only@localhost:5432/postgres $(PY) -m pytest -q tests/isolation

e2e-local:        ## black-box HTTP tests against the running local service (see tests/e2e)
	E2E_BASE_URL=http://localhost:8000 $(PY) -m pytest -q tests/e2e

db-up:            ## start local PostgreSQL in Docker
	docker compose up -d --wait postgres

db-down:          ## stop it and delete its data
	docker compose down -v

db-migrate:       ## apply all migrations to the local database
	cd migrator && $(PY) -m migrator.local $(LOCAL_DB)

run-api:          ## run the API on http://localhost:8000
	scripts/run_local.sh 8000

smoke-local:      ## end-to-end checks against the running local service
	scripts/smoke_test.sh http://localhost:8000

build:            ## build app.zip and migrator.zip into build/
	scripts/build_lambda.sh all

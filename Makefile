# Shortcuts for local development. See docs/TESTING.md.
SERVICES := identity commerce imports reports documents migrator
PY ?= python3
LOCAL_DB := postgresql://postgres:local-only@localhost:5432/saas

.PHONY: setup test isolation-local e2e-local db-up db-down db-migrate run-identity smoke-local build

setup:            ## install every service's dev dependencies
	$(PY) -m pip install -e libs/platform_common uvicorn pytest httpx
	for s in $(SERVICES); do $(PY) -m pip install -r services/$$s/requirements.txt; done

test:             ## unit tests for every service (add PG_ADMIN_URL/PG_DSN for the PostgreSQL ones)
	cd libs/platform_common && $(PY) -m pytest -q
	for s in $(SERVICES); do (cd services/$$s && $(PY) -m pytest -q) || exit 1; done

isolation-local:  ## database role guards on a fresh database (needs make db-up)
	PG_DSN=postgresql://postgres:local-only@localhost:5432/postgres $(PY) -m pytest -q tests/isolation

e2e-local:        ## black-box HTTP tests against the running local service (see tests/e2e)
	E2E_BASE_URL=http://localhost:8000 $(PY) -m pytest -q tests/e2e

db-up:            ## start local PostgreSQL in Docker
	docker compose up -d --wait postgres

db-down:          ## stop it and delete its data
	docker compose down -v

db-migrate:       ## apply all migrations to the local database
	cd services/migrator && $(PY) -m migrator.local $(LOCAL_DB)

run-identity:     ## run the identity service on http://localhost:8000
	scripts/run_local.sh identity 8000

smoke-local:      ## end-to-end checks against the running local service
	scripts/smoke_test.sh http://localhost:8000

build:            ## build the Lambda zips into build/
	scripts/build_lambda.sh all

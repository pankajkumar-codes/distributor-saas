# Testing: locally, then on AWS

Only the **identity** module has real endpoints so far, so these steps test sign-in,
tenants, members, invitations, audit and tenant isolation.

## 1. Automated tests (no setup beyond Python)

On Windows, run these from WSL, or copy the commands under each target in the `Makefile`.

```bash
make setup
make test
```

These run against an in-memory database. To also run the PostgreSQL tests, including
row-level security and the migrator, start the local database (step 2) and run:

```bash
PG_ADMIN_URL=postgresql+psycopg://postgres:local-only@localhost:5432/postgres \
PG_DSN=postgresql://postgres:local-only@localhost:5432/postgres make test
```

GitHub Actions runs all of these on every pull request, plus:

- `ruff check app migrator libs tests scripts` (rules in `ruff.toml`), including the
  clock rule: business code calls `Clock.now()` / `Clock.today()`, never
  `datetime.now()`, `date.today()` or `time.time()` (TID251; the few legacy files that
  still do are listed in `ruff.toml` with a reason)
- `migrations`: `python -m migrator.checks` on every timestamped migration. Names are
  `YYYYMMDDHHMM_snake_name.sql` with no shared prefix in a module; no business date in
  SQL (`current_date`, `now()::date`); every new table has ENABLE and FORCE row-level
  security unless `migrator/migrator/global_tables.yaml` lists it with a reason; a
  `NO FORCE` is forced again in the same file; every view is `security_invoker`
- `tax-literals`: `python scripts/ci_checks/tax_literals.py`. No number but 0, 1 and
  100, no `Decimal` but `"0.01"`, and no date in sales, filing, catalog or imports code
  (tests excluded): rates, thresholds and dates belong in `refdata/`. A finding that
  isn't a tax rule goes in `scripts/ci_checks/tax_literals_allowlist.yaml` with a reason
- `python scripts/ci_checks/sql_boundaries.py` (in `boundaries`): SQL in one module
  names another module's schema only as `<schema>.v_<view>` or `<schema>.<function>(`
- `pytest tests/tools`: each check above fails on its planted fixture in
  `tests/ci_fixtures/` and passes on the repository (AC-13)
- `python scripts/float_guard.py`: no float literals, `float()` or `float` types in any
  module under `app/`, `migrator/` or `libs/` (tests excluded); a real exception needs a
  `# float-ok: <reason>` comment on the line, which reviewers must agree with
- `python scripts/ci_checks/migration_keys.py origin/main`: no migration that exists on
  `main` is missing or edited (the migrator keys its ledger on module and file name)
- `lint-imports` (contracts in `.importlinter`): modules don't import each other, the
  API or the worker; `platform_common` and the migrator import nothing from the app
- gitleaks over the whole git history
- `openapi`: `app/openapi.json` matches the API (`make openapi` regenerates it and the web
  client types), and no money field is typed as a number
- `refdata`: every file under `refdata/` passes the loader's checks
  (`python -m migrator.refdata check ../refdata` from `migrator/`); the migrator tests
  also load them into PostgreSQL
- `web`: exact pins in `web/package.json`, `npm ci` from the lockfile, `npm audit`
  with no high or critical advisory in a runtime dependency, generated API types, `tsc`,
  ESLint, Vitest and the production build (`web/README.md`)
- `web-e2e`: Playwright at 360 px and 1280 px against the API on PostgreSQL (sign-up with
  the emailed code, the reload fallback, a reload keeping the session, sign-out and
  sign-in, creating a business with a GSTIN and landing on its Home), with axe finding
  nothing serious or critical
- the end-to-end suite below, against identity on real PostgreSQL, after migrating twice
- `tests/isolation`: role guards after every migration. No role but the migrating superuser
  has superuser, BYPASSRLS, CREATEROLE or replication; the app and owner roles from the
  design can't reach a privileged role; NOLOGIN roles can't log in; no login role owns
  objects. Run it locally with `make isolation-local`

Jobs and storage never touch AWS in CI: tests use `FakeQueue` and `LocalObjectStore`,
and only `platform_common/aws.py` imports boto3, which no test loads. Locally, a job
runs as soon as its request commits (`InlineQueue`), and presigned uploads and
downloads go to `/api/v1/dev/objects/*`, which exist only in a debug environment.

LLD-0 §7 checks not in CI yet, and why:
- `route-coverage` (every route declares its permission and has a tenant test): waits
  for the LLD-1 routes to settle; the stock-era routes in `identity/api.py` go first.
- `openapi` (the generated schema matches the committed one): Junior's PR #38.
- "every tenant table calls `platform.apply_tenant_policies`": no such function yet;
  tenant migrations write the policy pair out, and `migrations` checks ENABLE/FORCE.
- "only allow-listed files run as the master": every migration runs as the master today.

Some tests are marked `xfail(strict=True)`. Each one is a known defect with an ID
(`QA-DEF-…`) in the QA plan. When the fix lands the test passes, pytest reports it as an
unexpected pass and fails, and the marker must be removed in the same PR.

## 2. Run it on your machine

Needs Docker and Python 3.12.

```bash
make db-up          # PostgreSQL 16 in Docker on localhost:5432
make db-migrate     # applies every module's migrations (identity schema, tables, row-level security)
make run-api        # API on http://localhost:8000 (leave this running)
```

In a second terminal:

```bash
make smoke-local    # creates a tenant as one user, checks a second user can't see it
```

You should see `ALL CHECKS PASSED`. Then run the fuller end-to-end suite:

```bash
make e2e-local      # tests/e2e: onboarding, isolation, roles, error leakage
```

The same suite runs against staging with two Cognito tokens:
`E2E_BASE_URL=$API E2E_TOKEN_A=... E2E_TOKEN_B=... pytest tests/e2e`. Tests that need a
third user skip there. You can also open http://localhost:8000/docs to
try each endpoint in the browser. Locally there is no Cognito: the `X-Debug-User`
header plays the signed-in user, for example `X-Debug-User: alice`. That header is
ignored everywhere except local and test runs, and always on Lambda. A local run must
export `PLATFORM_ENV=local` (`make run-api` and `scripts/run_local.sh` do): a bare
`uvicorn app.api:app` starts with `PLATFORM_ENV` unset, which fails closed, so debug
login is off.

`make db-down` deletes the local database when you want a fresh start.

## 3. Test on AWS (staging)

> Written, not yet run. Nothing in AWS exists until Pankaj decides on staging (D-040),
> and the first staging deploy needs the CEO's approval (TD-20). The app still lacks
> `app.mailer.handler` and the Parameter Store key reads (docs/OPEN_QUESTIONS.md), so
> sign-up email won't work on a stack built from this commit.

Needs an AWS account in Mumbai, the AWS CLI v2 signed in to it, and Terraform 1.10 or
newer. Staging costs about USD 49 a month while it exists (tech plan §7): mostly the
database and three private network endpoints (SQS, Parameter Store, Cognito) at about
USD 9.5 each. Run `terraform destroy` when you finish testing, to save credits.

### One-time setup

```bash
aws configure                     # region: ap-south-1
cd infra/bootstrap && terraform init && terraform apply
# note the state_bucket output, then:
cd ../envs/staging
cp terraform.tfvars.example terraform.tfvars   # app origin and alert email
terraform init -backend-config="bucket=<state_bucket from above>"
```

Until a domain exists, put any https origin in `web_origins` for the first apply. Then
replace it with the `app_url` output and apply again: `APP_ORIGIN` and the upload CORS
rule follow it.

### Deploy

`.github/workflows/deploy-staging.yml` does these steps (a reviewed plan, then that plan
applied; docs/DEPLOYMENT.md) once Pankaj has finished the deploy setup. Run by hand,
they are:

```bash
cd ../../..                       # repo root
make build                        # build/app.zip and build/migrator.zip
(cd web && npm ci && npm run build)
cd infra/envs/staging
terraform plan -out=tfplan        # review what will be created
terraform apply tfplan            # runs the migrator before updating the API and worker
aws s3 sync ../../../web/dist "s3://$(terraform output -raw web_bucket)"
aws cloudfront create-invalidation --distribution-id "$(terraform output -raw cdn_distribution_id)" --paths /index.html
```

The apply fails if a migration fails. The migrator's log
(`aws logs tail /aws/lambda/distsaas-staging-migrator`) lists what it applied and the
refdata it loaded.

### Create two test users and run the smoke test

Staging allows command-line password sign-in for test users. Prod does not.

```bash
POOL=$(terraform output -raw user_pool_id)
CLIENT=$(terraform output -raw user_pool_client_id)
APP=$(terraform output -raw app_url)

for U in tester-a@example.com tester-b@example.com; do
  aws cognito-idp admin-create-user --user-pool-id "$POOL" --username "$U" \
    --user-attributes Name=email,Value="$U" Name=email_verified,Value=true --message-action SUPPRESS
  aws cognito-idp admin-set-user-password --user-pool-id "$POOL" --username "$U" \
    --password 'Staging-Test-Pass1' --permanent
done

token() {
  aws cognito-idp initiate-auth --client-id "$CLIENT" --auth-flow USER_PASSWORD_AUTH \
    --auth-parameters USERNAME="$1",PASSWORD='Staging-Test-Pass1' \
    --query AuthenticationResult.AccessToken --output text
}

../../../scripts/smoke_test.sh "$APP" "$(token tester-a@example.com)" "$(token tester-b@example.com)"
```

Access tokens last 5 minutes (TD-4b), so fetch them just before the run. A user created
this way has no `identity.sessions` row, so identity answers 401 until S1 sign-in
creates one (docs/ARCHITECTURE.md).

QA's staging-only checks (LLD-0 §7) run here too: real Cognito over the endpoint, the
JWT authorizer through CloudFront, SES, cookie forwarding, the H-4 upload policy, the
mail queue's retention, and `SHOW max_connections`.

### When something fails

```bash
aws logs tail /aws/lambda/distsaas-staging-api --since 15m
aws logs tail /aws/lambda/distsaas-staging-worker --since 15m
aws logs tail /aws/apigateway/distsaas-staging --since 15m
```

A 401 means the token was missing or expired. A 500 usually means the database is
unreachable or the migrations did not run, so check the API log. A message in either
dead-letter queue sends an alarm email to `budget_alert_emails`.

### Clean up

```bash
terraform destroy
```

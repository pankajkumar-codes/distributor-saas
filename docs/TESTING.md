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

- `ruff check app migrator libs tests scripts` (rules in `ruff.toml`)
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
- `web`: exact pins in `web/package.json`, `npm ci` from the lockfile, and `npm audit`
  with no high or critical advisory in a runtime dependency (`web/README.md`)
- the end-to-end suite below, against identity on real PostgreSQL, after migrating twice
- `tests/isolation`: role guards after every migration. No role but the migrating superuser
  has superuser, BYPASSRLS, CREATEROLE or replication; the app and owner roles from the
  design can't reach a privileged role; NOLOGIN roles can't log in; no login role owns
  objects. Run it locally with `make isolation-local`

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

> Out of date until Staff 2's S0b infra change: the Terraform below still deploys the
> old per-service Lambdas, while `make build` now builds `app.zip` and `migrator.zip`.

Needs an AWS account (Mumbai, Paid plan), the AWS CLI v2 signed in to it, and
Terraform 1.10 or newer. Staging costs money while it exists, roughly $30 a month,
mostly the database and two private network endpoints. Run `terraform destroy` when
you are done testing to save credits.

### One-time setup

```bash
aws configure                     # region: ap-south-1
cd infra/bootstrap && terraform init && terraform apply
# note the state_bucket output, then:
cd ../envs/staging
cp terraform.tfvars.example terraform.tfvars   # set your web origin and alert email
terraform init -backend-config="bucket=<state_bucket from above>"
```

### Deploy

```bash
cd ../../..                       # repo root
make build                        # Lambda zips in build/
cd infra/envs/staging
terraform plan                    # review what will be created
terraform apply
aws lambda invoke --function-name "$(terraform output -raw migrator_function)" out.json && cat out.json
```

The last command applies the database migrations. It should list
`identity/0001_identity.sql` and `identity/0002_identity_rls.sql`.

### Create two test users and run the same smoke test

Staging allows command-line password sign-in for test users. Prod does not.

```bash
POOL=$(terraform output -raw user_pool_id)
CLIENT=$(terraform output -raw user_pool_client_id)
API=$(terraform output -raw api_endpoint)

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

../../../scripts/smoke_test.sh "$API" "$(token tester-a@example.com)" "$(token tester-b@example.com)"
```

### When something fails

```bash
aws logs tail /aws/lambda/distsaas-staging-identity --since 15m
aws logs tail /aws/apigateway/distsaas-staging --since 15m
```

A 401 means the token was missing or expired (tokens last 60 minutes). A 500 usually
means the database is unreachable or migrations did not run. Check the identity log.

### Clean up

```bash
terraform destroy
```

# Distributor SaaS

Multi-tenant commerce and distribution SaaS for Indian sellers and distributors
(first tenant: Vashi Essentials). Product rules live in `CLAUDE.md` and `docs/`.

## Shape

One Python (FastAPI) app on AWS Lambda in Mumbai (`ap-south-1`), split into modules
that each own a PostgreSQL schema (D-027, which replaced the five-service design).
It sits behind one API Gateway with Cognito sign-in and shares one RDS PostgreSQL
instance. Everything in AWS is Terraform.

| Path | What | State |
| --- | --- | --- |
| `app/src/app/api.py` | API Lambda: every module's router under `/api/v1` | working, tested |
| `app/src/app/worker.py` | worker Lambda: SQS jobs | skeleton |
| `app/src/app/modules/identity` | tenants, memberships, roles, invitations, audit log | working, tested |
| `app/src/app/modules/imports` | marketplace file parsing and validation | parsing only, tested |
| `libs/platform_common` | shared helpers: auth, unit of work, errors (Deny → 404), permissions, clock, paging, money, idempotency | working, tested |
| `migrator/` | applies every module's SQL migrations once, as the RDS master user | working, tested |

See `docs/ARCHITECTURE.md` for the reasoning and costs.

## Tenant isolation

- The tenant is never trusted from the client. Every request is checked against an
  active membership, and a tenant you are not in answers exactly like one that does
  not exist (404).
- PostgreSQL row-level security repeats the check inside the database, so a query that
  forgets its tenant filter still returns nothing from other tenants.
- The app connects with short-lived IAM tokens; no database password is stored in
  it. The identity module cannot update or delete audit rows.

## Test it

Step-by-step local and AWS testing: **docs/TESTING.md**. Quick version:

```bash
make setup && make test
make db-up && make db-migrate && make run-api   # then: make smoke-local
```

## Run the tests

```bash
pip install -e libs/platform_common -e "app[dev]"
cd app && pytest -q                         # in-memory SQLite
PG_ADMIN_URL=postgresql+psycopg://postgres@localhost:5432/postgres pytest -q   # plus real PostgreSQL + RLS
```

## Deploy (needs your AWS account; nothing here has been applied yet)

1. Create the AWS account in Mumbai on the **Paid plan** (the Free plan closes after
   6 months; the Paid plan still gets the sign-up credits).
2. `cd infra/bootstrap && terraform init && terraform apply` creates the state bucket.
3. Put that bucket name into `bucket = "..."` in `infra/envs/staging/main.tf`'s backend
   block (or pass `-backend-config=bucket=...`).
4. `cp infra/envs/staging/terraform.tfvars.example infra/envs/staging/terraform.tfvars`
   and fill in your web origin and budget-alert email.
5. `scripts/build_lambda.sh all` (builds `app.zip` and `migrator.zip`; the Terraform
   still expects per-service zips until the S0b infra change)
6. `cd infra/envs/staging && terraform init && terraform plan`, review, then `terraform apply`.
7. `aws lambda invoke --function-name $(terraform output -raw migrator_function) out.json`
   applies the database migrations.

Each environment has an AWS budget alert (staging $30, prod $60 a month by default).

## Rough monthly cost at small scale (not yet checked against Mumbai prices)

| Item | Approx. USD/month |
| --- | --- |
| RDS PostgreSQL db.t4g.micro, 20 GB | 15 |
| SQS + Secrets Manager private endpoints, one AZ | 15 |
| Lambda, API Gateway, SQS, Cognito, S3 at low volume | ~0 to 5 |

No NAT gateway is used. Switch `db_multi_az = true` in prod before live invoices
(roughly doubles the database line).

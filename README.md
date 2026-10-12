# Distributor SaaS

Multi-tenant commerce and distribution SaaS for Indian sellers and distributors
(first tenant: Vashi Essentials). Product rules live in `CLAUDE.md` and `docs/`.

## Shape

Five Python (FastAPI) microservices on AWS Lambda in Mumbai (`ap-south-1`), behind one
API Gateway with Cognito sign-in, sharing one RDS PostgreSQL instance where each
service owns its own schema and database user. Everything in AWS is Terraform.

| Service | Owns | State |
| --- | --- | --- |
| identity | tenants, memberships, roles, audit log | working, tested |
| commerce | catalog, purchases, stock ledger, wholesale invoices, payments | skeleton, waits on D-009 to D-013 |
| imports | marketplace file uploads, staging, validation, de-duplication | skeleton, waits on sample reports |
| documents | invoice PDFs from SQS events | skeleton |
| reports | registers, reconciliation, exports | skeleton |
| migrator | applies every service's SQL migrations once, as the RDS master user | working, tested |

See `docs/ARCHITECTURE.md` for the reasoning and costs.

## Tenant isolation

- The tenant is never trusted from the client. Every request is checked against an
  active membership, and a tenant you are not in answers exactly like one that does
  not exist (404).
- PostgreSQL row-level security repeats the check inside the database, so a query that
  forgets its tenant filter still returns nothing from other tenants.
- Services connect with short-lived IAM tokens as `svc_<service>`; no database
  password is stored in the services. The identity service cannot update or delete
  audit rows.

## Run the tests

```bash
cd services/identity
pip install -r requirements-dev.txt -e ../../libs/platform_common
pytest -q                                   # in-memory SQLite
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
5. `scripts/build_lambda.sh all`
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

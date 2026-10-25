# Architecture

**Decided 2026-10-24** (D-027, superseding the five-service design of D-019). The
authoritative design documents are in the project files, not in this repo:

- tech plan DOC-3 v0.2 (`team/docs/tech-plan.md`);
- HLD DOC-4 v0.2 (`team/docs/hld.md`);
- LLD-0 to LLD-7 (`team/docs/lld-*.md`).

This page summarises them. Where it differs from them, they win.

> **Code status.** Until the S0a restructure PR merges, the repo still has the old
> layout (`services/<name>/` with one Lambda each and a `svc_<name>` login role).
> The S0a PR moves it to the layout below without changing behaviour.

## One app, split into modules

One modular monolith, deployed as four Lambdas built from one codebase:

- **api**: FastAPI behind API Gateway (HTTP API). It serves `/api/v1/*`.
- **worker**: consumes SQS jobs, which come from a transactional outbox.
- **mailer**: outside the VPC, with no database access. It only sends email through SES.
- **migrator**: applies migrations and loads refdata on deploy.

Each module has its own PostgreSQL schema and an `interface` package. Other modules
may import only that `interface` package, and import-linter enforces this in CI. Reads
across modules go through `security_invoker` views. There are no foreign keys across
schemas. The shared code is `libs/platform_common`. It provides:

- `unit_of_work` / `business_uow`;
- `Principal`, `require(permission)`, and `Deny` → 404;
- `MoneyStr` (decimal strings over the API, never floats);
- `uuid7`, and `Clock` for IST business dates;
- audit, outbox and jobs, idempotency, rate counters and log redaction.

The web app is a React + TypeScript single-page app on S3 + CloudFront, on the same
origin as `/api/*` (D-023).

## Data and tenancy

- **Database:** one RDS PostgreSQL 16 instance.
- **Database roles:**
  - The app connects as `app_rw` (IAM auth).
  - Read-only units of work switch to `app_ro`.
  - Database objects are owned by `app_owner`, which only the migrator uses.
  - Retention runs as `app_retention`, through definer functions only.
- **Row-level security:** FORCE RLS on every tenant table. Policies read `app.tenant_id`,
  `app.user_id`, `app.role` and `app.support_grant_id`, set per transaction from the
  verified membership. They never come from the client.
- **Support staff:** read only, and only through an owner-created, expiring grant that
  is audited on every request.
- **Financial records:** finalized documents and return snapshots are insert-only.
  Corrections are new rows, such as credit notes and new snapshot versions (D-034,
  D-035).

## Sign-in

Our API fronts Cognito. We issue and check our own email codes, and Cognito holds
passwords and TOTP. Access tokens last 5 minutes, and every request also checks the
session. Refresh happens through an `HttpOnly` cookie (D-028).

## Network and cost

- **Subnets:** private only. No NAT gateway.
- **AWS services from the VPC:** S3 through a gateway endpoint. SQS, Secrets Manager
  and Cognito through interface endpoints in one AZ.
- **Email:** leaves through the mailer Lambda outside the VPC.
- **Public internet:** any future call to it (marketplace or GST APIs) needs a NAT
  gateway or a proxy, which is a cost decision.
- **Budget:** about USD 49/month per environment (D-008).

## Deliberately not done yet

- Nothing is deployed. CI tests the code and validates Terraform only. Deploys wait
  for the OIDC role and approval (D-031).
- Stock, payments beyond one full payment per invoice, GSP filing, e-invoice and
  e-way bill APIs are out of Release 1 (HLD §1).

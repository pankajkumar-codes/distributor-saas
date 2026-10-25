# Architecture (decided 12 Oct 2026)

Owner decisions on 12 Oct 2026: host on AWS Mumbai; build as microservices with AWS
infrastructure as code; write services in Python.

## Service boundaries

Boundaries follow transactions, not tables. Finalizing an invoice, deducting its
stock and allocating its payment must succeed or fail together, so catalog,
procurement, stock, wholesale sales and payments all live in **commerce**. Splitting
them would need distributed transactions or sagas around money, which the business
rules (sections 4, 5 and 10) make risky.

- **identity**: tenants, memberships, roles, audit. Cognito handles passwords and MFA.
- **commerce**: everything that changes stock or money. Publishes events to SQS.
  Data model: `docs/adr/0001-commerce-data-model.md` (proposed).
- **imports**: uploads land in a private S3 bucket; rows are staged, validated and
  previewed; confirmed rows are handed to commerce idempotently (source file checksum
  plus external IDs).
- **documents**: consumes invoice-finalized events and writes PDFs to S3.
- **reports**: read-only access to the other schemas.

## Data

One RDS PostgreSQL instance, one schema per service, one login role per service with
grants only on its own schema (reports gets read-only grants). Row-level security keys
off `app.user_sub` / `app.tenant_id`, set per transaction by the service.

Services other than identity never read identity tables. They check membership with
`platform_common.tenancy.tenant_dependency`, which calls the security-definer
functions `identity.caller_role()` / `identity.is_member()` (granted through the
`tenant_auth` group role, identity migration 0003). Those functions only answer for
the user in `app.user_sub`. The dependency then binds the request's session to the
tenant, re-applying both settings at the start of every transaction.

## Network and cost

Private subnets only. No internet gateway and no NAT gateway. Lambdas reach S3 through
a free gateway endpoint, and SQS and Secrets Manager through interface endpoints in a
single AZ to keep cost down. Calls to anything on the public internet (marketplace or
GST APIs later) will need a NAT gateway or a proxy, which is a cost decision.

## Deliberately not done yet

- No business endpoints in commerce, imports, reports or documents: they wait on the
  blocking decisions in DECISIONS.md.
- No web frontend yet (planned: React on S3 + CloudFront).
- No deploy pipeline to AWS: CI tests and validates Terraform only. Applying is manual
  until an AWS account and an approval step exist.

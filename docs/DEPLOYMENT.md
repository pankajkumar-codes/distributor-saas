# Deployment Plan

## Approval required
Do not choose or provision a cloud provider, paid service, production database, domain, or public deployment without explicit approval.

## Environments
- Local development
- Automated test/CI
- Staging
- Production

Use separate credentials and data stores per environment. Do not copy production data into development by default.

## Required deployment capabilities
- Repeatable build and deployment process.
- Environment-variable documentation.
- Secret management through the selected platform.
- Database migration procedure and pre-migration backup for risky changes.
- Liveness/readiness health checks.
- Structured logs, error reporting, and basic metrics.
- Database backups with documented retention.
- Restoration and recovery procedure.
- Rollback strategy.
- TLS and secure domain configuration.
- Access control and least privilege.
- Cost alerts or budgets where supported.
- Data export and exit strategy to reduce lock-in.

## Cloud selection checklist
Compare:
- Hosting region and data requirements.
- Monthly baseline and usage-based costs.
- Managed relational database availability.
- Backup/restore features and retention pricing.
- Object storage and egress pricing.
- Background job support.
- Secrets, logs, metrics, and alerting costs.
- Deployment simplicity and rollback.
- Scaling limits and migration path.
- Vendor lock-in.

## Current state (D-040)
AWS in Mumbai (`ap-south-1`) is chosen (TD-1). The Terraform under `infra/` and the
manual workflow `.github/workflows/deploy-staging.yml` are written but **not applied**:
no AWS resource exists until Pankaj decides on staging, and the first staging deploy needs
the CEO's approval (TD-20, TD-21). How to deploy and test: `docs/TESTING.md` §3.

The stack has six functions: `api`, `worker`, `mailer`, `migrator`, `retention`
(D-041, L6-5), the only one that logs in as `app_retention`, and `renderer` (D-042), the
PDF renderer from its own `renderer.zip`. The `retention` function's
`purge` and `retention` schedules are written **disabled**. Its errors alarm is a standard
CloudWatch alarm, about USD 0.10 a month once applied; the function itself costs nothing
while its schedules are off. Hourly runs of a few seconds would be well under USD 0.01
a month at Lambda list prices (not verified against an AWS bill).

**Renderer costs (D-042), once applied:**
- The function costs nothing while nothing sends to its `render` queue; S4 adds the
  sender. Lambda still polls the empty queue, which makes SQS requests every month. With
  the jobs and mail queues that may pass SQS's 1 million free requests a month (about
  USD 0.40 per further million). Not verified against a bill.
- A one-page invoice took about 0.3 s warm at 1024 MB locally, so about 0.3 GB-s. At the
  arm64 list price of about USD 0.0000134 per GB-s (us-east-1; Mumbai not checked), that
  is about USD 0.000004 per invoice plus USD 0.20 per million requests.
- Ten thousand invoices a month would be about USD 0.05, inside Lambda's monthly free
  allowance (400,000 GB-s) if the account still has it.
- Its DLQ alarm is another standard alarm, about USD 0.10 a month.
- The zip has no ECR cost (it is not an image) and no NAT: the renderer runs outside the
  VPC. The worker reaches it through SQS over the existing SQS endpoint, so there is no
  Lambda VPC endpoint (about USD 7-8 a month per AZ).
- The deployed zip is built with Python 3.12.15 and pip 26.2.2, pinned in
  `deploy-staging.yml` as in CI (`renderer/README.md`).

## Launch prerequisites (AWS account actions, Pankaj)
- **Lambda concurrency quota of at least 156 in ap-south-1 before the first prod apply.**
  Prod reserves TD-6's caps (api 40, worker 10, mailer 5, migrator 1 = 56), and Lambda
  keeps 100 of the account quota unreserved, so the apply fails on a smaller quota. The
  increase is requested in Service Quotas and costs nothing. Staging leaves the caps off.
- The deploy setup below.
- A domain, its ACM certificate in us-east-1 (CloudFront), and SES production access for
  that domain (tech plan §0, §4.5).

## How a staging deploy runs (`.github/workflows/deploy-staging.yml`)
Started by hand from `main` only. Two jobs, both in the `staging` environment, so each
waits for its required reviewer:
1. **plan** builds `app.zip`, `migrator.zip`, `renderer.zip` and the web files, runs `terraform plan
   -out=tfplan`, and shows the plan in the run summary (sensitive values hidden). The
   plan, its provider lock file and the built files go to the state bucket under
   `plans/staging/<run id>/`. A plan file contains state, secrets included, so it never
   becomes a GitHub artifact; a 7-day lifecycle rule removes any plan whose apply never
   ran.
2. **apply** fetches exactly those files and runs `terraform apply tfplan`, so what is
   applied is what the reviewer read. Terraform refuses the plan if the state changed
   after it was made. The migrator runs inside the apply, before the API and worker
   change (`aws_lambda_invocation.migrate` in the stack), and a migration error fails
   the apply. Then the web files are published and only `index.html` is invalidated;
   older hashed files stay, so an open browser can still load its scripts.

No third-party action runs in these jobs, because they can mint AWS credentials:
Terraform is installed from HashiCorp and checked against its published SHA-256
(`scripts/deploy/install_terraform.sh`), and the sign-in uses the preinstalled AWS CLI
(`scripts/deploy/aws_oidc_login.sh`). Only GitHub's own `actions/*` are used.

## Deploy setup checklist (Pankaj, once, after the staging decision)
1. Apply `infra/bootstrap` once from your machine (`docs/TESTING.md` §3) and note its
   `state_bucket` output.
2. IAM: add GitHub as an OIDC identity provider (`token.actions.githubusercontent.com`,
   audience `sts.amazonaws.com`), and a deploy role that trusts it with these conditions:
   - `token.actions.githubusercontent.com:aud` equals `sts.amazonaws.com`;
   - `token.actions.githubusercontent.com:sub` equals
     `repo:pankajkumar-codes/distributor-saas:environment:staging`, exactly, with no
     wildcard, so only jobs in the `staging` environment of this repository can assume it.

   The role needs rights to create everything in `infra/modules` and to read and write
   the state bucket. Narrowing them to a least-privilege policy is a follow-up.
3. GitHub, Settings > Environments: create `staging` with **required reviewers** (you,
   or whoever you name) and **deployment branches limited to `main`**.
4. GitHub, Settings > Secrets and variables > Actions > Variables: set
   `AWS_DEPLOY_ROLE_ARN`, `TF_STATE_BUCKET`, `STAGING_WEB_ORIGINS` and
   `BUDGET_ALERT_EMAILS`.
5. Confirm each budget and alarm email subscription that AWS sends.

## Go-live checklist
- All critical tests pass.
- Tax and invoice behavior reviewed by a qualified professional.
- Tenant isolation independently tested.
- Production secrets configured securely.
- Backups and restore tested.
- Monitoring and alerting enabled.
- Incident and support process documented.
- Data retention and privacy notices reviewed.
- No unapproved external integrations or recurring costs.

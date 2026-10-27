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
1. **plan** builds `app.zip`, `migrator.zip` and the web files, runs `terraform plan
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

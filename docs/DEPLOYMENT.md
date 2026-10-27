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
- The OIDC deploy role and the repository variables listed in the deploy workflow.
- A domain, its ACM certificate in us-east-1 (CloudFront), and SES production access for
  that domain (tech plan §0, §4.5).

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

# Deployment Plan (Provider Not Yet Selected)

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

# Security and Privacy Requirements

## Threat model priorities
- Cross-tenant data exposure.
- Broken object-level authorization.
- Unauthorized invoice, stock, payment, or tax-record mutation.
- Duplicate effects caused by retries or concurrent requests.
- Malicious or malformed uploaded spreadsheets.
- Exposed credentials, tokens, exports, or uploaded files.
- Unsafe PDF/file access.
- Sensitive information leaking through logs, errors, or analytics.
- Compromised dependencies or deployment secrets.

## Required controls
- Server-side authorization for every tenant-owned object.
- Tenant-aware repository/query patterns and, where suitable, database-level defense in depth.
- Secure password/session management or a reviewed identity provider.
- Rate limiting and abuse controls appropriate to exposed endpoints.
- CSRF protections where applicable; secure cookie flags; strict CORS policy.
- Input validation and output encoding.
- Safe file type/size limits, parsing limits, and formula-injection protections for spreadsheet exports.
- Private object storage with authorization checks and expiring links where appropriate.
- Secrets outside source control; separate credentials per environment.
- Dependency scanning and patch process.
- Structured logs that omit secrets and unnecessary personal/financial data.
- Audit logs for sensitive operations.
- Encryption in transit and managed encryption at rest where available.
- Backup protection, access control, retention, and restoration testing.
- Least-privilege production roles and restricted operational access.

## Testing requirements
- Attempt cross-tenant reads/writes using guessed IDs.
- Test tenant scope on search, exports, downloads, reports, and background tasks.
- Test concurrent invoice/stock operations.
- Test malformed, oversized, duplicate, and formula-containing import files.
- Verify logs do not include credentials or full sensitive payloads.
- Verify a backup can be restored to a clean environment.

## Data handling
Use synthetic data in development and tests. Do not upload production customer records to external AI tools unless the data-handling implications have been explicitly reviewed and approved.

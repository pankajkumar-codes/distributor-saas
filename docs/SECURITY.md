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

## Release 1 threat-model delta (HLD DOC-4 §10, approved 2026-10-24)
These sharpen the priorities above for the approved design (docs/ARCHITECTURE.md). Each row names its test, and a feature that touches a row isn't done until that test passes.

**Trust boundaries:**
1. Browser ↔ CloudFront/API Gateway: everything from the client is untrusted, including business IDs, object IDs, roles shown in the UI and money values. The server recomputes all of them.
2. Unauthenticated routes (auth and public share links): rate-limited, with uniform replies.
3. API ↔ database: the tenant is set from the verified membership only.
4. Worker: jobs carry IDs, not data. The worker re-opens a unit of work with the job's business ID and its recorded actor, so RLS applies to jobs too.
5. Mailer: outside the VPC, with no database access; SES only.
6. Support staff: access only through grants.

**Authorization:** every route declares a permission (`require(permission)`), and a CI route-coverage check fails any route that has neither a permission nor an isolation-matrix entry. Role refusals return 404.

| Threat | Mitigation | Test |
|---|---|---|
| Cross-tenant ID guessing (API, exports, jobs, presigned keys) | Membership check + RLS + S3 keys under the business prefix, issued only by the API | Isolation suite per route and per job type, run as `app_rw` |
| Account enumeration via sign-up, verify or reset | Uniform reply and timing class on all three; an existing account gets an email, not an error | Byte-identical response and status on all three routes |
| Code brute force | 5 tries, 10 minutes, per-email and per-IP limits | Sign-up and sign-in code tests |
| Stolen access token after sign-out | 5-minute tokens + per-request session check | Session tests |
| CSRF on refresh | `SameSite=Strict`, path-scoped cookie, Origin check | Refresh from another origin is refused |
| Share-link guessing or replay | 128-bit token, hashed at rest, expiry, revoke, IP throttle, uniform 404 | Share-link tests |
| Formula injection in exports and uploads | Neutralise on every export and on parse | Export and import suites |
| Malicious upload (zip bomb, huge XLSX) | Size limit in the presigned POST policy, row and column limits in the parser, worker memory and timeout caps | Oversize and bomb fixtures |
| Codes, tokens or passwords in logs | Log filter on `password`, `code` and `token` fields; no request bodies in access logs; mail queue rules | Log-capture test for codes, tokens and the test password |
| Support abuse | Grants only, read only, audited per request | Grant tests |
| Tampering with filed figures | Insert-only snapshots, checksums, audit link | UPDATE/DELETE as `app_rw` fails |
| Privilege escalation inside a tenant at the database (e.g. self-promotion, self-invite as owner) | RLS write policies by role, owner-row trigger, column-level grants on invitations (identity migrations 0004 and 0005) | PostgreSQL RLS write tests in `services/identity/tests` |

**Secrets and encryption:**
- KMS on S3 and RDS.
- Secrets Manager and IAM database auth.
- Verification codes and share tokens are stored only as hashes.
- Nothing secret is kept in the repo.

## Data handling
Use synthetic data in development and tests. Do not upload production customer records to external AI tools unless the data-handling implications have been explicitly reviewed and approved.

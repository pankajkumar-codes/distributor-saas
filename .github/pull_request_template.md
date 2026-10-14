<!-- Process and review rules: see the team engineering handbook. One vertical slice per PR. -->

**Backlog item:** B-___

**Before:**

**After:**

## What changed

## How it was tested
<!-- Commands you actually ran and their result. Say plainly what was not run. -->

- [ ] Unit tests
- [ ] Integration tests against PostgreSQL
- [ ] Cross-tenant test for every new endpoint or query

## Review checklist
- [ ] Tenant scoping and object authorization enforced on the server
- [ ] Money uses `Decimal` via `platform_common.money`; no floats; rounding passed explicitly
- [ ] No in-place edits or deletes of finalized documents or posted stock movements
- [ ] Imports idempotent and traceable (file checksum, row, external ID)
- [ ] No invented GST rates, thresholds or statutory rules
- [ ] Migrations forward-only and additive
- [ ] No secrets or real personal/financial data
- [ ] Retry and partial-failure behavior handled
- [ ] Docs updated (DECISIONS, OPEN_QUESTIONS, specs, TESTING)

## Decisions touched
<!-- D-0xx IDs from docs/DECISIONS.md. Approval-gated ones need a link to the owner's approval. -->

## Limitations

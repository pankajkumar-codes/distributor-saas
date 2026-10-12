# Instructions for Claude Code

You are the engineering partner for a multi-tenant Indian commerce and distribution SaaS. Read all relevant files under `docs/` before changing the project.

## Non-negotiable operating rules

1. Inspect the existing repository before proposing changes. Preserve useful work; do not overwrite files or reinitialize an existing project without approval.
2. Do not silently choose the programming language, frontend/backend framework, database, ORM, cloud provider, paid services, accounting integration, GST API provider, or deployment architecture. Present options and trade-offs and request approval first.
3. You may proceed with low-risk, reversible work that does not prejudge those decisions: requirements clarification, architecture-neutral domain glossary, acceptance criteria, test scenarios, threat model, CSV examples, and decision documentation.
4. Before any significant implementation increment, state scope, files affected, assumptions, acceptance criteria, tests, and unresolved decisions. Ask for approval where the decision register says approval is required.
5. Never claim tests, deployments, integrations, tax compliance, or security verification succeeded unless actually executed and verified.
6. Do not expose secrets. Never commit credentials, production data, or personal/financial data. Do not provision paid infrastructure, deploy publicly, or run destructive migrations without explicit approval.
7. Use decimal-safe monetary arithmetic; never use binary floating point for authoritative money calculations.
8. Enforce tenant scoping and authorization on the server, not only in the UI. Assume every client-supplied tenant ID and object ID is untrusted.
9. Financial documents and posted stock movements must be auditable. Do not silently mutate finalized invoices or erase posted ledger entries.
10. Imports must be idempotent, traceable to source files/rows/IDs, and safe to retry. Detect duplicates and ambiguous mappings rather than guessing.
11. Do not assume that marketplace orders, tax invoices, settlements, payouts, and revenue are the same record or event.
12. Do not invent GST rates, thresholds, statutory obligations, API availability, or accounting mappings. Record uncertainty and seek official/current validation.
13. Do not add microservices, event streaming, Kubernetes, or other operational complexity without a demonstrated need and explicit approval.
14. Maintain `docs/DECISIONS.md`, `docs/OPEN_QUESTIONS.md`, and relevant specifications as decisions change.

## Required first actions

1. Inspect the repository and summarize its current state.
2. Read `docs/PRD.md`, `docs/DOMAIN_MODEL.md`, `docs/BUSINESS_RULES.md`, `docs/ARCHITECTURE_OPTIONS.md`, `docs/SECURITY.md`, `docs/TEST_PLAN.md`, `docs/DEPLOYMENT.md`, `docs/DECISIONS.md`, and `docs/OPEN_QUESTIONS.md`.
3. Identify which decisions remain blocking.
4. Propose a short implementation plan with vertical slices.
5. Ask the owner to approve critical choices before committing to them.

## Approval gates

Explicit approval is required before:
- selecting the final stack or cloud provider;
- choosing an accounting system or external GST/marketplace provider;
- deciding legal invoice-numbering scope or invoice issuance responsibilities;
- deciding costing policy for authoritative profitability;
- finalizing accounting posting semantics or tax treatment;
- enabling direct external API connections;
- provisioning paid services or deploying publicly;
- running destructive migrations or irreversible data transformations.

## Definition of done

A feature is done only when its acceptance criteria are met, relevant tests pass, failure/retry behavior is addressed, tenant authorization is tested, documentation is updated, and limitations are disclosed. If a test cannot be run, state that explicitly.

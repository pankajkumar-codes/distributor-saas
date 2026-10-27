# Team: invites, members and the audit log

LLD-2 part A (slice S2). The code is in `app/src/app/modules/identity/api_team.py`, and the migrations are identity's `202610261500_identity_invitations_r1.sql` and `202610261510_identity_audit_copy.sql`. Support access, TOTP recovery, the M16 client list and the audit CSV export come in parts B and C.

## Routes (all under `/api/v1`)

| Route | Permission | Notes |
|---|---|---|
| `POST /b/{id}/invitations` | `members.manage` | Needs an `Idempotency-Key`. Roles are admin, billing or CA (never owner). The mail goes out after commit. |
| `POST /b/{id}/invitations/{inv}/resend` | `members.manage` | Issues a new link (the old one stops working) and a fresh 7-day expiry. |
| `POST /b/{id}/invitations/{inv}/cancel` | `members.manage` | A retry gives the same answer. |
| `GET /me/invitations/{token}` | signed in | Preview. Anything that isn't a pending, unexpired invite to the caller's own email gets the same 404. |
| `POST /me/invitations/{token}/accept` | signed in | Needs the token **and** the caller's email (L2-2). A retry gives the same `business_id`. |
| `GET /b/{id}/members` | `members.manage` | Members (owners first) and pending invites. Names and emails come through `identity.member_profiles`. |
| `PATCH /b/{id}/members/{user_id}` | `members.manage` | Role change (L2-7). |
| `POST /b/{id}/members/{user_id}/deactivate` and `/reactivate` | `members.manage` | A reason is required. Reactivating gives back the member's previous role. |
| `GET /b/{id}/audit-log` | `audit.view` | Newest first, 50 per page, keyset cursor. Filters: `kind`, `actor`, `from`, `to` (Indian dates). |

## Rules

**Owner rules (409 `owner_rule`):**
- Only an owner can change, deactivate or reactivate an owner, or make someone an owner.
- The last active owner can't be demoted or deactivated, even by themselves.
- The T-013 trigger refuses the same writes if a route check is ever missed.

**Other refusals:**
- A CA's role changes only through a new invite, and nobody becomes a CA by a role change (409 `ca_needs_invite`).
- An invite to an active member gets 422 `already_member`.
- An invite to a deactivated member gets 409 `member_deactivated`, with the fix "Reactivate them with a reason".
- An invite to an email that already has an open invite gets 409 `invite_pending`.

**Daily invite limit.** At most 20 invite or resend mails per business in any 24 hours; more get 429 with `Retry-After`. The count comes from the business's own `member.invite` and `member.invite_resend` audit rows, inside the unit of work. A `rate.hit` bucket would have to be spent before the caller is checked, which would let an outsider use up a business's invites.

**Deactivation.** It takes effect on the member's next request to that business. Their sessions and their other businesses are untouched (L2-8).

**Invite status.** A BEFORE UPDATE trigger (`identity.guard_invitation_update`) allows only pending to cancelled, pending to expired (once the expiry has passed) and pending to accepted (only as `identity_auth`, inside `auth_accept_invitation`). Business, email and role never change, and the link, expiry and business name change only while pending. A second trigger (`identity.guard_invitation_insert`) refuses an invite inserted as anything but pending, or with acceptance or cancellation already filled in. `app_rw` can update only `status`, `expires_at`, `token_hash`, `last_sent_at`, `cancelled_at` and `cancelled_by`.

**Business name.** The invite keeps a snapshot of the business's display name (`business.interface.display_name`: trade name, else legal name, else GSTIN or enrolment number; the business row's name if there is no profile yet). The mail and the preview show the snapshot, and a resend refreshes it.

**Owner-rule errors.** The T-013 trigger raises SQLSTATE `IDO01`, and only that maps to 409 `owner_rule`. An RLS refusal (42501) stays an error.

**Tokens.** Invite tokens are 32 random bytes and are stored only as their sha256. No email, token or code goes into audit `data`.

## Audit log

- Every route writes through `platform_common.audit.record`.
- `member.accept` is written by `identity.auth_accept_invitation`, as `identity_auth`, under the `audit_auth_insert` policy.
- The deactivate and reactivate actions are named `members.deactivate` and `members.reactivate`, the names in the permissions matrix's reason-required list. LLD-2 §4.6 writes them as `member.*`.
- `identity/audit_labels.py` holds each action's label and kind, plus the target-to-screen links. A link is shown only when the caller's role can open that screen.

**The legacy copy.** `202610261510` copies `identity.audit_events` into `platform.audit_log`, keeping each row's id.
- A re-run copies nothing twice.
- Details that aren't a JSON object keep nothing.
- `platform.v_audit_log` then reads `platform.audit_log` only.
- `identity.audit_events` takes no more inserts: `ae_insert` is `with check (false)` and INSERT is revoked. Nothing is dropped.

## Not yet

- The hourly expiry job (LLD-0 §3.7): a pending invite past its date shows as `expired` and can't be accepted, but its status changes only when someone re-invites that email.
- The usage event `member_joined`: there is no usage-event table yet.
- Mail in AWS: SqsMailer is S0b. Locally the invite link lands in `build/mail/outbox.jsonl`.
- `/identity/tenants` (create, list, get) stays until S1's business routes replace it. Business creation now writes `business.create` to `platform.audit_log`.

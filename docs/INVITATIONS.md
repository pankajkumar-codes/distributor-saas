# Inviting a teammate (E0-1, plan T-004)

## Flow
1. An owner or admin invites an email address with a role (only an owner can invite
   an owner). The invitation is saved and audited first, then Cognito's
   `AdminCreateUser` emails the person a temporary password. If the person already has
   a login, no email is sent; the invitation is waiting for them when they sign in.
2. After signing in, the person sees their pending invitations
   (`GET /api/v1/identity/invitations`) and accepts one
   (`POST /api/v1/identity/invitations/{id}/accept`). That creates their membership with the
   invited role, email and display name.

Invitations are matched only on the caller's **verified** email claim. The web app must
send the Cognito **ID token** on these two calls, because access tokens carry no email.

## Rules
| Case | Result |
|---|---|
| Invite valid for | 7 days. Resend renews the 7 days and resends the email |
| Second invite to the same address while one is open (including expired) | 409, use resend |
| Address already belongs to a member | 409 "already a member" |
| Accept by someone whose verified email differs, or with no verified email | 404, same as a missing invitation |
| Accept an expired or revoked invitation | 410 |
| Accept twice by the same login | Same answer, one membership |
| Accept by a second login with the same email | 409 |
| The person has a deactivated membership in the tenant | 409; rejoining needs reactivation, not an invite |
| Cognito send fails | Invitation kept with `delivery: failed`; resend retries |
| Revoke | Retry-safe; frees the address for a new invitation |

Audit events: `invitation.created`, `invitation.resent`, `invitation.revoked`,
`invitation.accepted`.

## Row-level security (migration 0005)
The service sets `app.user_email` (verified email or empty) next to `app.user_sub` at the
start of every transaction. Invitations are visible to members of their tenant, and to
the addressee by email. A tenant's name is visible to someone holding a pending
invitation to it. Inserting an invitation requires membership of its tenant.

## Not done here
- **Infrastructure (Staff 2, D-040):** the S0b Terraform gives the API Lambda
  `cognito-idp:AdminCreateUser` on the user pool, the `COGNITO_USER_POOL_ID` variable,
  and a Cognito interface endpoint (TD-5). It is written but not applied, so invites
  can't be sent from AWS yet.
  Locally and in tests nothing is sent; the API records what would have gone out.
- The real Cognito call has not been exercised against AWS.
- Accepting inserts the invitee's own membership. Since T-013 (QA-DEF-001) only owners
  and admins may insert memberships, so this migration adds one more case to the
  `add_member` policy: the caller themselves, with exactly the role of a pending,
  unexpired invitation addressed to their verified email.


## R4-M1 and R4-M3: what is in place for team members by invitation (option (a) of D4)

The server side of R4 was built earlier (D-040 onward, LLD-2) and is checked again here against the R4 asks:

| Ask | Where it is |
|---|---|
| An admin creates a single-use, expiring invite link with a role | `POST /b/{id}/invitations` (owner or admin; only an owner can invite an owner): 32 random bytes, 7 days, one open invite per address, 20 mails a day per business. The role is one of the four fixed roles (D4 option (a)); no per-person permission tuning |
| The token is stored hashed and never logged | `identity.invitations.token_hash` (SHA-256 hex). `test_an_invite_token_never_reaches_a_log_an_audit_row_or_a_stored_column` runs the whole life of an invite and searches logs, audit rows and the table. The API Gateway access log records the route template, not the path, so a token in a link is not in it (infra/modules/api/main.tf) |
| The invitee accepts, new or existing user | `GET /me/invitations/{token}` and `POST /me/invitations/{token}/accept`: matched on the signed-in user's own email, so a forwarded link looks like an unknown one (AC2-7). A new person signs up first and then accepts; a retry returns the same business |
| Member list, change role, revoke | `GET /b/{id}/members` (members and pending invites), `PATCH /members/{user}` (role), `POST /members/{user}/deactivate` and `/reactivate` (reason required), `POST /invitations/{id}/resend` and `/cancel` |
| Audit | `member.invite`, `member.invite_resend`, `member.invite_cancel`, `member.accept`, role change, deactivate and reactivate, with no email or token in the row |
| Every route refuses a role without its permission | `app/tests/test_route_permissions_postgres.py` (R4-M3): every `/b/{business_id}` route declares exactly one `require(...)`, and each is called as every role that lacks it and as a non-member, and must answer the same 404 |

Not added in this slice: a "copy the link" option that shows the link to the admin instead of mailing it (the link is mailed, as designed), and per-person permissions (D4 options (b) and (c)).

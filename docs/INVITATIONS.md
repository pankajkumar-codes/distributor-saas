# Inviting a teammate (E0-1, plan T-004)

## Flow
1. An owner or admin invites an email address with a role (only an owner can invite
   an owner). The invitation is saved and audited first, then Cognito's
   `AdminCreateUser` emails the person a temporary password. If the person already has
   a login, no email is sent; the invitation is waiting for them when they sign in.
2. After signing in, the person sees their pending invitations
   (`GET /identity/invitations`) and accepts one
   (`POST /identity/invitations/{id}/accept`). That creates their membership with the
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

## Row-level security (migration 0003)
The service sets `app.user_email` (verified email or empty) next to `app.user_sub` at the
start of every transaction. Invitations are visible to members of their tenant, and to
the addressee by email. A tenant's name is visible to someone holding a pending
invitation to it. Inserting an invitation requires membership of its tenant.

## Not done here
- **Infrastructure (Staff):** the identity Lambda needs `cognito-idp:AdminCreateUser`
  on the user pool and the `COGNITO_USER_POOL_ID` variable. It also needs a network path
  to Cognito: Lambdas run in private subnets with no NAT, so this means either a
  Cognito interface endpoint or a NAT gateway. That is a cost decision, so nothing has
  been provisioned. Until then, invites can't be sent from AWS.
  Locally and in tests nothing is sent; the API records what would have gone out.
- The real Cognito call has not been exercised against AWS.
- When QA-DEF-001 (memberships insert policy is `WITH CHECK (true)`) is fixed, the new
  policy must still let an invitee insert their own membership when a matching pending
  invitation exists.

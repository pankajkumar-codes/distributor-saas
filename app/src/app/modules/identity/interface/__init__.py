"""What identity offers the rest of the app (LLD-1 §2, §6).

`resolve_principal` is the principal resolver the API registers with platform_common
(`set_principal_resolver`) at start-up: one call to identity.auth_resolve per unit of
work checks the caller's session and, for a business route, their membership or a
support grant.

The business functions (S1-d1) create a business with its owner and profile, and list
the caller's memberships for /me and the sign-in reply.
"""

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.business import interface as business
from app.modules.refdata import value_on
from platform_common import audit
from platform_common.auth import Caller, debug_env
from platform_common.errors import Deny, Invalid
from platform_common.ids import uuid7
from platform_common.uow import Principal, UnitOfWork

# LLD-1 L1-6: the access token's origin_jti, with event_id as the fallback.
SESSION_KEY_CLAIMS = ("origin_jti", "event_id")

_RESOLVE = text(
    "select user_id, session_id, role, support_grant_id, deny"
    " from identity.auth_resolve(:kind, :value, :sub, :business_id, :touch)"
)


def session_key_from_claims(claims) -> tuple[str, str] | None:
    """The (key_kind, key_value) an access token's claims name, or None. Sign-up opens
    the session under this key and the resolver looks it up the same way."""
    for kind in SESSION_KEY_CLAIMS:
        value = claims.get(kind)
        if value:
            return kind, str(value)
    return None


def session_key(tx: Session, caller: Caller) -> tuple[str | None, str | None]:
    """The (key_kind, key_value) of the caller's session row, from the token's claims.

    A caller named by X-Debug-User has no token. Locally and in tests only, it gets a
    debug session from identity.dev_ensure_session, which only migrator.local creates.
    """
    key = session_key_from_claims(caller.claims)
    if key:
        return key
    if debug_env() and not caller.claims:
        tx.execute(text("select identity.dev_ensure_session(:sub)"), {"sub": caller.user_sub})
        return "sid", f"debug:{caller.user_sub}"
    return None, None


def resolve_principal(
    tx: Session, caller: Caller, business_id: uuid.UUID | None, request_id: str, *, touch: bool = True
) -> Principal:
    """The checked caller, or Deny: session_invalid (401), not_found, not_member, support_no_grant (404)."""
    kind, value = session_key(tx, caller)
    row = tx.execute(
        _RESOLVE,
        {"kind": kind, "value": value, "sub": caller.user_sub, "business_id": business_id, "touch": touch},
    ).one_or_none()
    if row is None:
        raise Deny("session_invalid")  # no users row for this sub
    if row.deny is not None:
        raise Deny(row.deny)
    return Principal(
        user_sub=caller.user_sub,
        request_id=request_id,
        user_id=row.user_id,
        session_id=row.session_id,
        business_id=business_id,
        role=row.role,
        support_grant_id=row.support_grant_id,
    )


# businesses (S1-d1) ------------------------------------------------------------------


@dataclass(frozen=True)
class MembershipCard:
    business_id: uuid.UUID
    display_name: str
    gstin: str | None
    role: str


@dataclass(frozen=True)
class CreatedBusiness:
    business_id: uuid.UUID
    warnings: list[str]


_OWNED = text(
    "select count(*) from identity.memberships"
    " where user_id = :me and role = 'owner' and status = 'active' and identity.is_active_member(business_id)"
)


def create_business(uow: UnitOfWork, profile_in: business.NewBusinessProfile, *, today: date) -> CreatedBusiness:
    """LLD-1 §5.10, in the caller's /me unit of work. It takes the unit of work, not just
    its transaction, because it binds it to the new business as owner."""
    tx, me = uow.tx, uow.principal.user_id
    if me is None:
        raise RuntimeError("create_business needs a signed-in user")
    # One create at a time per user, so two concurrent requests can't both pass the limit [RM41-8].
    tx.execute(text("select pg_advisory_xact_lock(hashtextextended('identity.create_business:' || :me, 0))"),
               {"me": str(me)})
    limit = value_on(tx, "identity.max_owned_businesses", today)
    if tx.execute(_OWNED, {"me": me}).scalar() >= limit:
        raise Invalid("business_limit", f"you can own at most {limit} businesses")
    business_id = uuid7()
    uow.enter_new_business(business_id)
    tx.execute(text("insert into identity.businesses (id, created_by) values (:b, :me)"), {"b": business_id, "me": me})
    # Passes m_insert only through identity.is_bootstrap_owner: the creator, no member yet.
    tx.execute(
        text("insert into identity.memberships (id, business_id, user_id, role, status)"
             " values (:id, :b, :me, 'owner', 'active')"),
        {"id": uuid7(), "b": business_id, "me": me},
    )
    warnings = business.create_profile(tx, business_id, profile_in, by=me, today=today)
    audit.record(uow, "business.create", "business", business_id,
                 data={"registration_kind": profile_in.registration.kind})
    return CreatedBusiness(business_id, warnings)


_MEMBERSHIPS = text(
    "select m.business_id, m.role from identity.memberships m"
    " join identity.businesses b on b.id = m.business_id"
    " where m.user_id = :u and m.status = 'active' and b.status <> 'closed'"
)


def list_my_businesses(tx: Session, user_id: uuid.UUID) -> list[MembershipCard]:
    """The user's active memberships with each business's card, by display name.

    Runs as app_ro (UnitOfWork.become_read_only first): biz_member_ro and the business
    profile's profile_card_ro are app_ro policies (LLD-1 §3.4, §4), so under app_rw only
    the bound business would show. app.user_id must be `user_id`.
    """
    if tx.execute(text("select current_user")).scalar() != "app_ro":
        raise RuntimeError("list_my_businesses reads as app_ro; call uow.become_read_only() first")
    roles = {r.business_id: r.role for r in tx.execute(_MEMBERSHIPS, {"u": user_id})}
    cards = business.business_card(tx, list(roles))
    return sorted(
        (MembershipCard(c.business_id, c.display_name, c.gstin, roles[c.business_id]) for c in cards),
        key=lambda m: (m.display_name.casefold(), str(m.business_id)),
    )


def member_role(tx: Session, business_id: uuid.UUID, user_id: uuid.UUID) -> str | None:
    """The user's active role in the bound business, or None."""
    return tx.execute(
        text("select role from identity.memberships where business_id = :b and user_id = :u and status = 'active'"),
        {"b": business_id, "u": user_id},
    ).scalar()


def greeting_name(tx: Session) -> str | None:
    """The signed-in user's own name for Home's greeting (LLD-1 §10), or None if unset."""
    return tx.execute(
        text("select name from identity.users where id = nullif(current_setting('app.user_id', true), '')::uuid")
    ).scalar()


def team_started(tx: Session) -> bool:
    """Home's invite_ca_or_teammate item until LLD-2's own signal (LLD-1 §10): the bound
    business has a second active member or a pending invite. Invites are visible to
    owners and admins only (inv_ro), so for other roles only memberships count."""
    return bool(tx.execute(
        text("select (select count(*) from identity.memberships where status = 'active'"
             "         and business_id = nullif(current_setting('app.tenant_id', true), '')::uuid) > 1"
             " or exists (select 1 from identity.invitations where status = 'pending' and expires_at > now()"
             "         and business_id = nullif(current_setting('app.tenant_id', true), '')::uuid)")
    ).scalar())

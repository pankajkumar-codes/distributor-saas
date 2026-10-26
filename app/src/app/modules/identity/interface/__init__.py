"""What identity offers the rest of the app (LLD-1 §2, §6).

`resolve_principal` is the principal resolver the API registers with platform_common
(`set_principal_resolver`) at start-up: one call to identity.auth_resolve per unit of
work checks the caller's session and, for a business route, their membership or a
support grant.
"""

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from platform_common.auth import Caller, debug_env
from platform_common.errors import Deny
from platform_common.uow import Principal

# LLD-1 L1-6: the access token's origin_jti, with event_id as the fallback.
SESSION_KEY_CLAIMS = ("origin_jti", "event_id")

_RESOLVE = text(
    "select user_id, session_id, role, support_grant_id, deny"
    " from identity.auth_resolve(:kind, :value, :sub, :business_id, :touch)"
)


def session_key(tx: Session, caller: Caller) -> tuple[str | None, str | None]:
    """The (key_kind, key_value) of the caller's session row, from the token's claims.

    A caller named by X-Debug-User has no token. Locally and in tests only, it gets a
    debug session from identity.dev_ensure_session, which only migrator.local creates.
    """
    for kind in SESSION_KEY_CLAIMS:
        value = caller.claims.get(kind)
        if value:
            return kind, str(value)
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

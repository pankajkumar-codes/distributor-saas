"""The audit log (LLD-0 §3.6, HLD §5.2).

`record` inserts in the caller's transaction, so the audit row commits or rolls back
with the change it describes. The business, user and support grant come from the unit
of work, never from the caller. `data` passes through a per-action key allowlist:
amounts, emails, phones, codes and tokens are never written to it.
"""

import json
import uuid

from sqlalchemy import text

from .ids import uuid7

# action -> keys allowed in `data`. An action missing here can't be recorded.
ALLOWED_DATA: dict[str, frozenset[str]] = {
    "auth.signup": frozenset(),
    "auth.signin": frozenset({"totp"}),
    "auth.password_reset": frozenset(),
    "auth.password_change": frozenset(),
    "auth.totp_on": frozenset(),
    "auth.totp_off": frozenset(),
    "auth.signout_all": frozenset({"sessions"}),
    "business.create": frozenset({"registration_kind"}),
}

_INSERT = text(
    "insert into platform.audit_log"
    " (id, business_id, user_id, support_grant_id, action, target_kind, target_id, reason, data, request_id)"
    " values (:id, :business_id, :user_id, :grant, :action, :target_kind, :target_id, :reason,"
    " cast(:data as jsonb), :request_id)"
)


def record(
    uow,
    action: str,
    target_kind: str,
    target_id: uuid.UUID | None = None,
    *,
    reason: str | None = None,
    data: dict | None = None,
    user_level: bool = False,
) -> uuid.UUID:
    """Write one audit row in `uow`'s transaction and return its ID.

    `user_level` rows (sign-in, TOTP) have no business even inside a business request.
    """
    if action not in ALLOWED_DATA:
        raise ValueError(f"audit action {action!r} is not registered")
    extra = set(data or {}) - ALLOWED_DATA[action]
    if extra:
        raise ValueError(f"audit data keys not allowed for {action}: {sorted(extra)}")
    p = uow.principal
    if p.user_id is None and (user_level or p.business_id is None):
        raise ValueError("a user-level audit row needs a signed-in user")
    row_id = uuid7()
    uow.tx.execute(
        _INSERT,
        {
            "id": row_id,
            "business_id": None if user_level else p.business_id,
            "user_id": p.user_id,
            "grant": None if user_level else p.support_grant_id,
            "action": action,
            "target_kind": target_kind,
            "target_id": target_id,
            "reason": reason,
            "data": json.dumps(data or {}, sort_keys=True),
            "request_id": p.request_id,
        },
    )
    return row_id

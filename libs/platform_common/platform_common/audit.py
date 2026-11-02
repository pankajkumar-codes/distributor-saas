"""The audit log (LLD-0 §3.6, HLD §5.2).

`record` inserts in the caller's transaction, so the audit row commits or rolls back
with the change it describes. The business, user and support grant come from the unit
of work, never from the caller. `data` passes through a per-action key allowlist:
amounts, emails, phones, codes and tokens are never written to it. Actions in
permissions.REASON_REQUIRED need a non-blank reason (LLD-0 §3.3).
"""

import json
import uuid

from sqlalchemy import text

from .ids import uuid7
from .permissions import REASON_REQUIRED, require_reason

# action -> keys allowed in `data`. An action missing here can't be recorded.
ALLOWED_DATA: dict[str, frozenset[str]] = {
    "auth.signup": frozenset(),
    "auth.signin": frozenset({"totp"}),
    "auth.password_reset": frozenset(),
    "auth.password_change": frozenset(),
    "auth.totp_on": frozenset(),
    "auth.totp_off": frozenset(),
    "auth.signout": frozenset(),
    "auth.signout_all": frozenset({"sessions"}),
    "business.create": frozenset({"registration_kind"}),
    # Business profile (LLD-1 §8.2, L1-13, L1-14).
    "business.profile_update": frozenset({"fields"}),
    "business.turnover_band_set": frozenset({"fy", "band"}),
    "business.frequency_set": frozenset({"frequency", "effective_from", "warnings"}),
    "business.channels_update": frozenset({"enabled"}),
    "business.gstin_locked": frozenset(),
    # Team (LLD-2 §4). member.accept is written by identity.auth_accept_invitation.
    "member.invite": frozenset({"role"}),
    "member.invite_resend": frozenset(),
    "member.invite_cancel": frozenset(),
    "member.accept": frozenset({"role"}),
    "member.role_change": frozenset({"from", "to"}),
    # Reason-required actions (permissions.yaml); their data keys come with their slices.
    **{action: frozenset() for action in REASON_REQUIRED},
    # Catalog (LLD-3 §9): IDs, product codes, changed field names and GST rate values only.
    "product.created": frozenset({"code"}),
    "product.updated": frozenset({"code", "fields"}),
    "product.archived": frozenset({"code"}),
    "product.unarchived": frozenset({"code"}),
    "product.deleted": frozenset({"code"}),
    "product.rate_added": frozenset({"rate_id", "rate", "valid_from"}),
    "product.rate_voided": frozenset({"rate_id", "rate", "valid_from"}),
    "product.rate_confirmed": frozenset({"rate_id", "rate"}),
    "product.rate_unconfirmed": frozenset({"rate_id", "rate"}),
    # No customer name, address or GSTIN in audit data (LLD-3 §9): field names only.
    "customer.created": frozenset(),
    "customer.updated": frozenset({"fields"}),
    "customer.archived": frozenset(),
    "customer.unarchived": frozenset(),
    "customer.deleted": frozenset(),
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
    if action in REASON_REQUIRED:
        reason = require_reason(action, reason)
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

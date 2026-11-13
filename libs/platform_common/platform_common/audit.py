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
    # Written by identity.auth_totp_recovery_complete, not by record(): the row is the
    # account's own, and names the support user who removed its TOTP (LLD-2 §6.3).
    "auth.totp_removed_by_support": frozenset({"support_user_id"}),
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
    # One row per request under a support grant (LLD-2 §6.2), written by business_uow.
    "support.view": frozenset({"method", "route_template", "object_id"}),
    "support.grant": frozenset({"expires_at", "replaced"}),  # replaced: the grant it ended, if any
    "support.revoke": frozenset(),
    # The audit log's CSV export logs itself with its filters (LLD-2 §7 [D, RM42-11]).
    "audit.export": frozenset({"kind", "actor", "from", "to"}),
    # Reason-required actions (permissions.yaml); their data keys come with their slices.
    **{action: frozenset() for action in REASON_REQUIRED},
    # Catalog (LLD-3 §9): IDs, product codes, changed field names and GST rate values only.
    "product.created": frozenset({"code", "import_run_id", "row_number"}),
    "product.updated": frozenset({"code", "fields", "import_run_id", "row_number"}),
    "product.archived": frozenset({"code"}),
    "product.unarchived": frozenset({"code", "import_run_id", "row_number"}),
    "product.deleted": frozenset({"code"}),
    "product.rate_added": frozenset({"rate_id", "rate", "valid_from", "import_run_id", "row_number"}),
    "product.rate_voided": frozenset({"rate_id", "rate", "valid_from"}),
    "product.rate_confirmed": frozenset({"rate_id", "rate"}),
    "product.rate_unconfirmed": frozenset({"rate_id", "rate"}),
    # No customer name, address or GSTIN in audit data (LLD-3 §9): field names only.
    "customer.created": frozenset(),
    "customer.updated": frozenset({"fields"}),
    "customer.archived": frozenset(),
    "customer.unarchived": frozenset(),
    "customer.deleted": frozenset(),
    # Drafts are not GST records; no buyer or amounts in audit data.
    "draft.created": frozenset(),
    "draft.updated": frozenset(),
    "draft.deleted": frozenset(),
    # Finalize (LLD-4 §12): numbers, kinds and codes only; no amounts, names or GSTINs.
    "document.finalized": frozenset({"number", "kind", "practice", "draft_id"}),
    "document.pos_override": frozenset({"computed_pos", "chosen_pos"}),  # reason required (G16)
    "catalog.import_applied": frozenset({"counts"}),  # row counts only
    "catalog.import_superseded": frozenset({"superseded_by"}),
    # Uploads (LLD-7 §11): the section and ids only, never a file's contents or name.
    "imports.upload_received": frozenset({"section", "upload_id"}),
    "imports.rejected": frozenset({"section", "upload_id", "reason"}),
    "imports.run_discarded": frozenset({"run_id", "section"}),
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

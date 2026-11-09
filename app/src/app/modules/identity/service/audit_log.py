"""The business's audit log as the owner and admin read it (LLD-2 §7): one query for the
screen's pages and the CSV export, so both show the same rows the same way.

Reads platform.v_audit_log under the business's row-level security (rows written under a
support grant are support's, never a member's). Names come from identity.member_profiles,
which needs the caller to be an active member of the business.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import text

from platform_common import audit
from platform_common.clock import IST
from platform_common.uow import UnitOfWork

from .. import audit_labels


@dataclass(frozen=True)
class Filters:
    kind: str | None
    actor: uuid.UUID | None
    date_from: date  # Indian dates, both ends included
    date_to: date

    def as_data(self) -> dict:
        """For the audit.export row (no email, no amount, no code)."""
        return {"kind": self.kind, "actor": None if self.actor is None else str(self.actor),
                "from": self.date_from.isoformat(), "to": self.date_to.isoformat()}


def ist_midnight(day: date, plus_days: int = 0) -> datetime:
    return datetime.combine(day + timedelta(days=plus_days), time(), IST).astimezone(UTC)


def rows(uow: UnitOfWork, f: Filters, *, after: tuple[datetime, uuid.UUID] | None, limit: int) -> list:
    """Newest first, at most `limit` rows after the (at, id) position `after`."""
    bid = uow.principal.business_id
    where = ["a.business_id = :b", "a.at >= :start", "a.at < :end"]
    params: dict = {"b": bid, "start": ist_midnight(f.date_from), "end": ist_midnight(f.date_to, 1), "limit": limit}
    if f.kind is not None:
        where.append("a.action = any(:actions)")
        params["actions"] = audit_labels.actions_of_kind(f.kind)
    if f.actor is not None:
        where.append("a.user_id = :actor and a.support_grant_id is null")
        params["actor"] = f.actor
    if after is not None:
        params["c_at"], params["c_id"] = after
        where.append("(a.at, a.id) < (:c_at, :c_id)")
    return uow.tx.execute(
        text(
            "select a.id, a.at, a.user_id, a.support_grant_id, a.action, a.target_kind, a.target_id,"
            " a.reason, a.data, coalesce(p.name, p.email) as actor_name"
            " from platform.v_audit_log a"
            " left join identity.member_profiles(array("
            "     select user_id from identity.memberships where business_id = :b)) p"
            "   on p.user_id = a.user_id and a.support_grant_id is null"
            f" where {' and '.join(where)}"
            " order by a.at desc, a.id desc limit :limit"
        ),
        params,
    ).all()


def actor_of(r) -> tuple[str, str]:
    """(kind, name): support rows are "Support team", rows with no user are "System"."""
    if r.support_grant_id is not None:
        return "support", "Support team"
    if r.user_id is None:
        return "system", "System"
    return "member", r.actor_name or "Former member"


def details_of(r) -> dict:
    """Only the allowlisted data keys for the row's action (LLD-0 §3.6)."""
    allowed = audit.ALLOWED_DATA.get(r.action, frozenset())
    return {k: v for k, v in (r.data or {}).items() if k in allowed}

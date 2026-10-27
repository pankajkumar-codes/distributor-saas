"""Team routes: invites, members and the audit log (LLD-2 §3, §4, §7).

Every route runs in one unit of work. Business routes get theirs from `business_uow`,
which has already checked the caller's active membership and set `app.tenant_id`, so
row-level security scopes every statement here to that business; the explicit
`business_id` filters are defence in depth. The invitee's preview and accept run as
the signed-in user (`me_uow`) through identity_auth's definer functions, which match
the link's token and the user's own email (L2-2).

Refusals: an object outside the business, or a role without the permission, is the
same 404 as an unknown business. The owner rules are 409 `owner_rule` with a message,
since the caller can already see the member list (§3).
"""

import base64
import hashlib
import os
import secrets
import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from platform_common import audit
from platform_common.auth import debug_env
from platform_common.clock import IST
from platform_common.errors import AppError, Conflict, Deny, Invalid, RateLimited
from platform_common.idempotency import run_once
from platform_common.ids import uuid7
from platform_common.mailer import Mailer, send_after_commit
from platform_common.paging import DateRange, PageParams, date_range, page_params
from platform_common.permissions import Permission, Role, has_permission, matrix, require, require_reason
from platform_common.uow import BusinessUoW, MeUoW, UnitOfWork, parse_id

from app.modules.business.interface import display_name

from . import audit_labels
from .providers import mailer

router = APIRouter(tags=["team"])

# Provisional refdata (L2-9; the PO owns both). They move to refdata rows when it lands.
INVITE_EXPIRY_DAYS = 7  # identity.invite_expiry_days
INVITES_PER_BUSINESS_PER_DAY = 20  # identity.invites_per_business_per_day
AUDIT_PAGE = 50

ROLE_LABELS = {"owner": "Owner", "admin": "Admin", "billing": "Billing", "ca": "CA"}

def app_origin() -> str:
    origin = os.environ.get("APP_ORIGIN")
    if origin:
        return origin.rstrip("/")
    if debug_env():
        return "http://localhost:5173"
    raise RuntimeError("APP_ORIGIN is not set")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _business(uow: UnitOfWork) -> uuid.UUID:
    return uow.principal.business_id


# --- Invitations (§4.1-4.3) -----------------------------------------------------


class InviteIn(BaseModel):
    # Loose on purpose: the mail reaching the address is the real check.
    email: str = Field(max_length=254, pattern=r"^\s*[^@\s]+@[^@\s]+\.[^@\s]+\s*$")
    role: Literal["admin", "billing", "ca"]
    display_name: str | None = Field(default=None, min_length=1, max_length=200)


class InviteOut(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    status: str  # pending | accepted | cancelled | expired
    expires_at: datetime


_INVITE_COLUMNS = "id, email, role, status, expires_at"


def _invite_out(row) -> dict:
    """`row` carries the database's now(), so "expired" never depends on the app's clock."""
    status = row.status
    if status == "pending" and row.expires_at <= row.now:
        status = "expired"
    return InviteOut(id=row.id, email=row.email, role=row.role, status=status, expires_at=row.expires_at).model_dump(
        mode="json"
    )


def _check_invite_limit(uow: UnitOfWork) -> None:
    """At most INVITES_PER_BUSINESS_PER_DAY invite mails per business in any 24 hours.

    Counted from the business's own audit rows, inside the unit of work, after the
    membership check: a rate.hit bucket would have to be spent before the caller is
    known, so an outsider could use up a business's invites.
    """
    sent, oldest, now = uow.tx.execute(
        text(
            "select count(*), min(at), now() from platform.audit_log"
            " where business_id = :b and action in ('member.invite', 'member.invite_resend')"
            " and at > now() - interval '1 day'"
        ),
        {"b": _business(uow)},
    ).one()
    if sent >= INVITES_PER_BUSINESS_PER_DAY:
        raise RateLimited(retry_after=max(1, int((oldest + timedelta(days=1) - now).total_seconds()) + 1))


def _lock_invites(uow: UnitOfWork) -> None:
    # Serialises invites in one business: the daily count and the one-open-invite rule.
    uow.tx.execute(
        text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"identity.invite:{_business(uow)}"},
    )


def _business_name(uow: UnitOfWork) -> str | None:
    """The name the invite mail and preview show, snapshotted on the invite (LLD-2):
    the business profile's display name, else the business row's name. Cut to the
    column's 200 characters, so a longer display name can't fail the invite."""
    name = display_name(uow.tx) or uow.tx.execute(
        text("select name from identity.businesses where id = :b"), {"b": _business(uow)}
    ).scalar()
    return name[:200] if name else name


def _send_invite(uow: UnitOfWork, mail: Mailer, email: str, role: str, token: str, business_name: str | None) -> None:
    inviter = uow.tx.execute(
        text("select coalesce(name, email) from identity.users where id = :me"), {"me": uow.principal.user_id}
    ).scalar_one()
    send_after_commit(
        uow,
        mail,
        "invitation",
        email,
        {
            "business_name": business_name or "",
            "inviter_name": inviter,
            "role_label": ROLE_LABELS[role],
            "link": f"{app_origin()}/invite/{token}",
        },
    )


def _member_emails(uow: UnitOfWork) -> dict[str, str]:
    """email -> membership status, for this business's members (through member_profiles)."""
    rows = uow.tx.execute(
        text(
            "select p.email, m.status from identity.memberships m"
            " join identity.member_profiles(array(select user_id from identity.memberships where business_id = :b)) p"
            " on p.user_id = m.user_id where m.business_id = :b"
        ),
        {"b": _business(uow)},
    ).all()
    return {r.email: r.status for r in rows}


def _create_invite(uow: UnitOfWork, mail: Mailer, body: InviteIn) -> dict:
    bid = _business(uow)
    email = body.email.strip().lower()
    _lock_invites(uow)
    status = _member_emails(uow).get(email)
    if status == "active":
        raise Invalid("already_member", "This person is already a member", field="email")
    if status == "deactivated":
        raise Conflict(
            "member_deactivated", "This person was deactivated here", fix="Reactivate them with a reason"
        )
    pending = uow.tx.execute(
        text(
            "select id, expires_at <= now() as lapsed from identity.invitations"
            " where business_id = :b and email = :e and status = 'pending' for update"
        ),
        {"b": bid, "e": email},
    ).one_or_none()
    if pending is not None and not pending.lapsed:
        raise Conflict("invite_pending", "This email already has an open invite", fix="Resend it")
    _check_invite_limit(uow)
    if pending is not None:
        # The hourly job (LLD-0 §3.7) isn't running yet; a lapsed invite is closed here.
        uow.tx.execute(text("update identity.invitations set status = 'expired' where id = :i"), {"i": pending.id})

    token = secrets.token_urlsafe(32)
    invite_id = uuid7()
    business_name = _business_name(uow)
    row = uow.tx.execute(
        text(
            "insert into identity.invitations (id, business_id, email, display_name, role, status, token_hash,"
            " invited_by_user, expires_at, last_sent_at, business_name)"
            " values (:id, :b, :e, :n, :r, 'pending', :h, :me, now() + make_interval(days => :days), now(), :bn)"
            f" returning {_INVITE_COLUMNS}, now()"
        ),
        {
            "id": invite_id,
            "b": bid,
            "e": email,
            "n": body.display_name,
            "r": body.role,
            "h": token_hash(token),
            "me": uow.principal.user_id,
            "bn": business_name,
            "days": INVITE_EXPIRY_DAYS,
        },
    ).one()
    audit.record(uow, "member.invite", "invitation", invite_id, data={"role": body.role})
    _send_invite(uow, mail, email, body.role, token, business_name)
    return _invite_out(row)


@router.post(
    "/b/{business_id}/invitations",
    status_code=201,
    response_model=InviteOut,
    dependencies=[Depends(require(Permission.MEMBERS_MANAGE))],
)
def invite(
    body: InviteIn,
    uow: BusinessUoW,
    mail: Annotated[Mailer, Depends(mailer)],
    request: Request,
    idempotency_key: str | None = Header(None),
):
    return run_once(
        uow.tx,
        _business(uow),
        idempotency_key,
        method="POST",
        route=request.scope["route"].path,
        payload=body.model_dump(mode="json"),
        operation=lambda: _create_invite(uow, mail, body),
    )


def _locked_invite(uow: UnitOfWork, invitation_id: str):
    row = uow.tx.execute(
        text(
            f"select {_INVITE_COLUMNS}, now() from identity.invitations"
            " where id = :i and business_id = :b for update"
        ),
        {"i": parse_id(invitation_id), "b": _business(uow)},
    ).one_or_none()
    if row is None:
        raise Deny("not_found")
    return row


@router.post(
    "/b/{business_id}/invitations/{invitation_id}/resend",
    response_model=InviteOut,
    dependencies=[Depends(require(Permission.MEMBERS_MANAGE))],
)
def resend_invite(invitation_id: str, uow: BusinessUoW, mail: Annotated[Mailer, Depends(mailer)]):
    """A new link (the old one stops working) and a fresh expiry (§4.2)."""
    _lock_invites(uow)
    inv = _locked_invite(uow, invitation_id)
    if inv.status != "pending":
        raise Conflict("invite_not_pending", f"This invite is {inv.status}", fix="Send a new invite")
    _check_invite_limit(uow)
    token = secrets.token_urlsafe(32)
    business_name = _business_name(uow)  # refreshed, in case the business was renamed
    row = uow.tx.execute(
        text(
            "update identity.invitations set token_hash = :h, expires_at = now() + make_interval(days => :days),"
            f" last_sent_at = now(), business_name = :bn where id = :i returning {_INVITE_COLUMNS}, now()"
        ),
        {"h": token_hash(token), "days": INVITE_EXPIRY_DAYS, "bn": business_name, "i": inv.id},
    ).one()
    audit.record(uow, "member.invite_resend", "invitation", inv.id)
    _send_invite(uow, mail, inv.email, inv.role, token, business_name)
    return _invite_out(row)


@router.post(
    "/b/{business_id}/invitations/{invitation_id}/cancel",
    response_model=InviteOut,
    dependencies=[Depends(require(Permission.MEMBERS_MANAGE))],
)
def cancel_invite(invitation_id: str, uow: BusinessUoW):
    inv = _locked_invite(uow, invitation_id)
    if inv.status == "cancelled":
        return _invite_out(inv)  # a retry: same answer, no second audit row
    if inv.status != "pending":
        raise Conflict("invite_not_pending", f"This invite is {inv.status}")
    row = uow.tx.execute(
        text(
            "update identity.invitations set status = 'cancelled', cancelled_at = now(), cancelled_by = :me"
            f" where id = :i returning {_INVITE_COLUMNS}, now()"
        ),
        {"me": uow.principal.user_id, "i": inv.id},
    ).one()
    audit.record(uow, "member.invite_cancel", "invitation", inv.id)
    return _invite_out(row)


# --- Accepting (§4.4) ------------------------------------------------------------


class InvitePreviewOut(BaseModel):
    business_name: str | None
    role: str
    inviter_name: str | None
    expires_at: datetime


class AcceptOut(BaseModel):
    business_id: uuid.UUID


@router.get("/me/invitations/{token}", response_model=InvitePreviewOut)
def preview_invite(token: str, uow: MeUoW):
    row = uow.tx.execute(
        text("select * from identity.auth_invitation_preview(:h)"), {"h": token_hash(token)}
    ).one_or_none()
    if row is None:
        raise Deny("not_found")  # unknown, expired, cancelled, resent-away or someone else's
    return InvitePreviewOut(
        business_name=row.business_name, role=row.role, inviter_name=row.inviter_name, expires_at=row.expires_at
    )


@router.post("/me/invitations/{token}/accept", response_model=AcceptOut)
def accept_invite(token: str, uow: MeUoW):
    business_id = uow.tx.scalar(
        text("select identity.auth_accept_invitation(:h, :m, :a)"),
        {"h": token_hash(token), "m": uuid7(), "a": uuid7()},
    )
    if business_id is None:
        raise Deny("not_found")
    return AcceptOut(business_id=business_id)


# --- Members (§4.5, §4.6) --------------------------------------------------------


class MemberOut(BaseModel):
    user_id: uuid.UUID
    name: str | None
    email: str | None
    role: str
    status: str
    can_do: list[str]
    deactivated_at: datetime | None = None
    deactivated_by_name: str | None = None
    deactivation_reason: str | None = None


class MembersOut(BaseModel):
    members: list[MemberOut]
    invites: list[InviteOut]


def can_do(role: str) -> list[str]:
    """The role table's rows this role has, in the matrix's order (the Team tab's text)."""
    return [entry["row"] for name, entry in matrix()["permissions"].items() if role in entry["roles"]]


_MEMBER_SELECT = """
    select m.user_id, p.name, p.email, m.role, m.status, m.deactivated_at, m.deactivation_reason,
           coalesce(d.name, d.email) as deactivated_by_name
    from identity.memberships m
    left join identity.member_profiles(array(
        select user_id from identity.memberships where business_id = :b
    )) p on p.user_id = m.user_id
    left join identity.member_profiles(array(
        select deactivated_by from identity.memberships where business_id = :b and deactivated_by is not null
    )) d on d.user_id = m.deactivated_by
    where m.business_id = :b
"""


def _member_out(row) -> MemberOut:
    return MemberOut(
        user_id=row.user_id,
        name=row.name,
        email=row.email,
        role=row.role,
        status=row.status,
        can_do=can_do(row.role),
        deactivated_at=row.deactivated_at,
        deactivated_by_name=row.deactivated_by_name,
        deactivation_reason=row.deactivation_reason,
    )


@router.get(
    "/b/{business_id}/members",
    response_model=MembersOut,
    dependencies=[Depends(require(Permission.MEMBERS_MANAGE))],
)
def list_members(uow: BusinessUoW, page: PageParams = Depends(page_params)):
    bid = _business(uow)
    members = uow.tx.execute(
        text(
            _MEMBER_SELECT + " order by m.role = 'owner' desc, lower(coalesce(p.name, p.email)), m.user_id"
            " limit :limit offset :offset"
        ),
        {"b": bid, "limit": page.limit, "offset": page.offset},
    ).all()
    invites = uow.tx.execute(
        text(
            f"select {_INVITE_COLUMNS}, now() from identity.invitations"
            " where business_id = :b and status = 'pending' order by created_at"
        ),
        {"b": bid},
    ).all()
    return MembersOut(
        members=[_member_out(m) for m in members],
        invites=[InviteOut(**_invite_out(i)) for i in invites],
    )


class RoleIn(BaseModel):
    role: Role


class ReasonIn(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


def _lock_member(uow: UnitOfWork, user_id: str):
    """The target row and the business's active owners, locked in one order (owners
    first), so two owners can't demote or deactivate each other at once."""
    bid = _business(uow)
    target = parse_id(user_id)
    owners = uow.tx.execute(
        text(
            "select user_id from identity.memberships where business_id = :b and role = 'owner'"
            " and status = 'active' order by user_id for update"
        ),
        {"b": bid},
    ).all()
    row = uow.tx.execute(
        text(_MEMBER_SELECT + " and m.user_id = :u for update of m"), {"b": bid, "u": target}
    ).one_or_none()
    if row is None:
        raise Deny("not_found")
    return row, len(owners)


def _caller_is_owner(uow: UnitOfWork) -> bool:
    return uow.principal.role == "owner"


def _owner_rule(message: str) -> Conflict:
    return Conflict("owner_rule", message)


ONLY_OWNER = "Only an owner can change an owner"
NEEDS_OWNER = "A business needs at least one owner"


# T-013's trigger raises its own SQLSTATE (202610270100); RLS refusals are 42501 and
# must not read as an owner rule.
OWNER_RULE_SQLSTATE = "IDO01"


def _update_member(uow: UnitOfWork, sql: str, params: dict) -> None:
    """The T-013 trigger is the database backstop for the owner rules; if it ever
    refuses what the checks above let through, the caller still gets owner_rule."""
    try:
        with uow.tx.begin_nested():
            uow.tx.execute(text(sql), params)
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) == OWNER_RULE_SQLSTATE:
            raise _owner_rule(ONLY_OWNER) from None
        raise


@router.patch(
    "/b/{business_id}/members/{user_id}",
    response_model=MemberOut,
    dependencies=[Depends(require(Permission.MEMBERS_MANAGE))],
)
def change_role(user_id: str, body: RoleIn, uow: BusinessUoW):
    """L2-7. A CA's role changes only through a fresh invite (PO, RM-4.2)."""
    member, owners = _lock_member(uow, user_id)
    new = body.role.value
    if member.role == new:
        return _member_out(member)
    if member.role == "ca" or new == "ca":
        raise Conflict("ca_needs_invite", "A CA's role changes only through a new invite", fix="Send a new invite")
    if (member.role == "owner" or new == "owner") and not _caller_is_owner(uow):
        raise _owner_rule(ONLY_OWNER)
    if member.status != "active":
        raise Conflict("member_deactivated", "This member is deactivated", fix="Reactivate them first")
    if member.role == "owner" and owners <= 1:
        raise _owner_rule(NEEDS_OWNER)
    _update_member(
        uow,
        "update identity.memberships set role = :r, role_changed_at = now(), role_changed_by = :me"
        " where business_id = :b and user_id = :u",
        {"r": new, "me": uow.principal.user_id, "b": _business(uow), "u": member.user_id},
    )
    audit.record(uow, "member.role_change", "member", member.user_id, data={"from": member.role, "to": new})
    return _member_out(_lock_member(uow, user_id)[0])


def _change_status(uow: UnitOfWork, user_id: str, reason: str | None, deactivate: bool) -> MemberOut:
    action = "members.deactivate" if deactivate else "members.reactivate"
    reason = require_reason(action, reason)  # before anything changes (AC2-4)
    member, owners = _lock_member(uow, user_id)
    if member.status == ("deactivated" if deactivate else "active"):
        return _member_out(member)  # a retry: same answer, no second audit row
    if member.role == "owner" and not _caller_is_owner(uow):
        raise _owner_rule(ONLY_OWNER)
    if deactivate and member.role == "owner" and owners <= 1:
        raise _owner_rule(NEEDS_OWNER)
    if deactivate:
        sql = (
            "update identity.memberships set status = 'deactivated', deactivated_at = now(),"
            " deactivated_by = :me, deactivation_reason = :reason where business_id = :b and user_id = :u"
        )
    else:
        # Back with their previous role [RM42-7]; the deactivation record stays in the audit log.
        sql = (
            "update identity.memberships set status = 'active', deactivated_at = null,"
            " deactivated_by = null, deactivation_reason = null where business_id = :b and user_id = :u"
        )
    _update_member(uow, sql, {"me": uow.principal.user_id, "reason": reason, "b": _business(uow), "u": member.user_id})
    audit.record(uow, action, "member", member.user_id, reason=reason)
    return _member_out(_lock_member(uow, user_id)[0])


@router.post(
    "/b/{business_id}/members/{user_id}/deactivate",
    response_model=MemberOut,
    dependencies=[Depends(require(Permission.MEMBERS_MANAGE))],
)
def deactivate_member(user_id: str, body: ReasonIn, uow: BusinessUoW):
    """Takes effect on the member's next request; their sessions and other businesses are untouched (L2-8)."""
    return _change_status(uow, user_id, body.reason, deactivate=True)


@router.post(
    "/b/{business_id}/members/{user_id}/reactivate",
    response_model=MemberOut,
    dependencies=[Depends(require(Permission.MEMBERS_MANAGE))],
)
def reactivate_member(user_id: str, body: ReasonIn, uow: BusinessUoW):
    return _change_status(uow, user_id, body.reason, deactivate=False)


# --- Audit log (§7) -------------------------------------------------------------


class Actor(BaseModel):
    kind: Literal["member", "support", "system"]
    name: str
    user_id: uuid.UUID | None = None


class Target(BaseModel):
    kind: str
    id: uuid.UUID | None
    href: str | None = None


class AuditRowOut(BaseModel):
    at: datetime
    actor: Actor
    action: str
    action_label: str
    target: Target
    reason: str | None
    details: dict


class AuditPageOut(BaseModel):
    items: list[AuditRowOut]
    next_cursor: str | None


def _encode_cursor(at: datetime, row_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(f"{at.isoformat()}|{row_id}".encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        at, row_id = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
        return datetime.fromisoformat(at), uuid.UUID(row_id)
    except (ValueError, UnicodeDecodeError):
        raise AppError("cursor_invalid", "this cursor is not valid", field="cursor") from None


def _href(business_id: uuid.UUID, kind: str, target_id: uuid.UUID | None, role: str) -> str | None:
    route = audit_labels.TARGETS.get(kind)
    if route is None or not has_permission(role, route[1]):
        return None
    if "{id}" in route[0] and target_id is None:
        return None
    return f"/b/{business_id}" + route[0].format(id=target_id)


@router.get(
    "/b/{business_id}/audit-log",
    response_model=AuditPageOut,
    dependencies=[Depends(require(Permission.AUDIT_VIEW))],
)
def audit_log(
    uow: BusinessUoW,
    cursor: str | None = Query(None, max_length=200),
    kind: Literal["invoices", "gst_filing", "team_settings", "support"] | None = None,
    actor: uuid.UUID | None = None,
    dates: DateRange = Depends(date_range),
):
    """Newest first, AUDIT_PAGE rows a page. Periods are Indian dates, both ends included."""
    bid = _business(uow)
    where = ["a.business_id = :b", "a.at >= :start", "a.at < :end"]
    params: dict = {"b": bid, "start": _ist_midnight(dates.date_from), "end": _ist_midnight(dates.date_to, 1)}
    if kind is not None:
        where.append("a.action = any(:actions)")
        params["actions"] = audit_labels.actions_of_kind(kind)
    if actor is not None:
        where.append("a.user_id = :actor and a.support_grant_id is null")
        params["actor"] = actor
    if cursor is not None:
        params["c_at"], params["c_id"] = _decode_cursor(cursor)
        where.append("(a.at, a.id) < (:c_at, :c_id)")
    rows = uow.tx.execute(
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
        {**params, "limit": AUDIT_PAGE + 1},
    ).all()
    more = len(rows) > AUDIT_PAGE
    rows = rows[:AUDIT_PAGE]
    role = uow.principal.role
    return AuditPageOut(
        items=[_audit_row(bid, r, role) for r in rows],
        next_cursor=_encode_cursor(rows[-1].at, rows[-1].id) if more else None,
    )


def _ist_midnight(day: date, plus_days: int = 0) -> datetime:
    return datetime.combine(day + timedelta(days=plus_days), time(), IST).astimezone(UTC)


def _audit_row(business_id: uuid.UUID, r, role: str) -> AuditRowOut:
    if r.support_grant_id is not None:
        actor = Actor(kind="support", name="Support team")
    elif r.user_id is None:
        actor = Actor(kind="system", name="System")
    else:
        actor = Actor(kind="member", name=r.actor_name or "Former member", user_id=r.user_id)
    allowed = audit.ALLOWED_DATA.get(r.action, frozenset())
    return AuditRowOut(
        at=r.at,
        actor=actor,
        action=r.action,
        action_label=audit_labels.label(r.action),
        target=Target(kind=r.target_kind, id=r.target_id, href=_href(business_id, r.target_kind, r.target_id, role)),
        reason=r.reason,
        details={k: v for k, v in (r.data or {}).items() if k in allowed},
    )

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from platform_common.auth import Caller, current_caller, debug_env
from platform_common.db import engine, session_factory
from platform_common.errors import Conflict, Deny, Gone, request_id
from platform_common.permissions import Permission, Role, has_permission
from platform_common.uow import parse_id

from . import invites
from .interface import resolve_principal
from .models import (
    INVITATION_DAYS,
    AuditEvent,
    Business,
    Delivery,
    Invitation,
    InvitationStatus,
    Membership,
    MembershipStatus,
    User,
)

router = APIRouter(prefix="/identity", tags=["identity"])


@lru_cache(maxsize=1)
def _factory():
    # SQLite (tests, local) has no schemas; Postgres uses the identity schema.
    translate = None if engine().dialect.name == "postgresql" else {"identity": None}
    return session_factory(translate)


def _postgres(session: Session) -> bool:
    return session.bind.dialect.name == "postgresql"


def debug_user_id(session: Session, sub: str) -> uuid.UUID:
    """The identity.users id for `sub`, creating the row: local and test only.

    Until S1 sign-up creates users, callers named by X-Debug-User get a row here. On
    PostgreSQL it goes through identity.dev_ensure_user, which only migrator.local
    creates (migrator/local_only.sql), so it doesn't exist in AWS either. The
    route that adds a member by sub uses it too. The row's email is a placeholder:
    invitations match the caller's verified email, not this one.
    """
    if not debug_env():
        raise RuntimeError("debug users exist only when PLATFORM_ENV is local or test")
    if _postgres(session):
        return session.scalar(text("select identity.dev_ensure_user(:sub)"), {"sub": sub})
    user = session.scalar(select(User).where(User.cognito_sub == sub))
    if user is None:
        user = User(cognito_sub=sub, email=f"{sub}@debug.invalid".lower())
        session.add(user)
        session.flush()
    return user.id


def caller_user_id(session: Session, caller: Caller, request_id: str) -> uuid.UUID:
    """The caller's identity.users id, after the per-request session check.

    On PostgreSQL this is the principal resolver (identity.auth_resolve), as in AWS. The
    SQLite test database has no functions, so there an X-Debug-User caller gets a row
    directly; SQLite never runs outside local and test.
    """
    if _postgres(session):
        return resolve_principal(session, caller, None, request_id).user_id
    if not debug_env():
        raise Deny("session_invalid")
    return debug_user_id(session, caller.user_sub)


def db_session(request: Request, principal: Caller = Depends(current_caller)) -> Iterator[Session]:
    with _factory()() as session:
        with session.begin():
            user_id = caller_user_id(session, principal, request_id(request))
        session.info.update(user_id=user_id, tenant_id=None)
        if _postgres(session):

            @event.listens_for(session, "after_begin")
            def _rls_context(sess, transaction, connection):
                # The LLD-1 §3.4 policies read these. Set at the start of every transaction,
                # since set_config(..., true) ends with it and a request may commit twice.
                connection.execute(
                    text(
                        "select set_config('app.user_id', :uid, true), set_config('app.user_sub', :sub, true), "
                        "set_config('app.user_email', :email, true), set_config('app.tenant_id', :tid, true)"
                    ),
                    {
                        "uid": str(user_id),
                        "sub": principal.user_sub,
                        "email": principal.verified_email or "",
                        "tid": str(sess.info["tenant_id"] or ""),
                    },
                )

        yield session


def me(session: Session) -> uuid.UUID:
    return session.info["user_id"]


def bind_business(session: Session, business_id: uuid.UUID) -> None:
    """Scope the rest of the request to one business (app.tenant_id)."""
    session.info["tenant_id"] = business_id
    if _postgres(session) and session.in_transaction():
        session.execute(text("select set_config('app.tenant_id', :t, true)"), {"t": str(business_id)})


def active_membership(session: Session, business_id: uuid.UUID) -> Membership:
    bind_business(session, business_id)
    membership = session.scalar(
        select(Membership).where(
            Membership.business_id == business_id,
            Membership.user_id == me(session),
            Membership.status == MembershipStatus.active,
        )
    )
    if membership is None:
        # Same answer whether the business is missing or simply not the caller's.
        raise Deny("not_member")
    return membership


def require_permission(membership: Membership, permission: Permission) -> None:
    if not has_permission(membership.role, permission):
        raise Deny("role_denied")


def audit(session: Session, tenant_id, actor: str, action: str, entity_type: str, entity_id, **details):
    session.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor_sub=actor,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            details=details,
        )
    )


class TenantIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class TenantOut(BaseModel):
    id: uuid.UUID
    name: str
    role: Role


class MemberIn(BaseModel):
    user_sub: str = Field(min_length=1, max_length=128)
    role: Role


class MemberOut(BaseModel):
    user_sub: str
    role: Role
    status: MembershipStatus
    email: str | None = None
    display_name: str | None = None


def member_out(m: Membership) -> MemberOut:
    return MemberOut(user_sub=m.user_sub, role=m.role, status=m.status, email=m.email, display_name=m.display_name)


class InvitationIn(BaseModel):
    # Deliberately loose: Cognito delivering the temporary password is the real check.
    email: str = Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    role: Role
    display_name: str | None = Field(default=None, min_length=1, max_length=200)


class InvitationOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    email: str
    display_name: str | None
    role: Role
    # pending / accepted / revoked, or "expired" for a pending one past its date.
    status: str
    delivery: Delivery
    invited_by: str
    created_at: datetime
    expires_at: datetime


class MyInvitationOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    tenant_name: str
    role: Role
    expires_at: datetime


class ReasonIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class AuditOut(BaseModel):
    actor_sub: str
    action: str
    entity_type: str
    entity_id: str
    details: dict
    at: datetime


@router.post("/tenants", status_code=201, response_model=TenantOut)
def create_tenant(
    body: TenantIn,
    principal: Caller = Depends(current_caller),
    session: Session = Depends(db_session),
):
    business_id = uuid.uuid4()
    bind_business(session, business_id)
    session.add(Business(id=business_id, name=body.name, created_by=me(session)))
    session.flush()
    session.add(
        Membership(
            business_id=business_id,
            user_id=me(session),
            user_sub=principal.user_sub,
            role=Role.owner,
            email=principal.verified_email,
        )
    )
    audit(session, business_id, principal.user_sub, "tenant.created", "tenant", business_id)
    session.commit()
    return TenantOut(id=business_id, name=body.name, role=Role.owner)


@router.get("/tenants", response_model=list[TenantOut])
def my_tenants(
    principal: Caller = Depends(current_caller),
    session: Session = Depends(db_session),
):
    if _postgres(session):
        # Every business the caller belongs to: only app_ro's biz_member_ro policy shows
        # more than the one bound business (LLD-1 §3.4).
        session.execute(text("set local role app_ro"))
    rows = session.execute(
        select(Business, Membership.role)
        .join(Membership, Membership.business_id == Business.id)
        .where(Membership.user_id == me(session), Membership.status == MembershipStatus.active)
        .order_by(Business.name)
    ).all()
    return [TenantOut(id=t.id, name=t.name, role=role) for t, role in rows]


@router.get("/tenants/{tenant_id}", response_model=TenantOut)
def get_tenant(
    tenant_id: str,
    principal: Caller = Depends(current_caller),
    session: Session = Depends(db_session),
):
    tid = parse_id(tenant_id)
    membership = active_membership(session, tid)
    tenant = session.get(Business, tid)
    return TenantOut(id=tenant.id, name=tenant.name, role=membership.role)


@router.get("/tenants/{tenant_id}/members", response_model=list[MemberOut])
def list_members(
    tenant_id: str,
    principal: Caller = Depends(current_caller),
    session: Session = Depends(db_session),
):
    tid = parse_id(tenant_id)
    active_membership(session, tid)
    members = session.scalars(
        select(Membership).where(Membership.business_id == tid).order_by(Membership.created_at)
    )
    return [member_out(m) for m in members]


@router.post(
    "/tenants/{tenant_id}/members",
    status_code=201,
    response_model=MemberOut,
)
def add_member(
    tenant_id: str,
    body: MemberIn,
    principal: Caller = Depends(current_caller),
    session: Session = Depends(db_session),
):
    tid = parse_id(tenant_id)
    check_can_invite(active_membership(session, tid), body.role)
    user_id = debug_user_id(session, body.user_sub)  # LLD-2 replaces adding by sub with invitations
    member = Membership(business_id=tid, user_id=user_id, user_sub=body.user_sub, role=body.role)
    session.add(member)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise Conflict("already_member", "already a member")
    audit(session, tid, principal.user_sub, "member.added", "membership", member.id, role=body.role.value)
    session.commit()
    return member_out(member)


@router.post("/tenants/{tenant_id}/members/{user_sub}/deactivate", response_model=MemberOut)
def deactivate_member(
    tenant_id: str,
    user_sub: str,
    body: ReasonIn,
    principal: Caller = Depends(current_caller),
    session: Session = Depends(db_session),
):
    return _change_member_status(session, principal, tenant_id, user_sub, MembershipStatus.deactivated, body.reason)


@router.post("/tenants/{tenant_id}/members/{user_sub}/reactivate", response_model=MemberOut)
def reactivate_member(
    tenant_id: str,
    user_sub: str,
    body: ReasonIn,
    principal: Caller = Depends(current_caller),
    session: Session = Depends(db_session),
):
    return _change_member_status(session, principal, tenant_id, user_sub, MembershipStatus.active, body.reason)


def _change_member_status(
    session: Session, principal: Caller, tenant_id: str, user_sub: str, new_status: MembershipStatus, reason: str
) -> MemberOut:
    tid = parse_id(tenant_id)
    caller = active_membership(session, tid)
    require_permission(caller, Permission.MEMBERS_MANAGE)
    # Lock the tenant's active owners so two owners can't deactivate each other at once.
    owners = session.scalars(
        select(Membership)
        .where(
            Membership.business_id == tid,
            Membership.role == Role.owner,
            Membership.status == MembershipStatus.active,
        )
        .with_for_update()
    ).all()
    # Lock the target too, so two concurrent changes to one member write one audit event.
    member = session.scalar(
        select(Membership)
        .where(Membership.business_id == tid, Membership.user_sub == user_sub)
        .with_for_update()
    )
    if member is None:
        raise Deny("not_found")
    if member.status == new_status:
        # A retry of a change that already happened: same answer, no second audit event.
        return member_out(member)
    if member.role == Role.owner and caller.role != Role.owner:
        raise Deny("role_denied")
    if new_status == MembershipStatus.deactivated and member.role == Role.owner and len(owners) <= 1:
        raise Conflict("last_owner", "cannot deactivate the last active owner")

    member.status = new_status
    deactivating = new_status == MembershipStatus.deactivated
    member.deactivated_at = datetime.now(UTC) if deactivating else None
    member.deactivated_by = me(session) if deactivating else None
    member.deactivation_reason = reason if deactivating else None
    action = "member.deactivated" if deactivating else "member.reactivated"
    audit(
        session, tid, principal.user_sub, action, "membership", member.id,
        user_sub=member.user_sub, role=member.role.value, reason=reason,
    )
    session.commit()
    return member_out(member)


@router.get("/tenants/{tenant_id}/audit", response_model=list[AuditOut])
def audit_log(
    tenant_id: str,
    principal: Caller = Depends(current_caller),
    session: Session = Depends(db_session),
):
    tid = parse_id(tenant_id)
    require_permission(active_membership(session, tid), Permission.AUDIT_VIEW)
    events = session.scalars(
        select(AuditEvent).where(AuditEvent.tenant_id == tid).order_by(AuditEvent.at.desc())
    )
    return [
        AuditOut(
            actor_sub=e.actor_sub, action=e.action, entity_type=e.entity_type, entity_id=e.entity_id,
            details=e.details or {}, at=e.at,
        )
        for e in events
    ]


# --- Invitations (E0-1) --------------------------------------------------------


def _aware(value: datetime) -> datetime:
    # SQLite hands back naive datetimes; everything here is stored in UTC.
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _expired(inv: Invitation) -> bool:
    return inv.status == InvitationStatus.pending and _aware(inv.expires_at) <= datetime.now(UTC)


def invitation_out(inv: Invitation) -> InvitationOut:
    return InvitationOut(
        id=inv.id,
        tenant_id=inv.tenant_id,
        email=inv.email,
        display_name=inv.display_name,
        role=inv.role,
        status="expired" if _expired(inv) else inv.status.value,
        delivery=inv.delivery,
        invited_by=inv.invited_by,
        created_at=inv.created_at,
        expires_at=inv.expires_at,
    )


def check_can_invite(caller: Membership, role: Role) -> None:
    require_permission(caller, Permission.MEMBERS_MANAGE)
    if role == Role.owner and caller.role != Role.owner:
        raise Deny("role_denied")


def _deliver(session: Session, inv: Invitation, *, resend: bool) -> None:
    """Runs after the invitation is committed, so a mail failure never loses it.

    A failed send is recorded as delivery=failed; "resend" retries it.
    """
    try:
        invites.sender().send(inv.email, resend=resend)
        inv.delivery = Delivery.sent
    except invites.DeliveryFailed:
        inv.delivery = Delivery.failed
    session.commit()


def _tenant_invitation(session: Session, tid: uuid.UUID, invitation_id: str) -> Invitation:
    try:
        iid = uuid.UUID(invitation_id)
    except ValueError:
        raise Deny("not_found") from None
    inv = session.scalar(
        select(Invitation).where(Invitation.id == iid, Invitation.tenant_id == tid).with_for_update()
    )
    if inv is None:
        raise Deny("not_found")
    return inv


@router.post(
    "/tenants/{tenant_id}/invitations",
    status_code=201,
    response_model=InvitationOut,
)
def invite_member(
    tenant_id: str,
    body: InvitationIn,
    principal: Caller = Depends(current_caller),
    session: Session = Depends(db_session),
):
    tid = parse_id(tenant_id)
    check_can_invite(active_membership(session, tid), body.role)
    email = body.email.strip().lower()

    if session.scalar(
        select(Membership.id).where(Membership.business_id == tid, func.lower(Membership.email) == email)
    ):
        raise Conflict("already_member", "already a member")
    open_invite = session.scalar(
        select(Invitation)
        .where(
            Invitation.tenant_id == tid, Invitation.email == email, Invitation.status == InvitationStatus.pending
        )
        .with_for_update()
    )
    if open_invite is not None:
        # One open invitation per person; an expired one is renewed with "resend".
        raise Conflict("already_invited", "already invited; use resend")

    inv = Invitation(
        tenant_id=tid,
        email=email,
        display_name=body.display_name,
        role=body.role,
        invited_by=principal.user_sub,
        expires_at=datetime.now(UTC) + timedelta(days=INVITATION_DAYS),
    )
    session.add(inv)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()  # a concurrent invite for the same email won
        raise Conflict("already_invited", "already invited; use resend")
    audit(session, tid, principal.user_sub, "invitation.created", "invitation", inv.id, role=body.role.value)
    session.commit()
    _deliver(session, inv, resend=False)
    return invitation_out(inv)


@router.get("/tenants/{tenant_id}/invitations", response_model=list[InvitationOut])
def list_invitations(
    tenant_id: str,
    principal: Caller = Depends(current_caller),
    session: Session = Depends(db_session),
):
    tid = parse_id(tenant_id)
    require_permission(active_membership(session, tid), Permission.MEMBERS_MANAGE)
    rows = session.scalars(
        select(Invitation).where(Invitation.tenant_id == tid).order_by(Invitation.created_at.desc())
    )
    return [invitation_out(i) for i in rows]


@router.post("/tenants/{tenant_id}/invitations/{invitation_id}/resend", response_model=InvitationOut)
def resend_invitation(
    tenant_id: str,
    invitation_id: str,
    principal: Caller = Depends(current_caller),
    session: Session = Depends(db_session),
):
    tid = parse_id(tenant_id)
    caller = active_membership(session, tid)
    inv = _tenant_invitation(session, tid, invitation_id)
    check_can_invite(caller, inv.role)
    if inv.status != InvitationStatus.pending:
        raise Conflict("invitation_not_pending", f"invitation is {inv.status.value}")
    inv.expires_at = datetime.now(UTC) + timedelta(days=INVITATION_DAYS)
    inv.delivery = Delivery.pending
    audit(session, tid, principal.user_sub, "invitation.resent", "invitation", inv.id)
    session.commit()
    _deliver(session, inv, resend=True)
    return invitation_out(inv)


@router.post("/tenants/{tenant_id}/invitations/{invitation_id}/revoke", response_model=InvitationOut)
def revoke_invitation(
    tenant_id: str,
    invitation_id: str,
    principal: Caller = Depends(current_caller),
    session: Session = Depends(db_session),
):
    tid = parse_id(tenant_id)
    caller = active_membership(session, tid)
    inv = _tenant_invitation(session, tid, invitation_id)
    check_can_invite(caller, inv.role)
    if inv.status == InvitationStatus.revoked:
        return invitation_out(inv)  # retry: same answer, no second audit event
    if inv.status != InvitationStatus.pending:
        raise Conflict("invitation_not_pending", f"invitation is {inv.status.value}")
    inv.status = InvitationStatus.revoked
    audit(session, tid, principal.user_sub, "invitation.revoked", "invitation", inv.id)
    session.commit()
    return invitation_out(inv)


@router.get("/invitations", response_model=list[MyInvitationOut])
def my_invitations(
    principal: Caller = Depends(current_caller),
    session: Session = Depends(db_session),
):
    email = principal.verified_email
    if email is None:
        return []
    rows = session.execute(
        select(Invitation, Business.name)
        .join(Business, Business.id == Invitation.tenant_id)
        .where(Invitation.email == email, Invitation.status == InvitationStatus.pending)
        .order_by(Invitation.created_at)
    ).all()
    return [
        MyInvitationOut(id=i.id, tenant_id=i.tenant_id, tenant_name=name, role=i.role, expires_at=i.expires_at)
        for i, name in rows
        if not _expired(i)
    ]


@router.post("/invitations/{invitation_id}/accept", response_model=TenantOut)
def accept_invitation(
    invitation_id: str,
    principal: Caller = Depends(current_caller),
    session: Session = Depends(db_session),
):
    email = principal.verified_email
    try:
        iid = uuid.UUID(invitation_id)
    except ValueError:
        raise Deny("not_found") from None
    # Only the addressee may see or accept it; anyone else gets the same 404.
    inv = None
    if email is not None:
        mine = select(Invitation).where(Invitation.id == iid, Invitation.email == email)
        inv = session.scalar(mine)
        if inv is not None and inv.status == InvitationStatus.pending:
            # Lock only a pending one: FOR UPDATE goes through inv_accept, which (rightly)
            # shows the invitee nothing else, and a retry after accepting must still answer.
            inv = session.scalar(mine.with_for_update())
    if inv is None:
        raise Deny("not_found")

    if inv.status == InvitationStatus.accepted:
        if inv.accepted_by == principal.user_sub:
            bind_business(session, inv.tenant_id)
            tenant = session.get(Business, inv.tenant_id)
            return TenantOut(id=tenant.id, name=tenant.name, role=inv.role)  # retry
        raise Conflict("invitation_used", "invitation already used")
    if inv.status == InvitationStatus.revoked or _expired(inv):
        raise Gone("invitation_invalid", "invitation is no longer valid; ask for a new one")
    if session.scalar(
        select(Membership.id).where(Membership.business_id == inv.tenant_id, Membership.user_id == me(session))
    ):
        # Includes a deactivated membership: rejoining needs reactivation, not an invite.
        raise Conflict("already_member", "already a member")

    member = Membership(
        business_id=inv.tenant_id,
        user_id=me(session),
        user_sub=principal.user_sub,
        role=inv.role,
        email=email,
        display_name=inv.display_name,
    )
    session.add(member)
    inv.status = InvitationStatus.accepted
    inv.accepted_by = principal.user_sub
    inv.accepted_at = datetime.now(UTC)
    session.flush()
    # Bound only now, once the caller is a member (m_accept needs no business).
    bind_business(session, inv.tenant_id)
    tenant = session.get(Business, inv.tenant_id)
    audit(
        session, inv.tenant_id, principal.user_sub, "invitation.accepted", "invitation", inv.id,
        membership_id=str(member.id), role=inv.role.value,
    )
    session.commit()
    return TenantOut(id=tenant.id, name=tenant.name, role=inv.role)


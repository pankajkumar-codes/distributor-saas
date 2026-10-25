import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from platform_common.auth import Caller, current_caller
from platform_common.db import engine, session_factory
from platform_common.tenancy import not_found, parse_tenant_id

from . import invites
from .models import (
    INVITATION_DAYS,
    MANAGE_MEMBERS,
    READ_AUDIT,
    AuditEvent,
    Delivery,
    Invitation,
    InvitationStatus,
    Membership,
    MembershipStatus,
    Role,
    Tenant,
)

router = APIRouter(prefix="/identity", tags=["identity"])


@lru_cache(maxsize=1)
def _factory():
    # SQLite (tests, local) has no schemas; Postgres uses the identity schema.
    translate = None if engine().dialect.name == "postgresql" else {"identity": None}
    return session_factory(translate)


def db_session(principal: Caller = Depends(current_caller)) -> Iterator[Session]:
    with _factory()() as session:
        if session.bind.dialect.name == "postgresql":

            @event.listens_for(session, "after_begin")
            def _rls_context(sess, transaction, connection):
                # Row-level security policies read these; see migrations/0002, 0004 and 0005.
                # Set at the start of every transaction, since set_config(..., true)
                # ends with it and a request may commit more than once.
                connection.execute(
                    text(
                        "select set_config('app.user_sub', :sub, true), "
                        "set_config('app.user_email', :email, true)"
                    ),
                    {"sub": principal.user_sub, "email": principal.verified_email or ""},
                )

        yield session


def active_membership(session: Session, tenant_id: uuid.UUID, user_sub: str) -> Membership:
    membership = session.scalar(
        select(Membership).where(
            Membership.tenant_id == tenant_id,
            Membership.user_sub == user_sub,
            Membership.status == MembershipStatus.active,
        )
    )
    if membership is None:
        # Same answer whether the tenant is missing or simply not the caller's.
        raise not_found()
    return membership


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


@router.post("/tenants", status_code=status.HTTP_201_CREATED, response_model=TenantOut)
def create_tenant(
    body: TenantIn,
    principal: Caller = Depends(current_caller),
    session: Session = Depends(db_session),
):
    tenant = Tenant(name=body.name)
    session.add(tenant)
    session.flush()
    session.add(Membership(tenant_id=tenant.id, user_sub=principal.user_sub, role=Role.owner))
    audit(session, tenant.id, principal.user_sub, "tenant.created", "tenant", tenant.id)
    session.commit()
    return TenantOut(id=tenant.id, name=tenant.name, role=Role.owner)


@router.get("/tenants", response_model=list[TenantOut])
def my_tenants(
    principal: Caller = Depends(current_caller),
    session: Session = Depends(db_session),
):
    rows = session.execute(
        select(Tenant, Membership.role)
        .join(Membership, Membership.tenant_id == Tenant.id)
        .where(Membership.user_sub == principal.user_sub, Membership.status == MembershipStatus.active)
        .order_by(Tenant.name)
    ).all()
    return [TenantOut(id=t.id, name=t.name, role=role) for t, role in rows]


@router.get("/tenants/{tenant_id}", response_model=TenantOut)
def get_tenant(
    tenant_id: str,
    principal: Caller = Depends(current_caller),
    session: Session = Depends(db_session),
):
    tid = parse_tenant_id(tenant_id)
    membership = active_membership(session, tid, principal.user_sub)
    tenant = session.get(Tenant, tid)
    return TenantOut(id=tenant.id, name=tenant.name, role=membership.role)


@router.get("/tenants/{tenant_id}/members", response_model=list[MemberOut])
def list_members(
    tenant_id: str,
    principal: Caller = Depends(current_caller),
    session: Session = Depends(db_session),
):
    tid = parse_tenant_id(tenant_id)
    active_membership(session, tid, principal.user_sub)
    members = session.scalars(
        select(Membership).where(Membership.tenant_id == tid).order_by(Membership.created_at)
    )
    return [member_out(m) for m in members]


@router.post(
    "/tenants/{tenant_id}/members",
    status_code=status.HTTP_201_CREATED,
    response_model=MemberOut,
)
def add_member(
    tenant_id: str,
    body: MemberIn,
    principal: Caller = Depends(current_caller),
    session: Session = Depends(db_session),
):
    tid = parse_tenant_id(tenant_id)
    caller = active_membership(session, tid, principal.user_sub)
    if caller.role not in MANAGE_MEMBERS:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not allowed to manage members")
    if body.role == Role.owner and caller.role != Role.owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "only an owner can add an owner")

    member = Membership(tenant_id=tid, user_sub=body.user_sub, role=body.role)
    session.add(member)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "already a member")
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
    return _change_member_status(session, principal, tenant_id, user_sub, MembershipStatus.disabled, body.reason)


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
    tid = parse_tenant_id(tenant_id)
    caller = active_membership(session, tid, principal.user_sub)
    if caller.role not in MANAGE_MEMBERS:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not allowed to manage members")
    # Lock the tenant's active owners so two owners can't deactivate each other at once.
    owners = session.scalars(
        select(Membership)
        .where(
            Membership.tenant_id == tid,
            Membership.role == Role.owner,
            Membership.status == MembershipStatus.active,
        )
        .with_for_update()
    ).all()
    # Lock the target too, so two concurrent changes to one member write one audit event.
    member = session.scalar(
        select(Membership)
        .where(Membership.tenant_id == tid, Membership.user_sub == user_sub)
        .with_for_update()
    )
    if member is None:
        raise not_found()
    if member.status == new_status:
        # A retry of a change that already happened: same answer, no second audit event.
        return member_out(member)
    if member.role == Role.owner and caller.role != Role.owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "only an owner can change an owner's access")
    if new_status == MembershipStatus.disabled and member.role == Role.owner and len(owners) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "cannot deactivate the last active owner")

    member.status = new_status
    action = "member.deactivated" if new_status == MembershipStatus.disabled else "member.reactivated"
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
    tid = parse_tenant_id(tenant_id)
    caller = active_membership(session, tid, principal.user_sub)
    if caller.role not in READ_AUDIT:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not allowed to read the audit log")
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
    if caller.role not in MANAGE_MEMBERS:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not allowed to manage members")
    if role == Role.owner and caller.role != Role.owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "only an owner can invite an owner")


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
        raise not_found()
    inv = session.scalar(
        select(Invitation).where(Invitation.id == iid, Invitation.tenant_id == tid).with_for_update()
    )
    if inv is None:
        raise not_found()
    return inv


@router.post(
    "/tenants/{tenant_id}/invitations",
    status_code=status.HTTP_201_CREATED,
    response_model=InvitationOut,
)
def invite_member(
    tenant_id: str,
    body: InvitationIn,
    principal: Caller = Depends(current_caller),
    session: Session = Depends(db_session),
):
    tid = parse_tenant_id(tenant_id)
    check_can_invite(active_membership(session, tid, principal.user_sub), body.role)
    email = body.email.strip().lower()

    if session.scalar(
        select(Membership.id).where(Membership.tenant_id == tid, func.lower(Membership.email) == email)
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "already a member")
    open_invite = session.scalar(
        select(Invitation)
        .where(
            Invitation.tenant_id == tid, Invitation.email == email, Invitation.status == InvitationStatus.pending
        )
        .with_for_update()
    )
    if open_invite is not None:
        # One open invitation per person; an expired one is renewed with "resend".
        raise HTTPException(status.HTTP_409_CONFLICT, "already invited; use resend")

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
        raise HTTPException(status.HTTP_409_CONFLICT, "already invited; use resend")
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
    tid = parse_tenant_id(tenant_id)
    caller = active_membership(session, tid, principal.user_sub)
    if caller.role not in MANAGE_MEMBERS:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not allowed to manage members")
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
    tid = parse_tenant_id(tenant_id)
    caller = active_membership(session, tid, principal.user_sub)
    inv = _tenant_invitation(session, tid, invitation_id)
    check_can_invite(caller, inv.role)
    if inv.status != InvitationStatus.pending:
        raise HTTPException(status.HTTP_409_CONFLICT, f"invitation is {inv.status.value}")
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
    tid = parse_tenant_id(tenant_id)
    caller = active_membership(session, tid, principal.user_sub)
    inv = _tenant_invitation(session, tid, invitation_id)
    check_can_invite(caller, inv.role)
    if inv.status == InvitationStatus.revoked:
        return invitation_out(inv)  # retry: same answer, no second audit event
    if inv.status != InvitationStatus.pending:
        raise HTTPException(status.HTTP_409_CONFLICT, f"invitation is {inv.status.value}")
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
        select(Invitation, Tenant.name)
        .join(Tenant, Tenant.id == Invitation.tenant_id)
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
        raise not_found()
    # Only the addressee may see or accept it; anyone else gets the same 404.
    inv = None
    if email is not None:
        inv = session.scalar(select(Invitation).where(Invitation.id == iid, Invitation.email == email).with_for_update())
    if inv is None:
        raise not_found()

    if inv.status == InvitationStatus.accepted:
        if inv.accepted_by == principal.user_sub:
            tenant = session.get(Tenant, inv.tenant_id)
            return TenantOut(id=tenant.id, name=tenant.name, role=inv.role)  # retry
        raise HTTPException(status.HTTP_409_CONFLICT, "invitation already used")
    if inv.status == InvitationStatus.revoked or _expired(inv):
        raise HTTPException(status.HTTP_410_GONE, "invitation is no longer valid; ask for a new one")
    if session.scalar(
        select(Membership.id).where(Membership.tenant_id == inv.tenant_id, Membership.user_sub == principal.user_sub)
    ):
        # Includes a deactivated membership: rejoining needs reactivation, not an invite.
        raise HTTPException(status.HTTP_409_CONFLICT, "already a member")

    member = Membership(
        tenant_id=inv.tenant_id,
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
    # Read only now: row-level security shows a tenant to its members.
    tenant = session.get(Tenant, inv.tenant_id)
    audit(
        session, inv.tenant_id, principal.user_sub, "invitation.accepted", "invitation", inv.id,
        membership_id=str(member.id), role=inv.role.value,
    )
    session.commit()
    return TenantOut(id=tenant.id, name=tenant.name, role=inv.role)


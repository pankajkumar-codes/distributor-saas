import uuid
from collections.abc import Iterator
from datetime import datetime
from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException, Request, status
from mangum import Mangum
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from platform_common.auth import Principal, current_principal
from platform_common.db import engine, session_factory
from platform_common.tenancy import not_found, parse_tenant_id

from .models import MANAGE_MEMBERS, READ_AUDIT, AuditEvent, Membership, MembershipStatus, Role, Tenant

app = FastAPI(title="identity", root_path_in_servers=False)


@lru_cache(maxsize=1)
def _factory():
    # SQLite (tests, local) has no schemas; Postgres uses the identity schema.
    translate = None if engine().dialect.name == "postgresql" else {"identity": None}
    return session_factory(translate)


def db_session(principal: Principal = Depends(current_principal)) -> Iterator[Session]:
    with _factory()() as session:
        if session.bind.dialect.name == "postgresql":
            # Row-level security policies read this; see migrations/0002_identity_rls.sql.
            session.execute(
                text("select set_config('app.user_sub', :sub, true)"), {"sub": principal.user_sub}
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


class ReasonIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class AuditOut(BaseModel):
    actor_sub: str
    action: str
    entity_type: str
    entity_id: str
    details: dict
    at: datetime


@app.get("/identity/health")
def health():
    return {"status": "ok"}


@app.post("/identity/tenants", status_code=status.HTTP_201_CREATED, response_model=TenantOut)
def create_tenant(
    body: TenantIn,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(db_session),
):
    tenant = Tenant(name=body.name)
    session.add(tenant)
    session.flush()
    session.add(Membership(tenant_id=tenant.id, user_sub=principal.user_sub, role=Role.owner))
    audit(session, tenant.id, principal.user_sub, "tenant.created", "tenant", tenant.id)
    session.commit()
    return TenantOut(id=tenant.id, name=tenant.name, role=Role.owner)


@app.get("/identity/tenants", response_model=list[TenantOut])
def my_tenants(
    principal: Principal = Depends(current_principal),
    session: Session = Depends(db_session),
):
    rows = session.execute(
        select(Tenant, Membership.role)
        .join(Membership, Membership.tenant_id == Tenant.id)
        .where(Membership.user_sub == principal.user_sub, Membership.status == MembershipStatus.active)
        .order_by(Tenant.name)
    ).all()
    return [TenantOut(id=t.id, name=t.name, role=role) for t, role in rows]


@app.get("/identity/tenants/{tenant_id}", response_model=TenantOut)
def get_tenant(
    tenant_id: str,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(db_session),
):
    tid = parse_tenant_id(tenant_id)
    membership = active_membership(session, tid, principal.user_sub)
    tenant = session.get(Tenant, tid)
    return TenantOut(id=tenant.id, name=tenant.name, role=membership.role)


@app.get("/identity/tenants/{tenant_id}/members", response_model=list[MemberOut])
def list_members(
    tenant_id: str,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(db_session),
):
    tid = parse_tenant_id(tenant_id)
    active_membership(session, tid, principal.user_sub)
    members = session.scalars(
        select(Membership).where(Membership.tenant_id == tid).order_by(Membership.created_at)
    )
    return [MemberOut(user_sub=m.user_sub, role=m.role, status=m.status) for m in members]


@app.post(
    "/identity/tenants/{tenant_id}/members",
    status_code=status.HTTP_201_CREATED,
    response_model=MemberOut,
)
def add_member(
    tenant_id: str,
    body: MemberIn,
    principal: Principal = Depends(current_principal),
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
    return MemberOut(user_sub=member.user_sub, role=member.role, status=member.status)


@app.post("/identity/tenants/{tenant_id}/members/{user_sub}/deactivate", response_model=MemberOut)
def deactivate_member(
    tenant_id: str,
    user_sub: str,
    body: ReasonIn,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(db_session),
):
    return _change_member_status(session, principal, tenant_id, user_sub, MembershipStatus.disabled, body.reason)


@app.post("/identity/tenants/{tenant_id}/members/{user_sub}/reactivate", response_model=MemberOut)
def reactivate_member(
    tenant_id: str,
    user_sub: str,
    body: ReasonIn,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(db_session),
):
    return _change_member_status(session, principal, tenant_id, user_sub, MembershipStatus.active, body.reason)


def _change_member_status(
    session: Session, principal: Principal, tenant_id: str, user_sub: str, new_status: MembershipStatus, reason: str
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
        return MemberOut(user_sub=member.user_sub, role=member.role, status=member.status)
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
    return MemberOut(user_sub=member.user_sub, role=member.role, status=member.status)


@app.get("/identity/tenants/{tenant_id}/audit", response_model=list[AuditOut])
def audit_log(
    tenant_id: str,
    principal: Principal = Depends(current_principal),
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


handler = Mangum(app, lifespan="off")

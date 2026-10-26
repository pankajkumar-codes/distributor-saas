import uuid
from collections.abc import Iterator
from functools import lru_cache
from types import SimpleNamespace

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import event, select, text
from sqlalchemy.orm import Session

from platform_common import audit
from platform_common.auth import Caller, current_caller, debug_env
from platform_common.db import engine, session_factory
from platform_common.errors import Deny, request_id
from platform_common.permissions import Permission, Role, has_permission
from platform_common.uow import Principal, parse_id

from .interface import resolve_principal
from .models import Business, Membership, MembershipStatus, User

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


class TenantIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class TenantOut(BaseModel):
    id: uuid.UUID
    name: str
    role: Role


@router.post("/tenants", status_code=201, response_model=TenantOut)
def create_tenant(
    body: TenantIn,
    request: Request,
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
    if _postgres(session):
        # SQLite (unit tests) has no platform schema; on PostgreSQL the row goes to
        # platform.audit_log like every other module's.
        p = Principal(
            user_sub=principal.user_sub, request_id=request_id(request), user_id=me(session), business_id=business_id
        )
        audit.record(SimpleNamespace(tx=session, principal=p), "business.create", "business", business_id)
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

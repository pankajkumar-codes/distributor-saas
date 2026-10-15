"""Tenant identifiers arrive from the client and are never trusted on their own.

Services resolve a tenant only together with the caller's active membership, and
answer 404 both when the tenant does not exist and when the caller is not a member,
so another tenant's ids reveal nothing.

Services other than identity have no grants on identity tables. They ask
`identity.caller_role()` (identity migration 0003), which only ever answers for the
user in `app.user_sub`. Use `tenant_dependency` on every tenant-scoped route:

    tenant = tenant_dependency(db_session)

    @app.get("/commerce/tenants/{tenant_id}/products")
    def products(ctx: TenantContext = Depends(tenant), session = Depends(db_session)): ...

Both dependencies receive the same session, which is now bound to the tenant: every
transaction it starts sets `app.user_sub` and `app.tenant_id`, so row-level security
applies even after a commit. This needs PostgreSQL; tests that use SQLite override
the dependency.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from .auth import Principal, current_principal

_CTX_KEY = "platform_common.tenant_context"


@dataclass(frozen=True)
class TenantContext:
    tenant_id: uuid.UUID
    user_sub: str
    role: str


def parse_tenant_id(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except (ValueError, TypeError, AttributeError):
        raise not_found()


def not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "not found")


_SET_CONTEXT = text(
    "select set_config('app.user_sub', :sub, true), set_config('app.tenant_id', :tid, true)"
)


def _rebind_on_begin(session: Session, transaction, connection) -> None:  # noqa: ARG001
    ctx = session.info.get(_CTX_KEY)
    if ctx is not None:
        connection.execute(_SET_CONTEXT, {"sub": ctx.user_sub, "tid": str(ctx.tenant_id)})


def bind_tenant(session: Session, raw_tenant_id: str, principal: Principal) -> TenantContext:
    """Check the caller is an active member of the tenant and bind the session to it.

    Raises 404 for a malformed id, an unknown tenant, a non-member or a disabled
    member alike. A session can be bound to one tenant only.
    """
    tenant_id = parse_tenant_id(raw_tenant_id)
    existing = session.info.get(_CTX_KEY)
    if existing is not None:
        if existing.tenant_id != tenant_id or existing.user_sub != principal.user_sub:
            raise RuntimeError("session is already bound to another tenant or user")
        return existing

    session.execute(_SET_CONTEXT, {"sub": principal.user_sub, "tid": str(tenant_id)})
    role = session.scalar(text("select identity.caller_role(:t)"), {"t": tenant_id})
    if role is None:
        raise not_found()
    ctx = TenantContext(tenant_id=tenant_id, user_sub=principal.user_sub, role=role)
    session.info[_CTX_KEY] = ctx
    event.listen(session, "after_begin", _rebind_on_begin)
    return ctx


def tenant_dependency(session_dependency: Callable) -> Callable:
    """Build a FastAPI dependency for routes with a `{tenant_id}` path parameter."""

    def dependency(
        tenant_id: str,
        principal: Principal = Depends(current_principal),
        session: Session = Depends(session_dependency),
    ) -> TenantContext:
        return bind_tenant(session, tenant_id, principal)

    return dependency

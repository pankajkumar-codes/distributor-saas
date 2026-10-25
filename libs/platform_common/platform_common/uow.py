"""Units of work: one transaction, with the caller's context set for row-level security
(LLD-0 §3.1). This replaces #9's `bind_tenant`.

A business route gets its unit of work from the `business_uow` dependency:

    @router.get("/b/{business_id}/products")
    def products(uow: BusinessUoW): ...

`business_uow` parses the business ID (malformed is `Deny("not_found")`), opens the
transaction with the caller's `app.user_sub`, asks the principal resolver for the
caller's active membership, and only then sets `app.tenant_id` and `app.role`. Identity
registers the resolver at start-up (`set_principal_resolver`), so platform_common never
imports a module. The resolver raises `Deny` for anything that isn't an active
membership: not a member, a deactivated one, an unknown business.

The transaction commits once, after the endpoint returns and before the response is
sent (`scope="function"`), and rolls back on any exception. Every `app.*` setting is
transaction-local, so nothing leaks into the next request on the same connection.
"""

import logging
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from .auth import Caller, current_caller
from .errors import Deny, request_id

log = logging.getLogger("platform_common.uow")


@dataclass(frozen=True)
class Principal:
    """Who is calling, after the resolver checked them."""

    user_sub: str | None  # Cognito sub; the grandfathered identity policies read app.user_sub
    request_id: str
    user_id: uuid.UUID | None = None  # identity.users.id, from LLD-1 on
    session_id: uuid.UUID | None = None  # None for jobs and the retention role
    business_id: uuid.UUID | None = None
    role: str | None = None  # owner | admin | billing | ca
    support_grant_id: uuid.UUID | None = None


# (tx, caller, business_id or None, request_id) -> Principal, or raise Deny.
PrincipalResolver = Callable[[Session, Caller, uuid.UUID | None, str], Principal]

_resolver: PrincipalResolver | None = None
_factory: sessionmaker | None = None
_open: ContextVar[bool] = ContextVar("platform_common.uow_open", default=False)


def set_principal_resolver(resolver: PrincipalResolver | None) -> None:
    global _resolver
    _resolver = resolver


def set_session_factory(factory: sessionmaker | None) -> None:
    """Tests and local tools point units of work at another database; None restores the default."""
    global _factory
    _factory = factory


def _session_factory() -> sessionmaker:
    global _factory
    if _factory is None:
        from .db import session_factory

        _factory = session_factory()
    return _factory


_SET_CONTEXT = text(
    "select set_config('app.user_id', :user_id, true), set_config('app.user_sub', :user_sub, true),"
    " set_config('app.tenant_id', :tenant_id, true), set_config('app.role', :role, true),"
    " set_config('app.support_grant_id', :grant, true), set_config('app.request_id', :request_id, true)"
)


def _set_context(tx: Session, p: Principal) -> None:
    def s(value) -> str:
        return "" if value is None else str(value)

    tx.execute(
        _SET_CONTEXT,
        {
            "user_id": s(p.user_id),
            "user_sub": s(p.user_sub),
            "tenant_id": s(p.business_id),
            "role": s(p.role),
            "grant": s(p.support_grant_id),
            "request_id": p.request_id,
        },
    )


class UnitOfWork:
    def __init__(self, tx: Session, principal: Principal, read_only: bool):
        self.tx = tx
        self.principal = principal
        self.read_only = read_only
        self._after_commit: list[Callable[[], None]] = []

    def after_commit(self, fn: Callable[[], None]) -> None:
        """Run `fn` only once the transaction has committed (SQS sends, mail)."""
        self._after_commit.append(fn)

    def _bind(self, principal: Principal) -> None:
        self.principal = principal
        _set_context(self.tx, principal)


@contextmanager
def unit_of_work(principal: Principal, *, read_only: bool = False) -> Iterator[UnitOfWork]:
    """One transaction with `app.*` set from `principal`. Commits at exit, rolls back on error.

    `read_only` also makes the transaction read only and switches to `app_ro` (L0-7).
    Nesting raises: interface functions take `uow.tx` and never open or commit their own.
    """
    if _open.get():
        raise RuntimeError("unit_of_work is already open; pass uow.tx down instead")
    # Set, not reset: FastAPI may enter and exit a dependency in different contexts.
    _open.set(True)
    try:
        with _session_factory()() as tx:
            with tx.begin():
                if read_only:
                    # Must come before any other statement in the transaction.
                    tx.execute(text("set transaction read only"))
                    tx.execute(text("set local role app_ro"))
                uow = UnitOfWork(tx, principal, read_only)
                _set_context(tx, principal)
                yield uow
    finally:
        _open.set(False)
    for fn in uow._after_commit:
        try:
            fn()
        except Exception:
            # The commit stands; work that must happen goes through the outbox (§3.7).
            log.exception("after_commit callback failed", extra={"request_id": principal.request_id})


def parse_id(raw: str) -> uuid.UUID:
    """A path ID from the client. Malformed looks exactly like unknown."""
    try:
        return uuid.UUID(raw)
    except (ValueError, TypeError, AttributeError):
        raise Deny("not_found") from None


def _resolve(uow: UnitOfWork, caller: Caller, business_id: uuid.UUID | None) -> Principal:
    if _resolver is None:
        raise RuntimeError("no principal resolver registered; identity sets one at start-up")
    principal = _resolver(uow.tx, caller, business_id, uow.principal.request_id)
    if principal.business_id != business_id or principal.user_sub != caller.user_sub:
        raise RuntimeError("principal resolver returned a principal for another business or user")
    if principal.support_grant_id is not None:
        # The two-step support flow (LLD-0 §3.1 [L0v3-2]) needs LLD-1's support_grants and
        # the audit module. Until both exist a support principal is refused.
        raise Deny("support_no_grant")
    return principal


def business_uow(business_id: str, request: Request) -> Iterator[UnitOfWork]:
    """FastAPI dependency for every `/api/v1/b/{business_id}/...` route."""
    bid = parse_id(business_id)
    caller = current_caller(request)
    with unit_of_work(Principal(user_sub=caller.user_sub, request_id=request_id(request))) as uow:
        uow._bind(_resolve(uow, caller, bid))
        yield uow


def me_uow(request: Request) -> Iterator[UnitOfWork]:
    """FastAPI dependency for `/api/v1/me/...`: the signed-in user, no business."""
    caller = current_caller(request)
    with unit_of_work(Principal(user_sub=caller.user_sub, request_id=request_id(request))) as uow:
        uow._bind(_resolve(uow, caller, None))
        yield uow


def public_uow(request: Request) -> Iterator[UnitOfWork]:
    """FastAPI dependency for auth and share-link routes: no user, no business."""
    with unit_of_work(Principal(user_sub=None, request_id=request_id(request))) as uow:
        yield uow


BusinessUoW = Annotated[UnitOfWork, Depends(business_uow, scope="function")]
MeUoW = Annotated[UnitOfWork, Depends(me_uow, scope="function")]
PublicUoW = Annotated[UnitOfWork, Depends(public_uow, scope="function")]


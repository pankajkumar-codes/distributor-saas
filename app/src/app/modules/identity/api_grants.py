"""Support grants, the owner's side (LLD-2 §6.1, NF-1, TD-16).

An owner gives the support team read-only access to the business for a fixed time
(refdata support.grant_hours, 24 h in R1), and may end it early. One grant is active at a
time: a new one ends the one before. Owners and admins see the list, with how many pages
support viewed under each grant (the support.view audit rows).

Every route runs in `business_uow`. sg_tenant lets only an owner write a grant and
sg_tenant_read lets owners and admins read them, so the database holds the role rule as
well as `require()`; every query also filters by the bound business. A grant from
another business, or an unknown one, is the same 404 as an unknown business.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.modules.refdata import value_on
from platform_common import audit
from platform_common.clock import Clock, get_clock
from platform_common.errors import Conflict, Deny
from platform_common.ids import uuid7
from platform_common.permissions import Permission, require
from platform_common.uow import BusinessUoW, UnitOfWork, parse_id

router = APIRouter(tags=["support"])
GRANT = [Depends(require(Permission.SUPPORT_GRANT))]
VIEW = [Depends(require(Permission.AUDIT_VIEW))]
PAGE = 50  # grants shown; at most one a day in practice


class GrantIn(BaseModel):
    reason: str | None = Field(None, max_length=500)


class Person(BaseModel):
    user_id: uuid.UUID
    name: str


class GrantOut(BaseModel):
    id: uuid.UUID
    given_at: datetime
    expires_at: datetime
    given_by: Person
    reason: str | None
    status: str  # active | expired | revoked
    ended_at: datetime | None  # when it expired or was revoked; null while active
    ended_by: Person | None  # who revoked it (also the owner whose new grant replaced it)
    pages_viewed: int


class GrantsOut(BaseModel):
    grants: list[GrantOut]


def _business(uow: UnitOfWork) -> uuid.UUID:
    return uow.principal.business_id


_SELECT = """
select g.id, g.starts_at, g.expires_at, g.revoked_at, g.reason, g.granted_by, g.revoked_by,
       coalesce(gp.name, gp.email) as given_by_name, coalesce(rp.name, rp.email) as revoked_by_name,
       now() as now,
       (select count(*) from platform.v_audit_log v
         where v.business_id = g.business_id and v.support_grant_id = g.id
           and v.action = 'support.view') as pages_viewed
from identity.support_grants g
left join identity.member_profiles(array(
    select user_id from identity.memberships where business_id = :b)) gp on gp.user_id = g.granted_by
left join identity.member_profiles(array(
    select user_id from identity.memberships where business_id = :b)) rp on rp.user_id = g.revoked_by
where g.business_id = :b
"""


def _out(r) -> GrantOut:
    if r.revoked_at is not None:
        status, ended_at = "revoked", r.revoked_at
    elif r.expires_at <= r.now:
        status, ended_at = "expired", r.expires_at
    else:
        status, ended_at = "active", None
    return GrantOut(
        id=r.id,
        given_at=r.starts_at,
        expires_at=r.expires_at,
        given_by=Person(user_id=r.granted_by, name=r.given_by_name or "Former member"),
        reason=r.reason,
        status=status,
        ended_at=ended_at,
        ended_by=None
        if r.revoked_by is None
        else Person(user_id=r.revoked_by, name=r.revoked_by_name or "Former member"),
        pages_viewed=r.pages_viewed,
    )


def _one(uow: UnitOfWork, grant_id: uuid.UUID) -> GrantOut:
    row = uow.tx.execute(text(_SELECT + " and g.id = :g"), {"b": _business(uow), "g": grant_id}).one_or_none()
    if row is None:
        raise Deny("not_found")
    return _out(row)


def _end_active(uow: UnitOfWork) -> uuid.UUID | None:
    """Ends the business's active grant, if any, as revoked by the caller. Returns its ID."""
    return uow.tx.execute(
        text(
            "update identity.support_grants set revoked_at = now(), revoked_by = :me"
            " where business_id = :b and revoked_at is null and now() < expires_at returning id"
        ),
        {"b": _business(uow), "me": uow.principal.user_id},
    ).scalar()


@router.post("/b/{business_id}/support-grants", status_code=201, response_model=GrantOut, dependencies=GRANT)
def give_grant(body: GrantIn, uow: BusinessUoW, clock: Annotated[Clock, Depends(get_clock)]):
    """Gives support read-only access for support.grant_hours from now, ending the active
    grant if there is one."""
    bid = _business(uow)
    reason = (body.reason or "").strip() or None
    hours = value_on(uow.tx, "support.grant_hours", clock.today())
    # One active grant at a time even when two owners click at once: the second waits
    # here, then ends the grant the first just made.
    uow.tx.execute(text("select pg_advisory_xact_lock(hashtextextended('support_grant:' || :b, 0))"), {"b": str(bid)})
    replaced = _end_active(uow)
    grant_id = uuid7()
    expires_at = uow.tx.execute(
        text(
            "insert into identity.support_grants (id, business_id, granted_by, expires_at, reason)"
            " values (:id, :b, :me, now() + make_interval(hours => :h), :reason) returning expires_at"
        ),
        {"id": grant_id, "b": bid, "me": uow.principal.user_id, "h": hours, "reason": reason},
    ).scalar_one()
    data = {"expires_at": expires_at.isoformat()}
    if replaced is not None:
        data["replaced"] = str(replaced)
    audit.record(uow, "support.grant", "support_grant", grant_id, reason=reason, data=data)
    return _one(uow, grant_id)


@router.post("/b/{business_id}/support-grants/{grant_id}/revoke", response_model=GrantOut, dependencies=GRANT)
def revoke_grant(grant_id: str, uow: BusinessUoW):
    """Ends a grant now. Support's next request is refused: the resolver checks the
    grant on every request. A grant that already ended is 409 grant_ended."""
    gid = parse_id(grant_id)
    found = uow.tx.execute(
        text(
            "select revoked_at is null and now() < expires_at as active from identity.support_grants"
            " where id = :g and business_id = :b for update"
        ),
        {"g": gid, "b": _business(uow)},
    ).one_or_none()
    if found is None:
        raise Deny("not_found")
    if not found.active:
        raise Conflict("grant_ended", "This support access has already ended.")
    uow.tx.execute(
        text(
            "update identity.support_grants set revoked_at = now(), revoked_by = :me where id = :g and business_id = :b"
        ),
        {"g": gid, "b": _business(uow), "me": uow.principal.user_id},
    )
    audit.record(uow, "support.revoke", "support_grant", gid)
    return _one(uow, gid)


@router.get("/b/{business_id}/support-grants", response_model=GrantsOut, dependencies=VIEW)
def list_grants(uow: BusinessUoW):
    """Newest first: the active grant (if any) and past ones, with pages viewed."""
    rows = uow.tx.execute(
        text(_SELECT + " order by g.starts_at desc, g.id desc limit :n"), {"b": _business(uow), "n": PAGE}
    ).all()
    return GrantsOut(grants=[_out(r) for r in rows])

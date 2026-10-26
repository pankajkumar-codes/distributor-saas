"""S0a (c2) on PostgreSQL: identity.auth_resolve and the principal resolver (LLD-1 §6),
platform.support_grant_active and the support policies (LLD-0 §4.2), and owner-only
support grants (LLD-2 §2.4).

Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.modules.identity.interface import resolve_principal
from platform_common.auth import Caller
from platform_common.errors import Deny

from .conftest import PG_ADMIN_URL, PG_OWNER

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


def seed(sql, **params):
    with PG_OWNER["engine"].begin() as c:
        return c.execute(text(sql), params)


def user(sub, *, support=False):
    uid = uuid.uuid4()
    seed(
        "insert into identity.users (id, cognito_sub, email, is_support) values (:id, :sub, :email, :s)",
        id=uid, sub=sub, email=f"{sub}@example.com", s=support,
    )
    return uid


def session(uid, *, idle="0 minutes", expires_in="30 days", revoked=False):
    jti = str(uuid.uuid4())
    seed(
        "insert into identity.sessions (id, user_id, key_kind, key_value, auth_time, last_activity_at,"
        " absolute_expires_at, revoked_at) values (:id, :u, 'origin_jti', :jti, now(), now() - cast(:idle as interval),"
        " now() + cast(:exp as interval), case when :rev then now() end)",
        id=uuid.uuid4(), u=uid, jti=jti, idle=idle, exp=expires_in, rev=revoked,
    )
    return jti


def business(owner_id, *, status="active"):
    bid = uuid.uuid4()
    seed(
        "insert into identity.businesses (id, name, status, created_by) values (:b, 'Co', :s, :u)",
        b=bid, s=status, u=owner_id,
    )
    member(bid, owner_id, "owner")
    return bid


def member(bid, uid, role, status="active"):
    seed(
        "insert into identity.memberships (id, business_id, user_id, role, status) values (:id, :b, :u, :r, :s)",
        id=uuid.uuid4(), b=bid, u=uid, r=role, s=status,
    )


def grant(bid, by, *, starts="-1 hour", ends="23 hours", revoked=False):
    gid = uuid.uuid4()
    seed(
        "insert into identity.support_grants (id, business_id, granted_by, starts_at, expires_at, revoked_at)"
        " values (:g, :b, :u, now() + cast(:s as interval), now() + cast(:e as interval), case when :rev then now() end)",
        g=gid, b=bid, u=by, s=starts, e=ends, rev=revoked,
    )
    return gid


def resolve(svc, sub, jti, business_id=None):
    with Session(svc) as tx, tx.begin():
        return resolve_principal(tx, Caller(user_sub=sub, claims={"origin_jti": jti}), business_id, "r")


def deny_reason(svc, sub, jti, business_id=None):
    with pytest.raises(Deny) as e:
        resolve(svc, sub, jti, business_id)
    return e.value.reason


def as_ctx(c, uid, *, tenant=None, grant_id=None):
    c.execute(
        text(
            "select set_config('app.user_id', :u, true), set_config('app.tenant_id', :t, true),"
            " set_config('app.support_grant_id', :g, true)"
        ),
        {"u": str(uid), "t": str(tenant or ""), "g": str(grant_id or "")},
    )


# --- auth_resolve and the resolver -------------------------------------------------


def test_the_api_registers_identitys_resolver(pg_client):
    from platform_common import uow

    assert uow._resolver is resolve_principal


def test_a_live_session_resolves_without_a_business(pg_client):
    _, svc = pg_client
    asha = user("asha")
    p = resolve(svc, "asha", session(asha))
    assert (p.user_id, p.business_id, p.role, p.support_grant_id) == (asha, None, None, None)
    assert p.session_id is not None


@pytest.mark.parametrize(
    "kwargs", [{"revoked": True}, {"idle": "25 hours"}, {"expires_in": "-1 minute"}], ids=["revoked", "idle", "expired"]
)
def test_dead_sessions_are_session_invalid(pg_client, kwargs):
    _, svc = pg_client
    jti = session(user("asha"), **kwargs)
    assert deny_reason(svc, "asha", jti) == "session_invalid"


def test_unknown_user_or_someone_elses_session_key_is_session_invalid(pg_client):
    _, svc = pg_client
    user("asha")
    ravi_jti = session(user("ravi"))
    assert deny_reason(svc, "nobody", ravi_jti) == "session_invalid"
    assert deny_reason(svc, "asha", ravi_jti) == "session_invalid"
    assert deny_reason(svc, "asha", None) == "session_invalid"


def test_business_membership_decides(pg_client):
    _, svc = pg_client
    asha, ravi, meena = user("asha"), user("ravi"), user("meena")
    a = business(asha)
    member(a, ravi, "billing")
    member(a, meena, "ca", status="deactivated")
    assert resolve(svc, "asha", session(asha), a).role == "owner"
    assert resolve(svc, "ravi", session(ravi), a).role == "billing"
    assert deny_reason(svc, "meena", session(meena), a) == "not_member"
    outsider = user("eve")
    assert deny_reason(svc, "eve", session(outsider), a) == "not_member"
    assert deny_reason(svc, "asha", session(asha), uuid.uuid4()) == "not_found"
    closed = business(asha, status="closed")
    assert deny_reason(svc, "asha", session(asha), closed) == "not_found"
    # A dead session wins over everything else.
    assert deny_reason(svc, "asha", session(asha, revoked=True), a) == "session_invalid"


def test_support_user_needs_a_live_grant(pg_client):
    _, svc = pg_client
    asha, sam = user("asha"), user("sam", support=True)
    a = business(asha)
    jti = session(sam)
    assert deny_reason(svc, "sam", jti, a) == "support_no_grant"
    grant(a, asha, revoked=True)
    grant(a, asha, starts="-2 days", ends="-1 day")
    assert deny_reason(svc, "sam", jti, a) == "support_no_grant"
    short, long = grant(a, asha, ends="1 hour"), grant(a, asha, ends="20 hours")
    p = resolve(svc, "sam", jti, a)
    assert (p.role, p.support_grant_id) == (None, long)
    assert short != long
    # A grant for one business opens no other.
    b = business(asha)
    assert deny_reason(svc, "sam", jti, b) == "support_no_grant"


def test_touch_moves_the_idle_clock_at_most_once_a_minute(pg_client):
    _, svc = pg_client
    asha = user("asha")
    stale, fresh = session(asha, idle="10 minutes"), session(asha, idle="30 seconds")
    resolve(svc, "asha", stale)
    resolve(svc, "asha", fresh)
    rows = dict(
        seed(
            "select key_value, now() - last_activity_at < interval '5 seconds' from identity.sessions"
            " where key_value in (:a, :b)",
            a=stale, b=fresh,
        ).all()
    )
    assert rows == {stale: True, fresh: False}


def test_no_touch_in_a_read_only_transaction_and_none_when_asked(pg_client):
    _, svc = pg_client
    asha = user("asha")
    jti = session(asha, idle="10 minutes")
    with Session(svc) as tx, tx.begin():
        tx.execute(text("set transaction read only"))
        resolve_principal(tx, Caller(user_sub="asha", claims={"origin_jti": jti}), None, "r")
    with Session(svc) as tx, tx.begin():
        resolve_principal(tx, Caller(user_sub="asha", claims={"origin_jti": jti}), None, "r", touch=False)
    moved = seed("select now() - last_activity_at < interval '5 minutes' from identity.sessions where key_value = :k", k=jti)
    assert moved.scalar() is False


def test_only_app_rw_may_call_auth_resolve(pg_client):
    _, svc = pg_client
    with pytest.raises(DBAPIError, match="permission denied"):
        with svc.begin() as c:
            c.execute(text("set local role app_ro"))
            c.execute(text("select * from identity.auth_resolve('origin_jti', 'x', 'asha', null, false)"))


def test_debug_sessions_exist_only_in_local_and_test(pg_client, monkeypatch):
    _, svc = pg_client
    with Session(svc) as tx, tx.begin():
        p = resolve_principal(tx, Caller(user_sub="dev"), None, "r")
    assert p.user_id is not None and p.session_id is not None
    monkeypatch.setenv("PLATFORM_ENV", "prod")
    with Session(svc) as tx, tx.begin(), pytest.raises(Deny, match="session_invalid"):
        resolve_principal(tx, Caller(user_sub="dev2"), None, "r")
    assert seed("select count(*) from identity.users where cognito_sub = 'dev2'").scalar() == 0


# --- support_grant_active and support reads ---------------------------------------


def test_support_reads_only_the_business_of_the_named_grant(pg_client):
    _, svc = pg_client
    asha, sam, bob = user("asha"), user("sam", support=True), user("bob")
    a, b = business(asha), business(asha)
    ga, gb = grant(a, asha), grant(b, asha)
    with svc.begin() as c:
        as_ctx(c, sam, grant_id=ga)  # no tenant bound: only support_read can admit
        assert c.execute(text("select id from identity.businesses")).scalars().all() == [a]
        assert c.execute(text("select count(*) from identity.memberships")).scalar() == 1
        assert c.execute(text("select platform.support_grant_active(:b)"), {"b": b}).scalar() is False
    with svc.begin() as c:
        as_ctx(c, sam, grant_id=gb)
        assert c.execute(text("select id from identity.businesses")).scalars().all() == [b]
    for uid, gid in ((bob, ga), (sam, None), (sam, uuid.uuid4())):
        with svc.begin() as c:
            as_ctx(c, uid, grant_id=gid)
            assert c.execute(text("select count(*) from identity.businesses")).scalar() == 0
    seed("update identity.support_grants set revoked_at = now() where id = :g", g=ga)
    with svc.begin() as c:
        as_ctx(c, sam, grant_id=ga)
        assert c.execute(text("select count(*) from identity.businesses")).scalar() == 0


def test_support_can_write_nothing_but_its_view_record(pg_client):
    _, svc = pg_client
    asha, sam, bob = user("asha"), user("sam", support=True), user("bob")
    a = business(asha)
    ga = grant(a, asha)

    def view(c, *, action="support.view", uid=sam, gid=ga):
        c.execute(
            text(
                "insert into platform.audit_log (id, business_id, user_id, support_grant_id, action, target_kind, request_id)"
                " values (:i, :b, :u, :g, :a, 'route', 'r')"
            ),
            {"i": uuid.uuid4(), "b": a, "u": uid, "g": gid, "a": action},
        )

    with svc.begin() as c:
        as_ctx(c, sam, tenant=a, grant_id=ga)
        view(c)
    refused = [
        lambda c: view(c, action="member.add"),
        lambda c: view(c, uid=bob),
        lambda c: view(c, gid=None),
        lambda c: c.execute(
            text("insert into identity.support_grants (id, business_id, granted_by, expires_at) values (:g, :b, :u, now())"),
            {"g": uuid.uuid4(), "b": a, "u": sam},
        ),
    ]
    for attempt in refused:
        with pytest.raises(DBAPIError, match="row-level security"):
            with svc.begin() as c:
                as_ctx(c, sam, tenant=a, grant_id=ga)
                attempt(c)
    with svc.begin() as c:
        as_ctx(c, sam, tenant=a, grant_id=ga)
        assert c.execute(text("update identity.memberships set role = 'ca'")).rowcount == 0
    # A non-support user holding the grant id can't record a view either.
    with pytest.raises(DBAPIError, match="row-level security"):
        with svc.begin() as c:
            as_ctx(c, bob, tenant=a, grant_id=ga)
            view(c, uid=bob)
    assert seed("select count(*) from platform.audit_log where action = 'support.view'").scalar() == 1


# --- owner-only support grants ----------------------------------------------------


def test_only_the_owner_writes_support_grants_and_admins_may_read_them(pg_client):
    _, svc = pg_client
    asha, adi, ravi = user("asha"), user("adi"), user("ravi")
    a = business(asha)
    member(a, adi, "admin")
    member(a, ravi, "billing")

    def insert(c, uid):
        c.execute(
            text(
                "insert into identity.support_grants (id, business_id, granted_by, expires_at)"
                " values (:g, :b, :u, now() + interval '24 hours')"
            ),
            {"g": uuid.uuid4(), "b": a, "u": uid},
        )

    with svc.begin() as c:
        as_ctx(c, asha, tenant=a)
        insert(c, asha)
    for uid in (adi, ravi):
        with pytest.raises(DBAPIError, match="row-level security"):
            with svc.begin() as c:
                as_ctx(c, uid, tenant=a)
                insert(c, uid)
    with svc.begin() as c:
        as_ctx(c, adi, tenant=a)
        assert c.execute(text("select count(*) from identity.support_grants")).scalar() == 1
        assert c.execute(text("update identity.support_grants set revoked_at = now()")).rowcount == 0
        c.execute(text("set local role app_ro"))
        assert c.execute(text("select count(*) from identity.support_grants")).scalar() == 1
    with svc.begin() as c:
        as_ctx(c, ravi, tenant=a)
        assert c.execute(text("select count(*) from identity.support_grants")).scalar() == 0
        c.execute(text("set local role app_ro"))
        assert c.execute(text("select count(*) from identity.support_grants")).scalar() == 0
    with svc.begin() as c:
        as_ctx(c, asha, tenant=a)
        assert c.execute(text("update identity.support_grants set revoked_at = now()")).rowcount == 1

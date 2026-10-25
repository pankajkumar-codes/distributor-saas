"""Audit log and rate counters on PostgreSQL, as app_rw, so RLS applies (LLD-0 §3.6, §3.9).

Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, make_url, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import sessionmaker

from platform_common import audit, rate
from platform_common import uow as uow_mod
from platform_common.clock import FrozenClock
from platform_common.errors import Invalid, RateLimited
from platform_common.uow import Principal, unit_of_work

ADMIN_URL = os.environ.get("PG_ADMIN_URL")
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="PG_ADMIN_URL not set")
MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
A, B = uuid.uuid4(), uuid.uuid4()
ASHA, RAVI = uuid.uuid4(), uuid.uuid4()


@pytest.fixture(scope="module")
def factory():
    dbname = f"t_{uuid.uuid4().hex[:10]}"
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f"create database {dbname}"))
        for role in ("app_rw", "app_ro"):
            c.execute(
                text(
                    f"do $$ begin if not exists (select from pg_roles where rolname = '{role}') "
                    f"then create role {role} nologin; end if; end $$"
                )
            )
        c.execute(text("grant app_ro to app_rw"))
    url = make_url(ADMIN_URL).set(database=dbname)
    with create_engine(url).begin() as c:
        for f in sorted(MIGRATIONS.glob("*.sql")):
            c.exec_driver_sql(f.read_text())
    eng = create_engine(url)

    @event.listens_for(eng, "connect")
    def _as_app_rw(dbapi_conn, _):
        with dbapi_conn.cursor() as cur:
            cur.execute("set role app_rw")
        dbapi_conn.commit()

    f = sessionmaker(bind=eng, expire_on_commit=False)
    uow_mod.set_session_factory(f)
    yield f
    uow_mod.set_session_factory(None)
    eng.dispose()
    with admin.connect() as c:
        c.execute(text(f"drop database {dbname} with (force)"))


def P(user=ASHA, business=None, grant=None):
    return Principal(user_sub="sub", request_id="req-1", user_id=user, business_id=business, support_grant_id=grant)


def actions(principal, read_only=False):
    with unit_of_work(principal, read_only=read_only) as uow:
        return sorted(r[0] for r in uow.tx.execute(text("select action from platform.audit_log")))


def test_business_rows_stay_in_their_business(factory):
    with unit_of_work(P(business=A)) as uow:
        audit.record(uow, "business.create", "business", A, data={"registration_kind": "gstin"})
    assert actions(P(business=A)) == ["business.create"]
    assert actions(P(business=A), read_only=True) == ["business.create"]  # app_ro reads too
    assert actions(P(user=RAVI, business=B)) == []
    with pytest.raises(ProgrammingError, match="row-level security"):
        with unit_of_work(P(business=A)) as uow:
            uow.tx.execute(
                text(
                    "insert into platform.audit_log (id, business_id, action, target_kind, request_id)"
                    " values (:i, :b, 'business.create', 'business', 'r')"
                ),
                {"i": uuid.uuid4(), "b": B},
            )


def test_user_level_rows_belong_to_their_user(factory):
    with unit_of_work(P(user=RAVI)) as uow:
        audit.record(uow, "auth.signin", "user", RAVI, data={"totp": True})
    assert "auth.signin" in actions(P(user=RAVI))
    assert "auth.signin" not in actions(P(user=ASHA))
    with pytest.raises(ProgrammingError, match="row-level security"):
        with unit_of_work(P(user=ASHA)) as uow:
            uow.tx.execute(
                text(
                    "insert into platform.audit_log (id, user_id, action, target_kind, request_id)"
                    " values (:i, :u, 'auth.signin', 'user', 'r')"
                ),
                {"i": uuid.uuid4(), "u": RAVI},
            )


def test_a_support_grant_sees_and_writes_no_business_rows(factory):
    with unit_of_work(P(business=A)) as uow:
        audit.record(uow, "business.create", "business", A)
    assert "business.create" not in actions(P(business=A, grant=uuid.uuid4()))
    with pytest.raises(ProgrammingError, match="row-level security"):
        with unit_of_work(P(business=A, grant=uuid.uuid4())) as uow:
            audit.record(uow, "business.create", "business", A)


@pytest.mark.parametrize("sql", ["update platform.audit_log set reason = 'x'", "delete from platform.audit_log"])
def test_the_app_cannot_change_or_delete_audit_rows(factory, sql):
    with pytest.raises(ProgrammingError, match="permission denied"):
        with unit_of_work(P(business=A)) as uow:
            uow.tx.execute(text(sql))


def test_audit_refuses_unregistered_actions_extra_data_and_anonymous_user_rows(factory):
    with unit_of_work(P(business=A)) as uow:
        with pytest.raises(ValueError, match="not registered"):
            audit.record(uow, "made.up", "thing")
        with pytest.raises(ValueError, match="not allowed"):
            audit.record(uow, "auth.signup", "user", data={"email": "a@example.com"})
    with unit_of_work(P(user=None)) as uow:
        with pytest.raises(ValueError, match="signed-in user"):
            audit.record(uow, "auth.signup", "user")


@pytest.mark.parametrize("reason", [None, "", "  "])
def test_reason_required_actions_refuse_a_blank_reason_and_write_nothing(factory, reason):
    business = uuid.uuid4()
    with unit_of_work(P(business=business)) as uow:
        with pytest.raises(Invalid) as e:
            audit.record(uow, "members.deactivate", "member", RAVI, reason=reason)
    assert e.value.code == "reason_required"
    assert actions(P(business=business)) == []


def test_reason_required_actions_store_the_stripped_reason(factory):
    business = uuid.uuid4()
    with unit_of_work(P(business=business)) as uow:
        audit.record(uow, "members.deactivate", "member", RAVI, reason="  left the firm ")
    with unit_of_work(P(business=business)) as uow:
        assert uow.tx.execute(text("select reason from platform.audit_log")).scalar_one() == "left the firm"


def test_rate_hit_counts_in_its_own_transaction_and_resets_next_window(factory):
    clock = FrozenClock(datetime(2026, 10, 25, 10, 0, 30, tzinfo=UTC))
    key = rate.bucket("signin:email", f"{uuid.uuid4()}@example.com")
    for _ in range(3):
        rate.hit(key, 3, timedelta(minutes=15), clock=clock)
    with pytest.raises(RateLimited) as e:
        rate.hit(key, 3, timedelta(minutes=15), clock=clock)
    assert e.value.retry_after == 15 * 60 - 30
    clock.advance(timedelta(minutes=15))
    rate.hit(key, 3, timedelta(minutes=15), clock=clock)
    with factory() as s:
        stored = s.execute(text("select bucket from platform.rate_counters where bucket = :b"), {"b": key}).all()
    assert stored and "@" not in key


def test_rate_hit_refuses_inside_a_unit_of_work(factory):
    with unit_of_work(P()):
        with pytest.raises(RuntimeError, match="before the unit of work"):
            rate.hit(rate.bucket("x", "y"), 1, timedelta(minutes=1))

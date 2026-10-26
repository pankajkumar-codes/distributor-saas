"""identity.auth_* functions on PostgreSQL, called as app_rw (LLD-1 §3.5, §5.1-5.2, §5.6).

Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import threading
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from app.modules.identity import codes
from platform_common.ids import uuid7

from .conftest import PG_ADMIN_URL

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")
EMAIL = "asha@example.com"
TTL = timedelta(minutes=10)


@pytest.fixture()
def dbs(pg_client):
    _, app_rw = pg_client
    admin = create_engine(make_url(PG_ADMIN_URL).set(database=app_rw.url.database))
    yield app_rw, admin
    admin.dispose()


def call(eng, sql, **params):
    with eng.begin() as c:
        return c.execute(text(f"select {sql}"), params).scalar()


def issue(eng, code="042424", email=EMAIL, purpose="signup", max_tries=5):
    call(
        eng,
        "identity.auth_issue_code(:i, :p, :e, :h, :t, :m)",
        i=uuid7(),
        p=purpose,
        e=email,
        h=codes.code_hmac(purpose, email, code),
        t=TTL,
        m=max_tries,
    )


def check(eng, code="042424", email=EMAIL, purpose="signup"):
    return call(
        eng, "identity.auth_check_code(:p, :e, :h)", p=purpose, e=email, h=codes.code_hmac(purpose, email, code)
    )


def code_row(admin, email=EMAIL):
    with admin.connect() as c:
        return c.execute(
            text(
                "select tries, voided_at, claimed_at from identity.verification_codes where email = :e order by created_at desc limit 1"
            ),
            {"e": email},
        ).one()


def create_user(eng, email=EMAIL):
    user_id = uuid7()
    call(eng, "identity.auth_create_user(:i, :s, :e)", i=user_id, s=f"sub-{uuid.uuid4()}", e=email)
    return user_id


@pytest.mark.parametrize("table", ["sessions", "pending_signups", "verification_codes"])
def test_app_rw_cannot_read_auth_tables_directly(dbs, table):  # AC-9
    app_rw, _ = dbs
    with pytest.raises(ProgrammingError, match="permission denied"):
        with app_rw.connect() as c:
            c.execute(text(f"select 1 from identity.{table}"))


def test_right_code_is_claimed_once_and_consumed_once(dbs):
    app_rw, _ = dbs
    issue(app_rw)
    code_id = check(app_rw)
    assert code_id is not None
    assert check(app_rw) is None  # claimed in the last 60 s (AC-4)
    assert call(app_rw, "identity.auth_consume_code(:i)", i=code_id) is True
    assert call(app_rw, "identity.auth_consume_code(:i)", i=code_id) is False
    assert check(app_rw) is None  # no live code left


def test_wrong_tries_count_and_the_last_one_voids(dbs):  # AC-1
    app_rw, admin = dbs
    issue(app_rw, max_tries=5)
    for n in range(1, 5):
        assert check(app_rw, "000000") is None
        assert code_row(admin).tries == n and code_row(admin).voided_at is None
    assert check(app_rw, "000000") is None
    assert code_row(admin).voided_at is not None
    assert check(app_rw) is None  # even the right code, once voided


def test_expired_code_is_refused(dbs):  # AC-1
    app_rw, admin = dbs
    issue(app_rw)
    with admin.begin() as c:
        c.execute(text("update identity.verification_codes set expires_at = now() - interval '1 second'"))
    assert check(app_rw) is None


def test_a_new_code_voids_the_old_one(dbs):
    app_rw, _ = dbs
    issue(app_rw, "111111")
    issue(app_rw, "222222")
    assert check(app_rw, "111111") is None
    assert check(app_rw, "222222") is not None


def test_signup_code_for_an_existing_account_is_refused_like_a_wrong_one(dbs):  # RM3-7
    app_rw, admin = dbs
    issue(app_rw)
    create_user(app_rw)
    assert check(app_rw) is None
    assert code_row(admin).tries == 1


def test_reset_needs_an_account_and_codes_dont_cross_purposes(dbs):
    app_rw, _ = dbs
    issue(app_rw, purpose="reset")
    assert check(app_rw, purpose="reset") is None  # no account yet
    create_user(app_rw)
    issue(app_rw, "333333", purpose="reset")
    assert check(app_rw, "333333", purpose="signup") is None
    assert check(app_rw, "333333", purpose="reset") is not None


def test_emails_are_normalised_and_one_email_has_one_account(dbs):  # AC-5
    app_rw, admin = dbs
    issue(app_rw, email="  Asha@Example.COM ")
    assert check(app_rw, email=EMAIL) is not None
    user_id = create_user(app_rw, email=" ASHA@example.com")
    assert call(app_rw, "identity.auth_user_by_email(:e)", e="asha@EXAMPLE.com ") == user_id
    with admin.connect() as c:
        assert c.execute(text("select count(*) from identity.pending_signups")).scalar() == 0
    with pytest.raises(IntegrityError):
        create_user(app_rw, email="Asha@example.com")


def test_open_session_sets_the_absolute_expiry(dbs):
    app_rw, admin = dbs
    user_id = create_user(app_rw)
    call(
        app_rw,
        "identity.auth_open_session(:i, :u, 'origin_jti', :k, now(), 30)",
        i=uuid7(),
        u=user_id,
        k=str(uuid.uuid4()),
    )
    with admin.connect() as c:
        days = c.execute(
            text("select extract(day from absolute_expires_at - created_at) from identity.sessions")
        ).scalar()
    assert days == 30


def concurrently(n, fn):
    """Run fn on n connections at once; return results and raised exceptions."""
    results, barrier = [], threading.Barrier(n)

    def run(i):
        barrier.wait()
        try:
            results.append(fn(i))
        except Exception as e:  # noqa: BLE001 - the test asserts on it
            results.append(e)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def test_two_concurrent_checks_with_the_right_code_claim_once(dbs):  # AC-4
    app_rw, _ = dbs
    issue(app_rw)
    results = concurrently(2, lambda _: check(app_rw))
    assert sorted(r is not None for r in results) == [False, True]


@pytest.mark.parametrize("purpose", ["reset", "signup"])
def test_concurrent_code_requests_for_one_email_all_succeed(dbs, purpose):
    app_rw, admin = dbs
    if purpose == "reset":
        create_user(app_rw)
    results = concurrently(4, lambda i: issue(app_rw, f"{i:06d}", purpose=purpose))
    assert results == [None] * 4  # no UniqueViolation, so no 500 that reveals the account
    with admin.connect() as c:
        live = c.execute(
            text("select count(*) from identity.verification_codes where consumed_at is null and voided_at is null")
        ).scalar()
    assert live == 1

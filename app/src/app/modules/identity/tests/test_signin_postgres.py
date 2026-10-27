"""POST /auth/signin and /auth/signin/totp on PostgreSQL, as app_rw (LLD-1 §5.3, §5.4,
L1-7, L1-10, AC-14, AC-15).

Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie

import pytest
from sqlalchemy import text

from platform_common.clock import FrozenClock

from .auth_env import EMAIL, ORIGIN, PASSWORD, auth_env, one, sign_up, verify
from .conftest import PG_ADMIN_URL

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")

SECRET = "JBSWY3DPEHPK3PXP"  # a made-up TOTP secret for the fake provider


@pytest.fixture()
def env():
    with auth_env() as e:
        client, _, mail, _ = e
        assert verify(client, sign_up(client, mail).params["code"]).status_code == 200
        yield e


def signin(client, email=EMAIL, password=PASSWORD, headers=ORIGIN):
    return client.post("/api/v1/auth/signin", json={"email": email, "password": password}, headers=headers)


def totp(client, challenge, code, email=EMAIL):
    return client.post(
        "/api/v1/auth/signin/totp", json={"email": email, "challenge": challenge, "code": code}, headers=ORIGIN
    )


def enrol(idp, email=EMAIL):
    u = idp.user(email)
    u.totp_secret, u.totp_enabled = SECRET, True
    return idp.totp_code(SECRET)


def cookie(r):
    return SimpleCookie(r.headers["set-cookie"])["__Secure-rt"]


def test_sign_in_opens_a_session_and_sets_the_cookie(env):
    client, _, _, admin = env
    r = signin(client, email=" Asha@Example.com ")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"access_token", "expires_in", "user", "memberships"}
    assert body["user"]["email"] == EMAIL and body["memberships"] == []
    c = cookie(r)
    assert (c["path"], c["samesite"], c["max-age"], bool(c["httponly"]), bool(c["secure"])) == (
        "/api/v1/auth",
        "strict",
        "2592000",
        True,
        True,
    )
    assert one(admin, "select count(*) from identity.sessions where revoked_at is null") == 2  # sign-up's + this
    assert (
        client.post("/api/v1/auth/refresh", headers={**ORIGIN, "cookie": f"__Secure-rt={c.value}"}).status_code == 200
    )


def test_sign_in_writes_a_user_level_audit_row(env):
    client, _, _, admin = env
    assert signin(client).status_code == 200
    with admin.connect() as c:
        rows = c.execute(
            text(
                "select a.target_kind, a.business_id, a.data, a.user_id = s.user_id"
                " from platform.audit_log a join identity.sessions s on s.id = a.target_id"
                " where a.action = 'auth.signin'"
            )
        ).all()
    assert [tuple(r) for r in rows] == [("session", None, {"totp": False}, True)]


def test_sign_in_lists_the_callers_memberships(env):
    client, idp, _, _ = env
    body = {
        "registration": {"kind": "gstin", "gstin": "19AAPFU0939F1ZS"},
        "legal_name": "Vashi Essentials LLP",
        "trade_name": "Vashi Essentials",
        "address": {"line1": "12 Park St", "city": "Kolkata", "pin": "700016", "state_code": "19"},
        "turnover_band": "up_to_threshold",
        "einvoice_history": "no",
    }
    made = client.post(
        "/api/v1/b", json=body, headers={"x-debug-user": idp.user(EMAIL).sub, "Idempotency-Key": uuid.uuid4().hex}
    )
    assert made.status_code == 201, made.text
    r = signin(client)
    assert r.json()["memberships"] == [
        {
            "business_id": made.json()["business_id"],
            "display_name": "Vashi Essentials",
            "gstin": "19AAPFU0939F1ZS",
            "role": "owner",
        }
    ]


@pytest.mark.parametrize(
    "email, password",
    [(EMAIL, "wrong password here"), ("nobody@example.com", PASSWORD), ("nobody@example.com", "wrong password here")],
)
def test_a_wrong_password_and_an_unknown_email_look_the_same(env, email, password):
    client, _, _, admin = env
    r = signin(client, email=email, password=password)
    assert (r.status_code, r.json()["error"]["code"]) == (401, "signin_not_accepted")
    assert "set-cookie" not in r.headers
    assert one(admin, "select count(*) from identity.sessions") == 1


def test_a_provider_user_with_no_users_row_is_refused(env):
    client, idp, _, admin = env
    idp.create_user("half@example.com", PASSWORD)  # a sign-up that stopped after the provider step
    r = signin(client, email="half@example.com")
    assert (r.status_code, r.json()["error"]["code"]) == (401, "signin_not_accepted")
    assert one(admin, "select count(*) from identity.sessions") == 1
    assert all(t.revoked for t in idp._refresh.values() if t.sub == idp.user("half@example.com").sub)


@pytest.mark.parametrize("headers", [{}, {"origin": "https://evil.example"}])
def test_sign_in_from_another_origin_is_refused(env, headers):
    client, _, _, _ = env
    r = signin(client, headers=headers)
    assert r.status_code == 401 and "access_token" not in r.text


def test_the_eleventh_sign_in_for_one_email_in_15_minutes_is_429(env):  # L1-10
    client, _, _, _ = env
    for _ in range(10):
        assert signin(client, password="wrong password here").status_code == 401
    r = signin(client)  # even the right password
    assert r.status_code == 429 and "retry-after" in r.headers


def test_totp_users_get_a_challenge_then_sign_in_with_the_code(env):  # AC-14
    client, idp, _, admin = env
    code = enrol(idp)
    r = signin(client)
    assert r.status_code == 200 and set(r.json()) == {"step", "challenge"} and r.json()["step"] == "totp"
    assert "set-cookie" not in r.headers
    assert one(admin, "select count(*) from identity.sessions") == 1  # no session before the code
    done = totp(client, r.json()["challenge"], code)
    assert done.status_code == 200, done.text
    assert set(done.json()) == {"access_token", "expires_in", "user", "memberships"} and cookie(done).value
    assert one(admin, "select data from platform.audit_log where action = 'auth.signin'") == {"totp": True}


def test_a_wrong_totp_code_is_refused_and_the_challenge_still_works(env):  # AC-14
    client, idp, _, _ = env
    code = enrol(idp)
    challenge = signin(client).json()["challenge"]
    wrong = totp(client, challenge, "000000" if code != "000000" else "111111")
    assert (wrong.status_code, wrong.json()["error"]["code"]) == (401, "totp_not_accepted")
    assert wrong.json()["challenge"] == challenge
    assert totp(client, wrong.json()["challenge"], code).status_code == 200


def test_an_expired_or_unknown_challenge_is_signin_expired(env):
    client, idp, _, _ = env
    code = enrol(idp)
    challenge = signin(client).json()["challenge"]
    idp._clock = FrozenClock(datetime.now(UTC) + timedelta(minutes=4))  # the challenge lives 3 minutes
    r = totp(client, challenge, code)
    assert (r.status_code, r.json()["error"]["code"]) == (401, "signin_expired")
    r = totp(client, "made-up", code)
    assert (r.status_code, r.json()["error"]["code"]) == (401, "signin_expired")


def test_the_sixth_totp_try_for_one_email_in_15_minutes_is_429(env):  # L1-10
    client, idp, _, _ = env
    code = enrol(idp)
    challenge = signin(client).json()["challenge"]
    for _ in range(5):
        assert totp(client, challenge, "000000" if code != "000000" else "111111").status_code == 401
    assert totp(client, challenge, code).status_code == 429


def test_a_totp_answer_under_another_email_is_refused(env):
    client, idp, mail, admin = env
    ravi = verify(client, sign_up(client, mail, email="ravi@example.com").params["code"], email="ravi@example.com")
    assert ravi.status_code == 200
    code = enrol(idp)
    challenge = signin(client).json()["challenge"]
    r = totp(client, challenge, code, email="ravi@example.com")  # Asha's challenge, Ravi's email
    assert (r.status_code, r.json()["error"]["code"]) == (401, "signin_not_accepted")
    assert one(admin, "select count(*) from identity.sessions") == 2  # the two sign-ups' only


def test_no_secret_reaches_the_logs(env, caplog):  # AC-15
    client, idp, _, _ = env
    caplog.set_level(logging.DEBUG)
    code = enrol(idp)
    challenge = signin(client).json()["challenge"]
    totp(client, challenge, "000000" if code != "000000" else "111111")
    done = totp(client, challenge, code)
    signin(client, password="wrong password here")
    secrets = [PASSWORD, challenge, code, done.json()["access_token"], cookie(done).value]
    assert not [s for s in secrets for rec in caplog.records if s in rec.getMessage()]

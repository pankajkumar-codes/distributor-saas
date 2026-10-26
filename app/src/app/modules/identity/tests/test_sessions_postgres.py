"""POST /auth/refresh and /auth/signout on PostgreSQL, as app_rw (LLD-1 §5.5, §5.7, AC-6, AC-16).

Skipped unless PG_ADMIN_URL points at a disposable server.
"""

from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie

import pytest
from sqlalchemy import text

from platform_common.clock import FrozenClock

from .auth_env import ORIGIN, auth_env, one, sign_up, verify
from .conftest import PG_ADMIN_URL

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


@pytest.fixture()
def env():
    with auth_env() as e:
        yield e


def signed_in(env):
    client, _, mail, _ = env
    r = verify(client, sign_up(client, mail).params["code"])
    assert r.status_code == 200, r.text
    return r.json()["access_token"], SimpleCookie(r.headers["set-cookie"])["__Secure-rt"].value


def refresh(client, rt, headers=ORIGIN):
    cookie = {"cookie": f"__Secure-rt={rt}"} if rt else {}
    return client.post("/api/v1/auth/refresh", headers={**headers, **cookie})


def signout(client, access=None, rt=None):
    headers = {"authorization": f"Bearer {access}"} if access else {}
    if rt:
        headers["cookie"] = f"__Secure-rt={rt}"
    return client.post("/api/v1/auth/signout", headers=headers)


def cleared(r):
    return "Max-Age=0" in r.headers.get("set-cookie", "") and "__Secure-rt=" in r.headers["set-cookie"]


def test_refresh_returns_a_new_access_token_and_keeps_the_cookie(env):
    client = env[0]
    access, rt = signed_in(env)
    r = refresh(client, rt)
    assert r.status_code == 200, r.text
    assert set(r.json()) == {"access_token", "expires_in"} and r.json()["access_token"] != access
    assert "set-cookie" not in r.headers  # not rotated (L1-5)


@pytest.mark.parametrize("headers", [{}, {"origin": "https://evil.example"}])
def test_refresh_from_another_origin_is_401_and_clears_the_cookie(env, headers):  # AC-16
    client = env[0]
    _, rt = signed_in(env)
    r = refresh(client, rt, headers=headers)
    assert r.status_code == 401 and r.json()["error"]["code"] == "session_invalid" and cleared(r)


def test_refresh_without_the_cookie_or_with_a_bad_one_is_401(env):  # AC-16
    client = env[0]
    assert refresh(client, None).status_code == 401
    r = refresh(client, "not-a-token")
    assert r.status_code == 401 and cleared(r)


@pytest.mark.parametrize(
    "sql",
    [
        "update identity.sessions set last_activity_at = now() - interval '25 hours'",  # idle
        "update identity.sessions set absolute_expires_at = now() - interval '1 second'",  # 30 days
        "update identity.sessions set revoked_at = now(), revoke_reason = 'password_change'",
    ],
)
def test_refresh_needs_a_live_session_row(env, sql):  # AC-6
    client, _, _, admin = env
    _, rt = signed_in(env)
    with admin.begin() as c:
        c.execute(text(sql))
    r = refresh(client, rt)
    assert r.status_code == 401 and cleared(r)


def test_background_refresh_does_not_move_the_idle_clock(env):  # L1-8
    client, _, _, admin = env
    _, rt = signed_in(env)
    with admin.begin() as c:
        c.execute(text("update identity.sessions set last_activity_at = now() - interval '2 hours'"))
    before = one(admin, "select last_activity_at from identity.sessions")
    assert refresh(client, rt, headers={**ORIGIN, "x-background": "1"}).status_code == 200
    assert one(admin, "select last_activity_at from identity.sessions") == before
    assert refresh(client, rt).status_code == 200
    assert one(admin, "select last_activity_at from identity.sessions") > before


def test_sign_out_revokes_the_session_and_the_refresh_token(env):  # AC-6
    client, _, _, admin = env
    access, rt = signed_in(env)
    r = signout(client, access, rt)
    assert r.status_code == 204 and cleared(r)
    assert one(admin, "select revoke_reason from identity.sessions") == "signout"
    assert refresh(client, rt).status_code == 401


def test_sign_out_accepts_an_expired_access_token(env):  # §5.7: sign out after a long idle
    client, idp, _, admin = env
    idp._clock = FrozenClock(datetime.now(UTC) - timedelta(hours=1))  # tokens minted an hour ago
    access, rt = signed_in(env)
    assert signout(client, access, rt).status_code == 204
    assert one(admin, "select revoke_reason from identity.sessions") == "signout"


@pytest.mark.parametrize("access", [None, "garbage", "a.b.c"])
def test_sign_out_is_always_204(env, access):
    client, _, _, admin = env
    signed_in(env)
    r = signout(client, access)
    assert r.status_code == 204 and cleared(r)
    assert one(admin, "select count(*) from identity.sessions where revoked_at is null") == 1


def test_a_token_cannot_revoke_another_users_session(env):
    client, _, mail, admin = env
    access, _ = signed_in(env)
    r = verify(client, sign_up(client, mail, email="ravi@example.com").params["code"], email="ravi@example.com")
    assert r.status_code == 200
    assert signout(client, access).status_code == 204
    assert one(admin, "select count(*) from identity.sessions where revoked_at is null") == 1

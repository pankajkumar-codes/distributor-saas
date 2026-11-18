"""One active session per user: POST /auth/signin and /auth/signin/totp when a session is live, and
POST /auth/session/replace and /auth/session/cancel (R1 retest item 5).

Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import threading
import uuid
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie

import pytest
from sqlalchemy import text

from platform_common.auth import set_local_verifier
from platform_common.clock import FrozenClock, get_clock
from platform_common.fake_auth import CLIENT_ID, ISSUER

from .auth_env import EMAIL, ORIGIN, auth_env, end_sessions, one, sign_up, verify
from .conftest import PG_ADMIN_URL

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")

PASSWORD = "Correct-Horse-42!"
SECRET = "JBSWY3DPEHPK3PXP"


@pytest.fixture()
def env():
    with auth_env() as e:
        client, idp, mail, admin = e
        assert verify(client, sign_up(client, mail).params["code"]).status_code == 200
        end_sessions(admin)  # sign-up opened one
        set_local_verifier(idp.jwks(), issuer=ISSUER, client_id=CLIENT_ID)
        yield e
        set_local_verifier(None)


def signin(client, email=EMAIL):
    return client.post("/api/v1/auth/signin", json={"email": email, "password": PASSWORD}, headers=ORIGIN)


def totp_in(client, challenge, code, email=EMAIL):
    return client.post(
        "/api/v1/auth/signin/totp", json={"email": email, "challenge": challenge, "code": code}, headers=ORIGIN
    )


def cookie(r):
    return SimpleCookie(r.headers["set-cookie"])["__Secure-rt"].value


def bearer(token):
    return {"authorization": f"Bearer {token}"}


def replace(client, token, headers=ORIGIN):
    return client.post("/api/v1/auth/session/replace", headers={**headers, **bearer(token)})


def cancel(client, token, refresh=None, headers=ORIGIN):
    h = {**headers, **bearer(token)}
    if refresh:
        h["cookie"] = f"__Secure-rt={refresh}"
    return client.post("/api/v1/auth/session/cancel", headers=h)


def refresh(client, value):
    return client.post("/api/v1/auth/refresh", headers={**ORIGIN, "cookie": f"__Secure-rt={value}"})


def live(admin):
    return one(admin, "select count(*) from identity.sessions where revoked_at is null")


def me(client, r):
    return client.get("/api/v1/me", headers=bearer(r.json()["access_token"])).status_code


def two_browsers(client):
    """Browser A is signed in; browser B's sign-in is the one that is asked."""
    a = signin(client)
    assert a.status_code == 200 and "step" not in a.json()
    return a, signin(client)


def test_a_second_sign_in_opens_nothing_and_asks(env):
    client, _, _, admin = env
    a, b = two_browsers(client)
    assert b.status_code == 200, b.text
    assert set(b.json()) == {"step", "access_token", "expires_in"} and b.json()["step"] == "session_active"
    assert "__Secure-rt" in b.headers["set-cookie"]  # the refresh token is kept for the yes
    assert live(admin) == 1  # still only A's
    assert one(admin, "select count(*) from platform.audit_log where action = 'auth.signin'") == 1
    assert me(client, b) == 401  # no session row, so no route accepts B's token
    assert me(client, a) == 200
    assert refresh(client, cookie(b)).status_code == 401  # nor can it be refreshed into one


def test_yes_ends_the_other_session_and_continues_here(env):
    client, _, _, admin = env
    a, b = two_browsers(client)
    r = replace(client, b.json()["access_token"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"] == b.json()["access_token"] and body["user"]["email"] == EMAIL
    assert set(body) == {"access_token", "expires_in", "user", "memberships"} and body["expires_in"] > 0
    assert live(admin) == 1
    assert one(admin, "select count(*) from identity.sessions where revoke_reason = 'replaced'") == 1
    assert one(admin, "select data from platform.audit_log where action = 'auth.session_replaced'") == {"sessions": 1}
    # A is out: its token and its refresh cookie are refused, so A shows the timed-out screen.
    assert me(client, a) == 401
    assert refresh(client, cookie(a)).status_code == 401
    # B is in.
    assert me(client, b) == 200
    assert refresh(client, cookie(b)).status_code == 200


def test_a_repeated_yes_answers_the_same_and_changes_nothing(env):
    client, _, _, admin = env
    _, b = two_browsers(client)
    token = b.json()["access_token"]
    assert replace(client, token).status_code == 200
    assert replace(client, token).status_code == 200
    assert live(admin) == 1
    assert one(admin, "select count(*) from platform.audit_log where action = 'auth.session_replaced'") == 1


def test_no_keeps_the_other_session_and_the_new_sign_in_never_completes(env):
    client, idp, _, admin = env
    a, b = two_browsers(client)
    r = cancel(client, b.json()["access_token"], refresh=cookie(b))
    assert r.status_code == 204 and "Max-Age=0" in r.headers["set-cookie"]
    assert live(admin) == 1
    assert me(client, a) == 200  # A carries on
    assert refresh(client, cookie(a)).status_code == 200
    assert refresh(client, cookie(b)).status_code == 401  # B's provider token was revoked
    assert idp._refresh[cookie(b)].revoked is True and idp._refresh[cookie(a)].revoked is False
    assert one(admin, "select count(*) from platform.audit_log where action = 'auth.signin_declined'") == 1
    # B's access token is still good for a few minutes, but a "no" can't be turned into a "yes" afterwards.
    assert replace(client, b.json()["access_token"]).status_code == 401
    assert live(admin) == 1 and me(client, a) == 200


def test_cancel_with_the_token_of_a_live_session_ends_nothing(env):
    client, _, _, admin = env
    a, _ = two_browsers(client)
    assert cancel(client, a.json()["access_token"]).status_code == 204
    assert live(admin) == 1 and me(client, a) == 200


def test_a_yes_that_comes_too_late_is_refused(env):
    from app import api as app_api

    client, _, _, admin = env
    _, b = two_browsers(client)
    app_api.app.dependency_overrides[get_clock] = lambda: FrozenClock(datetime.now(UTC) + timedelta(minutes=11))
    try:
        r = replace(client, b.json()["access_token"])
    finally:
        app_api.app.dependency_overrides.pop(get_clock, None)
    assert (r.status_code, r.json()["error"]["code"]) == (401, "session_invalid")
    assert "Max-Age=0" in r.headers["set-cookie"]
    assert live(admin) == 1 and one(admin, "select count(*) from identity.sessions where revoke_reason = 'replaced'") == 0


@pytest.mark.parametrize("header", [{}, {"authorization": "Bearer not.a.token"}, {"authorization": "Basic abc"}])
def test_replace_without_a_good_token_changes_nothing(env, header):
    client, _, _, admin = env
    two_browsers(client)
    r = client.post("/api/v1/auth/session/replace", headers={**ORIGIN, **header})
    assert (r.status_code, r.json()["error"]["code"]) == (401, "session_invalid")
    assert live(admin) == 1


def test_replace_and_cancel_check_the_origin(env):
    client, _, _, admin = env
    a, b = two_browsers(client)
    token = b.json()["access_token"]
    assert replace(client, token, headers={}).status_code == 401
    assert replace(client, token, headers={"origin": "https://evil.example"}).status_code == 401
    assert cancel(client, token, refresh=cookie(b), headers={}).status_code == 204  # nothing is done for it
    assert one(admin, "select count(*) from platform.audit_log where action = 'auth.signin_declined'") == 0
    assert live(admin) == 1 and me(client, a) == 200


def test_ones_token_cannot_end_another_users_session(env):
    client, _, mail, admin = env
    ravi = "ravi@example.com"
    done = verify(client, sign_up(client, mail, email=ravi).params["code"], email=ravi)
    assert done.status_code == 200  # Ravi's sign-up session is live
    a = signin(client)
    assert replace(client, a.json()["access_token"]).status_code == 200  # Asha's own token: nothing to end
    assert live(admin) == 2  # one each
    assert me(client, done) == 200


def test_an_idle_session_does_not_count_as_active(env):
    client, _, _, admin = env
    a = signin(client)
    with admin.begin() as c:
        c.execute(text("update identity.sessions set last_activity_at = now() - interval '25 hours' where revoked_at is null"))
    b = signin(client)
    assert "step" not in b.json()  # the idle row is not live as the resolver reads it
    assert me(client, a) == 401 and me(client, b) == 200


def test_an_expired_session_does_not_count_as_active(env):
    client, _, _, admin = env
    signin(client)
    with admin.begin() as c:
        c.execute(text("update identity.sessions set absolute_expires_at = now() - interval '1 minute' where revoked_at is null"))
    assert "step" not in signin(client).json()


def test_a_signed_out_session_does_not_count_as_active(env):
    client, _, _, _ = env
    a = signin(client)
    assert client.post("/api/v1/auth/signout", headers=bearer(a.json()["access_token"])).status_code == 204
    assert "step" not in signin(client).json()


def test_the_two_step_flow_asks_after_the_code(env):
    client, idp, _, admin = env
    signin(client)
    u = idp.user(EMAIL)
    u.totp_secret, u.totp_enabled = SECRET, True
    step = signin(client).json()
    assert step["step"] == "totp"
    r = totp_in(client, step["challenge"], idp.totp_code(SECRET))
    assert r.status_code == 200 and r.json()["step"] == "session_active"
    assert live(admin) == 1
    done = replace(client, r.json()["access_token"])
    assert done.status_code == 200
    assert one(admin, "select count(*) from identity.sessions where revoke_reason = 'replaced'") == 1


def test_a_support_user_has_one_active_session_too(env):
    client, _, mail, admin = env
    sam = "sam@example.com"
    assert verify(client, sign_up(client, mail, email=sam).params["code"], email=sam).status_code == 200
    with admin.begin() as c:
        c.execute(text("update identity.users set is_support = true where email = :e"), {"e": sam})
    end_sessions(admin)
    a = signin(client, sam)
    assert a.json()["user"]["is_support"] is True
    b = signin(client, sam)
    assert b.json()["step"] == "session_active"
    done = replace(client, b.json()["access_token"])
    assert done.status_code == 200 and done.json()["user"]["is_support"] is True
    assert me(client, a) == 401


def test_sign_up_is_not_asked_anything(env):
    client, _, mail, _ = env
    r = verify(client, sign_up(client, mail, email="new@example.com").params["code"], email="new@example.com")
    assert r.status_code == 200 and "step" not in r.json()


def test_two_sign_ins_at_once_open_exactly_one_session(env):
    _, _, _, admin = env
    uid = one(admin, "select id from identity.users where email = :e", e=EMAIL)
    barrier, results = threading.Barrier(4), []

    def attempt():
        with admin.connect() as c:
            barrier.wait()
            with c.begin():
                results.append(
                    c.execute(
                        text("select identity.auth_open_session_once(:i, :u, 'sid', :k, now(), 30)"),
                        {"i": uuid.uuid4(), "u": uid, "k": uuid.uuid4().hex},
                    ).scalar()
                )

    threads = [threading.Thread(target=attempt) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == [False, False, False, True]
    assert live(admin) == 1


def test_two_yeses_at_once_leave_one_live_session(env):
    client, _, _, admin = env
    signin(client)
    token = signin(client).json()["access_token"]
    barrier, codes = threading.Barrier(2), []

    def attempt():
        barrier.wait()
        codes.append(replace(client, token).status_code)

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert codes == [200, 200] and live(admin) == 1


def set_idle(admin, minutes):
    with admin.begin() as c:
        c.execute(
            text(f"update identity.sessions set last_activity_at = now() - interval '{minutes} minutes' where revoked_at is null")
        )


def test_a_session_used_within_the_window_still_asks(env):
    client, _, _, admin = env
    a = signin(client)
    set_idle(admin, 25)
    assert signin(client).json()["step"] == "session_active"
    assert me(client, a) == 200


def test_a_session_idle_past_the_window_is_ended_and_does_not_ask(env):
    """The owner's stale session (seed, closed browser) must not block their own sign-in, and must not
    stay usable behind the new one."""
    client, _, _, admin = env
    a = signin(client)
    set_idle(admin, 40)  # still inside the 24 h idle rule, but past the 30 min window
    b = signin(client)
    assert "step" not in b.json()
    assert me(client, a) == 401 and me(client, b) == 200
    assert live(admin) == 1
    assert one(admin, "select count(*) from identity.sessions where revoke_reason = 'replaced'") == 1

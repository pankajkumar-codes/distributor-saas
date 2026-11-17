"""TOTP enrolment: POST /me/totp/setup, /me/totp/confirm and DELETE /me/totp on
PostgreSQL, as app_rw (LLD-1 §5.9, AC-14).

Skipped unless PG_ADMIN_URL points at a disposable server.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from platform_common.auth import set_local_verifier
from platform_common.clock import FrozenClock, get_clock
from platform_common.fake_auth import CLIENT_ID, ISSUER

from .auth_env import EMAIL, ORIGIN, PASSWORD, auth_env, last, one, sign_up, verify
from .conftest import PG_ADMIN_URL

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


@pytest.fixture()
def env():
    with auth_env() as e:
        client, idp, mail, _ = e
        assert verify(client, sign_up(client, mail).params["code"]).status_code == 200
        set_local_verifier(idp.jwks(), issuer=ISSUER, client_id=CLIENT_ID)
        yield e
        set_local_verifier(None)


def signin(client):
    return client.post("/api/v1/auth/signin", json={"email": EMAIL, "password": PASSWORD}, headers=ORIGIN)


def bearer(client):
    return {"authorization": f"Bearer {signin(client).json()['access_token']}"}


def enrol(client, idp, me):
    secret = client.post("/api/v1/me/totp/setup", headers=me).json()["secret"]
    r = client.post("/api/v1/me/totp/confirm", json={"code": idp.totp_code(secret)}, headers=me)
    assert r.status_code == 204, r.text
    return secret


def audit_actions(admin):
    with admin.connect() as c:
        return (
            c.execute(text("select action from platform.audit_log where action like 'auth.totp%' order by at, id"))
            .scalars()
            .all()
        )


def test_setup_then_confirm_turns_totp_on(env):  # AC-14
    client, idp, mail, admin = env
    me = bearer(client)
    r = client.post("/api/v1/me/totp/setup", headers=me)
    assert r.status_code == 200 and set(r.json()) == {"secret"}
    assert client.get("/api/v1/me", headers=me).json()["user"]["totp_enabled"] is False  # not until confirmed
    secret = r.json()["secret"]
    r = client.post("/api/v1/me/totp/confirm", json={"code": idp.totp_code(secret)}, headers=me)
    assert r.status_code == 204, r.text
    assert client.get("/api/v1/me", headers=me).json()["user"]["totp_enabled"] is True
    assert (last(mail).template, last(mail).to) == ("totp_on", EMAIL)
    assert audit_actions(admin) == ["auth.totp_on"]
    assert signin(client).json()["step"] == "totp"  # the provider now asks for a code


def test_setup_and_confirm_are_refused_while_totp_is_on(env):  # Staff 2, #60
    client, idp, _, admin = env
    me = bearer(client)
    secret = enrol(client, idp, me)
    r = client.post("/api/v1/me/totp/setup", headers=me)
    assert (r.status_code, r.json()["error"]["code"]) == (409, "totp_already_on")
    r = client.post("/api/v1/me/totp/confirm", json={"code": idp.totp_code(secret)}, headers=me)
    assert (r.status_code, r.json()["error"]["code"]) == (409, "totp_already_on")
    assert idp.user(EMAIL).totp_secret == secret and audit_actions(admin) == ["auth.totp_on"]  # the factor is unchanged
    assert client.delete("/api/v1/me/totp", headers=me).status_code == 204  # off (with the step-up), then again
    enrol(client, idp, me)


def test_a_wrong_code_turns_nothing_on(env):
    client, idp, mail, admin = env
    me = bearer(client)
    secret = client.post("/api/v1/me/totp/setup", headers=me).json()["secret"]
    sent = len(mail.sent)  # setup prints the demo's code; a wrong confirm sends nothing more
    wrong = "000000" if idp.totp_code(secret) != "000000" else "111111"
    r = client.post("/api/v1/me/totp/confirm", json={"code": wrong}, headers=me)
    assert (r.status_code, r.json()["error"]["code"]) == (422, "totp_not_accepted")
    assert one(admin, "select count(*) from identity.users where totp_enabled_at is not null") == 0
    assert len(mail.sent) == sent and audit_actions(admin) == []
    assert "access_token" in signin(client).json()


def test_removing_totp_within_the_step_up_window(env):
    client, idp, mail, admin = env
    me = bearer(client)
    enrol(client, idp, me)
    r = client.delete("/api/v1/me/totp", headers=me)
    assert r.status_code == 204, r.text
    assert client.get("/api/v1/me", headers=me).json()["user"]["totp_enabled"] is False
    assert (last(mail).template, audit_actions(admin)) == ("totp_off", ["auth.totp_on", "auth.totp_off"])
    assert "access_token" in signin(client).json()  # no code asked any more


def test_removing_totp_after_the_window_needs_a_fresh_sign_in(env):
    from app import api as app_api

    client, idp, _, admin = env
    me = bearer(client)
    enrol(client, idp, me)
    later = FrozenClock(datetime.now(UTC) + timedelta(minutes=11))  # auth.stepup_minutes is 10
    app_api.app.dependency_overrides[get_clock] = lambda: later
    r = client.delete("/api/v1/me/totp", headers=me)
    assert (r.status_code, r.json()["error"]["code"]) == (409, "reauth_required")
    assert idp.user(EMAIL).totp_enabled and audit_actions(admin) == ["auth.totp_on"]
    debug = client.delete("/api/v1/me/totp", headers={"x-debug-user": idp.user(EMAIL).sub})  # no auth_time
    assert debug.status_code in (401, 409)


def test_totp_routes_need_a_signed_in_caller(env):
    client, _, _, _ = env
    assert client.post("/api/v1/me/totp/setup").status_code == 401
    assert client.post("/api/v1/me/totp/confirm", json={"code": "123456"}).status_code == 401
    assert client.delete("/api/v1/me/totp").status_code == 401


def test_set_my_totp_acts_only_for_the_bound_caller(env):
    from platform_common.uow import Principal, unit_of_work

    _, idp, _, admin = env
    with unit_of_work(Principal(user_sub=None, request_id="t")) as uow:  # nobody bound
        assert uow.tx.execute(text("select identity.auth_set_my_totp(true)")).scalar() is False
    with unit_of_work(Principal(user_sub=idp.user(EMAIL).sub, request_id="t")) as uow:  # a sub alone isn't enough
        assert uow.tx.execute(text("select identity.auth_set_my_totp(true)")).scalar() is False
    assert one(admin, "select count(*) from identity.users where totp_enabled_at is not null") == 0


def test_removing_totp_when_it_is_off_changes_nothing(env):  # EM, #60
    client, idp, mail, admin = env
    me, sent = bearer(client), len(mail.sent)
    r = client.delete("/api/v1/me/totp", headers=me)
    assert (r.status_code, r.json()["error"]["code"]) == (409, "totp_already_off")
    assert len(mail.sent) == sent and audit_actions(admin) == []


@pytest.mark.parametrize("route", ["setup", "confirm", "remove"])
def test_a_token_the_provider_no_longer_accepts_is_401(env, monkeypatch, route):  # Staff 2, #65
    from platform_common.authprovider import AuthRefused

    client, idp, _, _ = env
    me = bearer(client)
    if route == "remove":
        enrol(client, idp, me)

    def refuse(*_):
        raise AuthRefused("token_invalid")

    monkeypatch.setattr(
        idp, {"setup": "associate_totp", "confirm": "verify_totp", "remove": "remove_totp"}[route], refuse
    )
    r = {
        "setup": lambda: client.post("/api/v1/me/totp/setup", headers=me),
        "confirm": lambda: client.post("/api/v1/me/totp/confirm", json={"code": "123456"}, headers=me),
        "remove": lambda: client.delete("/api/v1/me/totp", headers=me),
    }[route]()
    assert (r.status_code, r.json()["error"]["code"]) == (401, "session_invalid")


def demo_codes(mail):
    return [p["code"] for t, to, p in mail.sent if t == "demo_totp_code" and to == EMAIL]


def test_the_local_demo_prints_the_code_to_turn_two_step_on_and_to_sign_in(env):
    # An authenticator app cannot show the fake provider's code, so the demo prints it with the other codes.
    client, idp, mail, _ = env
    me = bearer(client)
    secret = client.post("/api/v1/me/totp/setup", headers=me).json()["secret"]
    assert demo_codes(mail) == [idp.totp_code(secret)]
    assert client.post("/api/v1/me/totp/confirm", json={"code": demo_codes(mail)[-1]}, headers=me).status_code == 204
    assert signin(client).json()["step"] == "totp"  # the sign-in step prints it again
    assert demo_codes(mail) == [idp.totp_code(secret)] * 2


def test_the_demo_code_is_never_sent_when_the_environment_is_not_a_debug_one(env, monkeypatch):
    from app.modules.identity import demo_hint

    client, idp, mail, _ = env
    monkeypatch.setattr(demo_hint, "debug_env", lambda: False)
    client.post("/api/v1/me/totp/setup", headers=bearer(client))
    assert demo_codes(mail) == []


def test_a_provider_without_the_demo_helper_prints_nothing(env):
    from app.modules.identity import demo_hint

    class Real:  # stands in for the Cognito provider
        pass

    _, _, mail, _ = env
    demo_hint.print_two_step_code(Real(), mail, email=EMAIL)
    assert demo_codes(mail) == []

"""POST /auth/signup and /auth/signup/verify on PostgreSQL, as app_rw (LLD-1 §5.1-5.2).

The database is built by migrator.local, exactly as `make run-api` builds it, so the
platform audit log and the identity auth functions are both there. The auth provider
and mailer are the fakes: nothing real is called or sent.

Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import jwt
import pytest
from sqlalchemy import text

from platform_common.authprovider import AuthRefused

from .auth_env import EMAIL, auth_env, last, one, sign_up, verify
from .conftest import PG_ADMIN_URL

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


@pytest.fixture()
def env():
    with auth_env() as e:
        yield e


def test_sign_up_and_verify_creates_the_user_session_and_audit_row(env):
    client, idp, mail, admin = env
    msg = sign_up(client, mail, email="  Asha@Example.com ")
    assert (msg.template, msg.to) == ("signup_code", EMAIL)
    r = verify(client, msg.params["code"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["email"] == EMAIL and body["expires_in"] == 300 and body["access_token"]
    cookie = r.headers["set-cookie"]
    for part in ("__Secure-rt=", "HttpOnly", "Secure", "SameSite=strict", "Path=/api/v1/auth", "Max-Age=2592000"):
        assert part in cookie
    user_id = body["user"]["id"]
    assert one(admin, "select cognito_sub from identity.users where id = :u", u=user_id) == idp.get_sub(EMAIL)
    assert (
        one(admin, "select count(*) from identity.sessions where user_id = :u and revoked_at is null", u=user_id) == 1
    )
    assert one(admin, "select action from platform.audit_log where user_id = :u", u=user_id) == "auth.signup"
    assert one(admin, "select count(*) from identity.pending_signups") == 0
    assert verify(client, msg.params["code"]).json()["error"]["code"] == "code_not_accepted"  # used once


def test_sign_up_reply_is_identical_for_a_registered_email(env):  # AC-2
    client, _, mail, _ = env
    verify(client, sign_up(client, mail).params["code"])
    new = client.post("/api/v1/auth/signup", json={"email": "ravi@example.com"})
    old = client.post("/api/v1/auth/signup", json={"email": EMAIL})
    assert (new.status_code, new.content) == (old.status_code, old.content)
    assert (last(mail).template, last(mail).params) == ("already_registered", {})


def test_weak_password_spends_no_try_and_wrong_code_does(env):  # AC-3
    client, _, mail, admin = env
    code = sign_up(client, mail).params["code"]
    r = verify(client, code, password="short")
    assert (r.status_code, r.json()["error"]["code"]) == (422, "password_weak")
    assert one(admin, "select tries from identity.verification_codes") == 0
    wrong = "000000" if code != "000000" else "111111"
    r = verify(client, wrong)
    assert (r.status_code, r.json()) == (
        400,
        {"error": {"code": "code_not_accepted", "message": r.json()["error"]["message"]}},
    )
    assert one(admin, "select tries from identity.verification_codes") == 1


def test_a_provider_failure_after_the_claim_can_be_retried(env, monkeypatch):  # AC-3, HLD §6.1
    client, idp, mail, admin = env
    code = sign_up(client, mail).params["code"]
    real = idp.initiate_auth
    monkeypatch.setattr(idp, "initiate_auth", lambda *a: (_ for _ in ()).throw(AuthRefused("not_authorized")))
    assert verify(client, code).status_code == 500  # the Cognito user exists, no users row yet
    assert one(admin, "select tries from identity.verification_codes") == 1
    assert one(admin, "select count(*) from identity.users") == 0
    monkeypatch.setattr(idp, "initiate_auth", real)
    assert verify(client, code).json()["error"]["code"] == "code_not_accepted"  # claim still held
    with admin.begin() as c:
        c.execute(text("update identity.verification_codes set claimed_at = now() - interval '61 seconds'"))
    r = verify(client, code)  # create_user says user_exists, so the recovery path runs
    assert r.status_code == 200, r.text
    assert one(admin, "select count(*) from identity.users") == 1


def test_verify_needs_the_app_origin(env):  # §5.6: the route sets the refresh cookie
    client, _, mail, _ = env
    code = sign_up(client, mail).params["code"]
    assert verify(client, code, headers={}).status_code == 401
    assert verify(client, code, headers={"origin": "https://evil.example"}).status_code == 401
    assert verify(client, code).status_code == 200  # no try was spent


def test_sixth_code_request_per_email_in_an_hour_is_429(env):  # AC-1
    client, _, mail, _ = env
    for _ in range(5):
        sign_up(client, mail)
    r = client.post("/api/v1/auth/signup", json={"email": EMAIL.upper()})
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1


@pytest.mark.parametrize("email", ["no-at-sign", "a@b", "two@@example.com", "sp ace@example.com"])
def test_malformed_email_is_422(env, email):
    client, _, _, _ = env
    r = client.post("/api/v1/auth/signup", json={"email": email})
    assert (r.status_code, r.json()["error"]["code"]) == (422, "email_invalid")


def test_session_key_falls_back_to_event_id_like_the_resolver(env, monkeypatch):  # L1-6
    client, idp, mail, admin = env
    code = sign_up(client, mail).params["code"]
    real = idp._access

    def without_origin_jti(sub, origin_jti, auth_time):
        claims = jwt.decode(real(sub, origin_jti, auth_time), options={"verify_signature": False})
        claims["event_id"] = claims.pop("origin_jti")
        return jwt.encode(claims, idp._key, algorithm="RS256", headers={"kid": idp.jwks()["keys"][0]["kid"]})

    monkeypatch.setattr(idp, "_access", without_origin_jti)
    r = verify(client, code)
    assert r.status_code == 200, r.text
    assert one(admin, "select key_kind from identity.sessions") == "event_id"

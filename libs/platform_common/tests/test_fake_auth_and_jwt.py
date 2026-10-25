"""FakeAuthProvider behaves like the LLD-1 §7.1 Cognito client, and verify_access_token
accepts only our access tokens (LLD-1 §7.3)."""

import time
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from platform_common.authprovider import AuthRefused
from platform_common.clock import FrozenClock
from platform_common.fake_auth import CLIENT_ID, ISSUER, FakeAuthProvider
from platform_common.jwt_verify import TokenInvalid, verify_access_token


@pytest.fixture(autouse=True)
def test_env(monkeypatch):
    monkeypatch.setenv("PLATFORM_ENV", "test")


@pytest.fixture()
def idp():
    clock = FrozenClock(datetime.now(UTC))
    p = FakeAuthProvider(clock)
    p.clock = clock
    p.create_user("Asha@Example.com ", "correct horse battery")
    return p


def verify(idp, token, **kw):
    return verify_access_token(token, idp.jwks(), issuer=ISSUER, client_id=CLIENT_ID, **kw)


def test_sign_in_gives_verifiable_tokens_and_the_session_key_survives_refresh(idp):
    r = idp.initiate_auth("asha@example.com", "correct horse battery")
    assert not r.needs_totp and r.refresh_token and r.expires_in == 300
    first = verify(idp, r.access_token)
    again = verify(idp, idp.refresh(r.refresh_token).access_token)
    assert first["sub"] == again["sub"] == idp.get_sub("ASHA@example.com")
    assert first["origin_jti"] == again["origin_jti"] and first["jti"] != again["jti"]
    second_device = verify(idp, idp.initiate_auth("asha@example.com", "correct horse battery").access_token)
    assert second_device["origin_jti"] != first["origin_jti"]


@pytest.mark.parametrize("email, password", [("asha@example.com", "wrong"), ("nobody@example.com", "x")])
def test_wrong_password_and_unknown_user_look_the_same(idp, email, password):
    with pytest.raises(AuthRefused) as e:
        idp.initiate_auth(email, password)
    assert e.value.code == "not_authorized"


def test_create_user_twice_is_user_exists(idp):
    with pytest.raises(AuthRefused, match="user_exists"):
        idp.create_user("asha@example.com", "another password")


def test_revoke_and_global_sign_out_stop_refresh(idp):
    a = idp.initiate_auth("asha@example.com", "correct horse battery").refresh_token
    b = idp.initiate_auth("asha@example.com", "correct horse battery").refresh_token
    idp.revoke_refresh(a)
    with pytest.raises(AuthRefused):
        idp.refresh(a)
    idp.refresh(b)
    idp.global_sign_out(idp.get_sub("asha@example.com"))
    with pytest.raises(AuthRefused):
        idp.refresh(b)


def test_totp_enrolment_then_challenge(idp):
    access = idp.initiate_auth("asha@example.com", "correct horse battery").access_token
    secret = idp.associate_totp(access)
    assert not idp.verify_totp(access, "000000" if idp.totp_code(secret) != "000000" else "111111")
    assert idp.verify_totp(access, idp.totp_code(secret))

    step = idp.initiate_auth("asha@example.com", "correct horse battery")
    assert step.needs_totp and step.access_token is None
    with pytest.raises(AuthRefused) as e:
        idp.respond_totp(step.challenge, "not-it")
    assert e.value.code == "totp_not_accepted" and e.value.challenge == step.challenge
    assert verify(idp, idp.respond_totp(step.challenge, idp.totp_code(secret)).access_token)
    with pytest.raises(AuthRefused, match="challenge_expired"):
        idp.respond_totp(step.challenge, idp.totp_code(secret))  # single use

    late = idp.initiate_auth("asha@example.com", "correct horse battery")
    idp.clock.advance(timedelta(minutes=3))
    with pytest.raises(AuthRefused, match="challenge_expired"):
        idp.respond_totp(late.challenge, idp.totp_code(secret))

    idp.remove_totp(idp.get_sub("asha@example.com"))
    assert not idp.initiate_auth("asha@example.com", "correct horse battery").needs_totp


def test_change_and_set_password(idp):
    access = idp.initiate_auth("asha@example.com", "correct horse battery").access_token
    with pytest.raises(AuthRefused, match="not_authorized"):
        idp.change_password(access, "wrong", "new password here")
    idp.change_password(access, "correct horse battery", "new password here")
    idp.initiate_auth("asha@example.com", "new password here")
    idp.set_password(idp.get_sub("asha@example.com"), "third password!")
    idp.initiate_auth("asha@example.com", "third password!")


@pytest.mark.parametrize("env", ["staging", "prod", ""])
def test_fake_refuses_outside_local_and_test(monkeypatch, env):
    monkeypatch.setenv("PLATFORM_ENV", env)
    with pytest.raises(RuntimeError):
        FakeAuthProvider()


def _forge(idp, **override):
    """A token signed by the fake's own key, with some claims changed."""
    claims = verify(idp, idp.initiate_auth("asha@example.com", "correct horse battery").access_token)
    claims.update(override)
    kid = idp.jwks()["keys"][0]["kid"]
    return jwt.encode(claims, idp._key, algorithm="RS256", headers={"kid": kid})


@pytest.mark.parametrize(
    "override",
    [{"token_use": "id"}, {"client_id": "other-client"}, {"iss": "https://evil.example"}],
)
def test_verify_refuses_other_tokens(idp, override):
    with pytest.raises(TokenInvalid):
        verify(idp, _forge(idp, **override))


def test_verify_allows_clock_skew_within_leeway(idp):
    assert verify(idp, _forge(idp, exp=int(time.time()) - 10))["sub"]
    assert verify(idp, _forge(idp, iat=int(time.time()) + 10))["sub"]


def test_verify_refuses_expired_unless_allowed(idp):
    old = _forge(idp, exp=int(time.time()) - 60)
    with pytest.raises(TokenInvalid):
        verify(idp, old)
    assert verify(idp, old, allow_expired=True)["sub"]


def test_verify_refuses_another_key_unsigned_and_garbage(idp):
    token = idp.initiate_auth("asha@example.com", "correct horse battery").access_token
    other = FakeAuthProvider()
    with pytest.raises(TokenInvalid):  # unknown kid
        verify_access_token(token, other.jwks(), issuer=ISSUER, client_id=CLIENT_ID)
    same_kid = {"keys": [{**other.jwks()["keys"][0], "kid": idp.jwks()["keys"][0]["kid"]}]}
    with pytest.raises(TokenInvalid):  # right kid, wrong key
        verify_access_token(token, same_kid, issuer=ISSUER, client_id=CLIENT_ID)
    claims = jwt.decode(token, options={"verify_signature": False})
    unsigned = jwt.encode(claims, key=None, algorithm="none", headers={"kid": idp.jwks()["keys"][0]["kid"]})
    for bad in (unsigned, "not.a.token", ""):
        with pytest.raises(TokenInvalid):
            verify(idp, bad)

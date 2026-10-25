"""Who-is-calling must fail closed: no verified claims and no debug environment means 401."""

import pytest
from starlette.requests import Request

from platform_common.auth import current_caller, set_local_verifier
from platform_common.errors import Deny
from platform_common.fake_auth import CLIENT_ID, ISSUER, FakeAuthProvider


def request(headers=None, event=None):
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
    }
    if event is not None:
        scope["aws.event"] = event
    return Request(scope)


def claims(sub, email=None):
    c = {"sub": sub}
    if email:
        c["email"] = email
    return {"requestContext": {"authorizer": {"jwt": {"claims": c}}}}


@pytest.mark.parametrize("env", ["local", "test", "staging", "prod"])
def test_verified_claims_win_in_every_env(monkeypatch, env):
    monkeypatch.setenv("PLATFORM_ENV", env)
    p = current_caller(request({"x-debug-user": "mallory"}, claims("real-sub", "a@example.com")))
    assert (p.user_sub, p.email) == ("real-sub", "a@example.com")


@pytest.mark.parametrize("env", ["local", "test"])
def test_debug_header_works_only_in_local_and_test(monkeypatch, env):
    monkeypatch.setenv("PLATFORM_ENV", env)
    assert current_caller(request({"x-debug-user": "alice"})).user_sub == "alice"


@pytest.mark.parametrize("env", ["staging", "prod", "Prod", "LOCAL", "dev", ""])
def test_debug_header_is_ignored_elsewhere(monkeypatch, env):
    monkeypatch.setenv("PLATFORM_ENV", env)
    with pytest.raises(Deny) as e:
        current_caller(request({"x-debug-user": "alice"}))
    assert e.value.reason == "session_invalid"


@pytest.mark.parametrize(
    "event",
    [
        {},
        {"requestContext": {}},
        {"requestContext": {"authorizer": {}}},
        {"requestContext": {"authorizer": {"jwt": {"claims": {}}}}},
        {"requestContext": {"authorizer": {"jwt": {"claims": {"sub": ""}}}}},
    ],
)
def test_missing_or_empty_claims_are_401(monkeypatch, event):
    monkeypatch.setenv("PLATFORM_ENV", "prod")
    with pytest.raises(Deny) as e:
        current_caller(request(event=event))
    assert e.value.reason == "session_invalid"


def test_empty_debug_header_is_401(monkeypatch):
    monkeypatch.setenv("PLATFORM_ENV", "test")
    with pytest.raises(Deny):
        current_caller(request({"x-debug-user": ""}))


@pytest.mark.xfail(
    strict=True,
    reason="QA-DEF-004: PLATFORM_ENV defaults to 'local', so a Lambda deployed without it "
    "would accept X-Debug-User. Terraform sets it today; the code should still fail closed.",
)
def test_unset_platform_env_fails_closed(monkeypatch):
    monkeypatch.delenv("PLATFORM_ENV", raising=False)
    with pytest.raises(Deny):
        current_caller(request({"x-debug-user": "alice"}))


# --- Local bearer tokens (LLD-0 §3.11): verified against FakeAuthProvider's keys -----

@pytest.fixture()
def fake_idp(monkeypatch):
    monkeypatch.setenv("PLATFORM_ENV", "test")
    idp = FakeAuthProvider()
    sub = idp.create_user("asha@example.com", "correct horse battery")
    token = idp.initiate_auth("asha@example.com", "correct horse battery").access_token
    set_local_verifier(idp.jwks(), issuer=ISSUER, client_id=CLIENT_ID)
    yield idp, sub, token
    set_local_verifier(None)


def test_local_bearer_token_gives_the_claims(fake_idp):
    _, sub, token = fake_idp
    caller = current_caller(request({"authorization": f"Bearer {token}"}))
    assert caller.user_sub == sub and caller.claims["origin_jti"]


def test_bad_local_bearer_token_is_401_even_with_a_debug_header(fake_idp):
    with pytest.raises(Deny) as e:
        current_caller(request({"authorization": "Bearer not.a.token", "x-debug-user": "alice"}))
    assert e.value.reason == "session_invalid"


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_local_bearer_token_is_ignored_outside_local_and_test(fake_idp, monkeypatch, env):
    _, _, token = fake_idp
    monkeypatch.setenv("PLATFORM_ENV", env)
    with pytest.raises(Deny) as e:
        current_caller(request({"authorization": f"Bearer {token}"}))
    assert e.value.reason == "session_invalid"


def test_bearer_without_a_local_verifier_falls_back_to_the_debug_header(monkeypatch):
    monkeypatch.setenv("PLATFORM_ENV", "test")
    set_local_verifier(None)
    assert current_caller(request({"authorization": "Bearer x", "x-debug-user": "alice"})).user_sub == "alice"

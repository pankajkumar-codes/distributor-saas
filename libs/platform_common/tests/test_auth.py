"""Who-is-calling must fail closed: no verified claims and no debug environment means 401."""

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from platform_common.auth import current_caller


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
    with pytest.raises(HTTPException) as e:
        current_caller(request({"x-debug-user": "alice"}))
    assert e.value.status_code == 401


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
    with pytest.raises(HTTPException) as e:
        current_caller(request(event=event))
    assert e.value.status_code == 401


def test_empty_debug_header_is_401(monkeypatch):
    monkeypatch.setenv("PLATFORM_ENV", "test")
    with pytest.raises(HTTPException):
        current_caller(request({"x-debug-user": ""}))


@pytest.mark.xfail(
    strict=True,
    reason="QA-DEF-004: PLATFORM_ENV defaults to 'local', so a Lambda deployed without it "
    "would accept X-Debug-User. Terraform sets it today; the code should still fail closed.",
)
def test_unset_platform_env_fails_closed(monkeypatch):
    monkeypatch.delenv("PLATFORM_ENV", raising=False)
    with pytest.raises(HTTPException):
        current_caller(request({"x-debug-user": "alice"}))

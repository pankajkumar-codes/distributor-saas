"""The cookie routes' Origin check (AC-16): one exact origin outside debug; both local dev addresses in debug.
No database."""

import pytest
from starlette.requests import Request

from app.modules.identity import api_auth
from platform_common.errors import Deny

LOCALHOST = "http://localhost:5173"
LOOPBACK = "http://127.0.0.1:5173"


def request(origin=None):
    headers = [(b"origin", origin.encode())] if origin else []
    return Request({"type": "http", "headers": headers, "method": "POST", "path": "/"})


def accepted(origin) -> bool:
    try:
        api_auth._check_origin(request(origin))
    except Deny:
        return False
    return True


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.delenv("APP_ORIGIN", raising=False)


def test_debug_accepts_both_local_addresses_and_refuses_others(monkeypatch):
    monkeypatch.setattr(api_auth, "debug_env", lambda: True)
    assert accepted(LOCALHOST) and accepted(LOOPBACK)
    for other in (None, "https://evil.example", "http://127.0.0.1:5174", "http://localhost:5173.evil.example",
                  "http://192.168.1.5:5173"):
        assert not accepted(other), other


def test_outside_debug_only_the_configured_origin_passes(monkeypatch):
    monkeypatch.setattr(api_auth, "debug_env", lambda: False)
    assert not accepted(LOCALHOST) and not accepted(LOOPBACK)  # nothing configured: nothing accepted
    monkeypatch.setenv("APP_ORIGIN", "https://app.example")
    assert accepted("https://app.example") and not accepted(LOCALHOST) and not accepted(LOOPBACK)


def test_debug_with_an_app_origin_set_stays_that_one_exact_origin(monkeypatch):
    monkeypatch.setattr(api_auth, "debug_env", lambda: True)
    monkeypatch.setenv("APP_ORIGIN", "https://app.example")
    assert accepted("https://app.example") and not accepted(LOOPBACK) and not accepted(LOCALHOST)

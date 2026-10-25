"""One response shape for refusals and errors (LLD-0 §3.2)."""

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from platform_common.errors import Conflict, Deny, Invalid, RateLimited, install_error_handlers

app = FastAPI()
install_error_handlers(app)


@app.get("/deny/{reason}")
def deny(reason: str):
    raise Deny(reason)


@app.get("/conflict")
def conflict():
    raise Conflict("period_locked", "the period is locked", fix="unlock it first")


@app.get("/invalid")
def invalid():
    raise Invalid("reason_required", "a reason is required", field="reason")


@app.get("/limited")
def limited():
    raise RateLimited(retry_after=30)


@app.get("/boom")
def boom():
    raise RuntimeError("secret detail 123456")


client = TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("reason", ["not_member", "role_denied", "not_found", "support_no_grant"])
def test_every_deny_is_the_same_404(reason, caplog):
    caplog.set_level(logging.INFO, "platform_common.errors")
    r = client.get(f"/deny/{reason}", headers={"x-request-id": "req-1"})
    assert r.status_code == 404
    assert r.json() == {"error": {"code": "not_found", "message": "not found"}}
    assert reason == "not_found" or reason not in r.text
    record = caplog.records[-1]
    assert (record.event, record.reason, record.request_id, record.route) == ("deny", reason, "req-1", "/deny/{reason}")


def test_session_invalid_is_401_and_says_nothing_about_the_business():
    r = client.get("/deny/session_invalid")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "session_invalid"


def test_unknown_deny_reason_is_a_programming_error():
    with pytest.raises(ValueError):
        Deny("because")


def test_app_errors_carry_code_message_field_and_fix():
    assert client.get("/conflict").json() == {
        "error": {"code": "period_locked", "message": "the period is locked", "fix": "unlock it first"}
    }
    r = client.get("/invalid")
    assert r.status_code == 422 and r.json()["error"]["field"] == "reason"
    r = client.get("/limited")
    assert r.status_code == 429 and r.headers["retry-after"] == "30"


def test_unhandled_error_hides_the_exception_text(caplog):
    caplog.set_level(logging.ERROR, "platform_common.errors")
    r = client.get("/boom")
    assert r.status_code == 500
    assert r.json() == {"error": {"code": "internal", "message": "something went wrong"}}
    assert "secret" not in r.text
    assert caplog.records[-1].levelno == logging.ERROR

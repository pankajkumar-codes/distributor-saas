"""The mailer Lambda (HLD §4, §7): renders, sends through SES, and logs no address,
code or exception text (RM2-28). SES is a stand-in here; nothing is sent."""

import json
import logging

import pytest

from app import mailer


class FakeSes:
    def __init__(self, fail_for=()):
        self.sent, self.fail_for = [], set(fail_for)

    def send(self, to, subject, body):
        if to in self.fail_for:
            raise RuntimeError(f"Email address is not verified: {to}")
        self.sent.append((to, subject, body))
        return f"ses-{len(self.sent)}"


def record(message_id, template, to, params):
    return {"messageId": message_id, "body": json.dumps({"template": template, "to": to, "params": params})}


@pytest.fixture()
def ses(monkeypatch):
    fake = FakeSes(fail_for={"bounce@example.com"})
    monkeypatch.setattr(mailer, "_sender", lambda: fake)
    return fake


def test_messages_are_sent_and_failures_come_back_alone(ses, caplog):
    caplog.set_level(logging.INFO)
    event = {"Records": [
        record("m1", "signup_code", "a@example.com", {"code": "042424"}),
        record("m2", "signup_code", "bounce@example.com", {"code": "135791"}),
        record("m3", "no_such_template", "c@example.com", {}),
        {"messageId": "m4", "body": "not json"},
    ]}
    assert mailer.handler(event, None) == {"batchItemFailures": [{"itemIdentifier": m} for m in ("m2", "m3", "m4")]}
    assert [(to, subject) for to, subject, _ in ses.sent] == [("a@example.com", "Your sign-up code")]
    assert "042424" in ses.sent[0][2]
    logged = caplog.text
    for secret in ("042424", "135791", "a@example.com", "bounce@example.com", "not verified"):
        assert secret not in logged
    assert "signup_code" in logged and "RuntimeError" in logged


def test_without_a_mail_domain_every_message_goes_back(monkeypatch):
    monkeypatch.delenv("MAIL_FROM_DOMAIN", raising=False)
    mailer._sender.cache_clear()
    event = {"Records": [record("m1", "password_changed", "a@example.com", {})]}
    assert mailer.handler(event, None) == {"batchItemFailures": [{"itemIdentifier": "m1"}]}

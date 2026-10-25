"""Mail goes out only after commit, and nothing here can send real mail (LLD-0 §3.11)."""

import json

import pytest

from platform_common.mailer import FakeMailer, LocalFileMailer, send_after_commit


class StubUoW:
    def __init__(self):
        self.callbacks = []

    def after_commit(self, fn):
        self.callbacks.append(fn)

    def commit(self):
        for fn in self.callbacks:
            fn()


def test_send_after_commit_sends_only_on_commit():
    mailer, uow = FakeMailer(), StubUoW()
    send_after_commit(uow, mailer, "signup_code", "a@example.com", {"code": "123456"})
    assert mailer.sent == []  # a rollback would drop the callbacks
    uow.commit()
    assert mailer.last("signup_code", "a@example.com") == {"code": "123456"}


@pytest.mark.parametrize(
    "template, to, params",
    [("no_such_template", "a@example.com", {}), ("signup_code", "not-an-address", {}), ("reset_code", "a@b.c", {"n": 1})],
)
def test_bad_messages_fail_before_commit(template, to, params):
    with pytest.raises(ValueError):
        send_after_commit(StubUoW(), FakeMailer(), template, to, params)


def test_local_file_mailer_writes_json_lines(monkeypatch, tmp_path):
    monkeypatch.setenv("PLATFORM_ENV", "local")
    path = tmp_path / "mail" / "outbox.jsonl"
    m = LocalFileMailer(path)
    m.send("signup_code", "a@example.com", {"code": "042424"})
    m.send("password_changed", "a@example.com", {})
    lines = [json.loads(x) for x in path.read_text().splitlines()]
    assert [x["template"] for x in lines] == ["signup_code", "password_changed"]
    assert lines[0]["params"]["code"] == "042424"


@pytest.mark.parametrize("env", ["staging", "prod", ""])
def test_local_file_mailer_refuses_outside_local_and_test(monkeypatch, tmp_path, env):
    monkeypatch.setenv("PLATFORM_ENV", env)
    with pytest.raises(RuntimeError):
        LocalFileMailer(tmp_path / "x.jsonl")

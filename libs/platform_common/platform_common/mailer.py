"""Sending mail (LLD-0 §3.11).

Mail that carries a code is handed over only after the request's transaction commits,
through `send_after_commit`, and never through the outbox, so a code never lands in
Postgres (HLD §7). In AWS the sender will be SqsMailer, which queues the message for
the mailer Lambda; it comes with Staff 2's mail queue and SES access (S0b).

Until then two senders exist, and neither sends anything real:
- FakeMailer records messages for tests.
- LocalFileMailer appends each message as a JSON line to a file, so a developer can
  read a sign-up code locally. It refuses to start outside PLATFORM_ENV local or test,
  and writes under the git-ignored build/ folder by default, since codes are plain text.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .auth import DEBUG_ENVS, platform_env

# Templates the mailer Lambda will render (LLD-1 §2 mailer/templates/).
TEMPLATES = frozenset(
    {"signup_code", "already_registered", "reset_code", "password_changed", "totp_on", "totp_off", "invitation"}
)


class Mailer(Protocol):
    def send(self, template: str, to: str, params: dict[str, str]) -> None: ...


def _check(template: str, to: str, params: dict[str, str]) -> None:
    if template not in TEMPLATES:
        raise ValueError(f"unknown mail template {template!r}")
    if "@" not in to or not all(isinstance(v, str) for v in params.values()):
        raise ValueError("mail needs an address and string params")


@dataclass
class FakeMailer:
    sent: list[tuple[str, str, dict[str, str]]] = field(default_factory=list)

    def send(self, template: str, to: str, params: dict[str, str]) -> None:
        _check(template, to, params)
        self.sent.append((template, to, dict(params)))

    def last(self, template: str, to: str) -> dict[str, str]:
        return next(p for t, a, p in reversed(self.sent) if t == template and a == to)


class LocalFileMailer:
    DEFAULT_PATH = Path("build/mail/outbox.jsonl")

    def __init__(self, path: Path = DEFAULT_PATH):
        if platform_env() not in DEBUG_ENVS:
            raise RuntimeError("LocalFileMailer is for local and test only")
        self.path = path

    def send(self, template: str, to: str, params: dict[str, str]) -> None:
        _check(template, to, params)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"template": template, "to": to, "params": params}) + "\n")


def send_after_commit(uow, mailer: Mailer, template: str, to: str, params: dict[str, str]) -> None:
    """Queue a message to go out only if `uow` commits. A failed send is logged by the
    unit of work and the commit stands; the user can ask for a new code."""
    _check(template, to, params)
    uow.after_commit(lambda: mailer.send(template, to, params))

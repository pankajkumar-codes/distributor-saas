"""Shared context: one database session, the policy, a clock and the git provider."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from . import policy as policy_mod
from .models import AuditLog, Base, Message, StateVersion, utcnow


class OrgError(Exception):
    """A rule refused the operation. `code` is stable for tests and the API."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def make_engine(url: str = "sqlite:///orgos.db") -> Engine:
    engine = create_engine(url)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _pragmas(dbapi_conn, _):
            dbapi_conn.execute("pragma foreign_keys=on")
            dbapi_conn.execute("pragma journal_mode=wal")

    Base.metadata.create_all(engine)
    return engine


@dataclass
class Org:
    session: Session
    policy: policy_mod.Policy
    clock: Callable[[], datetime] = utcnow
    provider: object | None = None  # see provider.py

    def now(self) -> datetime:
        return self.clock()

    def audit(self, actor: str, action: str, entity: str, **details) -> None:
        self.session.add(AuditLog(at=self.now(), actor=actor, action=action, entity=entity, details=details))
        self.touch()

    def message(self, type_: str, sender: str, recipient: str, body: str, *, task_id=None, pr_number=None,
                respond_by=None) -> Message:
        msg = Message(type=type_, sender=sender, recipient=recipient, body=body, task_id=task_id,
                      pr_number=pr_number, at=self.now(), respond_by=respond_by)
        self.session.add(msg)
        self.touch()
        return msg

    def touch(self) -> None:
        sv = self.session.get(StateVersion, 1)
        if sv is None:
            sv = StateVersion(id=1, version=0)
            self.session.add(sv)
        sv.version += 1
        sv.updated_at = self.now()

    def version(self) -> int:
        sv = self.session.scalar(select(StateVersion).where(StateVersion.id == 1))
        return sv.version if sv else 0


def open_org(url: str = "sqlite:///orgos.db", policy_path: Path | str | None = None, **kwargs) -> Org:
    engine = make_engine(url)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    pol = policy_mod.load(policy_path) if policy_path else policy_mod.load()
    return Org(session=session, policy=pol, **kwargs)

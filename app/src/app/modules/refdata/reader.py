"""Reads refdata rows by key and date (LLD-0 §6.4).

The whole of refdata.values and refdata.state_codes is a few hundred rows, so each
container keeps one snapshot in memory, keyed by the latest refdata.loads id. Every
call asks the database for that id (one indexed row) and reloads the snapshot when
it has changed, so a migrator load is picked up by the next request.

`tx` is the unit of work's session (uow.tx). refdata is global, so any unit of work
reads it, as app_rw or app_ro.
"""

import datetime as dt
import re
import threading
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

CONFIRMED = {"product": ("po_confirmed",), "tax": ("expert_confirmed", "ca_confirmed")}


class RefdataMissing(LookupError):
    """No row, or more than one, covers `key` on `on`."""

    def __init__(self, key: str, on: dt.date, found: int = 0):
        super().__init__(f"refdata {key!r} on {on.isoformat()}: {found} rows cover the date, need exactly 1")
        self.key, self.on, self.found = key, on, found


class RefdataUnconfirmed(Exception):
    """The row in force is still provisional (or confirmed by the wrong party for its kind)."""

    def __init__(self, key: str, on: dt.date, status: str, kind: str):
        super().__init__(f"refdata {key!r} on {on.isoformat()} is {status} ({kind} rows need {CONFIRMED[kind]})")
        self.key, self.on, self.status, self.kind = key, on, status, kind


@dataclass(frozen=True)
class _Row:
    value: str
    type: str
    kind: str
    status: str
    valid_from: dt.date
    valid_to: dt.date | None

    def covers(self, on: dt.date) -> bool:
        return self.valid_from <= on and (self.valid_to is None or on < self.valid_to)


@dataclass(frozen=True)
class _Snapshot:
    load_id: object
    values: dict[str, tuple[_Row, ...]]
    states: dict[str, tuple[tuple[str, dt.date, dt.date | None], ...]]


_lock = threading.Lock()
_snapshot: _Snapshot | None = None


def _current(tx: Session) -> _Snapshot:
    global _snapshot
    # Races, all benign: two requests that miss together both rebuild and the last
    # writer wins (both built a snapshot of the same rows or of a later load). A load
    # that commits between the id read below and the row reads gives a snapshot tagged
    # with the older id but holding newer rows; the next call sees the newer id and
    # rebuilds. Each table is read by one statement, so each is consistent in itself, and
    # values and state codes don't depend on each other.
    load_id = tx.execute(text("select id from refdata.loads order by at desc, id limit 1")).scalar()
    snap = _snapshot
    if snap is not None and snap.load_id == load_id:
        return snap
    values: dict[str, list[_Row]] = {}
    for key, value, type_, kind, status, valid_from, valid_to in tx.execute(
        text("select key, value, type, kind, status, valid_from, valid_to from refdata.values")
    ):
        values.setdefault(key, []).append(_Row(value, type_, kind, status, valid_from, valid_to))
    states: dict[str, list] = {}
    for code, name, valid_from, valid_to in tx.execute(
        text("select code, name, valid_from, valid_to from refdata.state_codes")
    ):
        states.setdefault(code, []).append((name, valid_from, valid_to))
    snap = _Snapshot(
        load_id,
        {k: tuple(v) for k, v in values.items()},
        {k: tuple(v) for k, v in states.items()},
    )
    with _lock:
        _snapshot = snap
    return snap


def _row(tx: Session, key: str, on: dt.date) -> _Row:
    if isinstance(on, dt.datetime) or not isinstance(on, dt.date):
        raise TypeError("`on` is a business date (Clock.today()), not a datetime")
    rows = [r for r in _current(tx).values.get(key, ()) if r.covers(on)]
    if len(rows) != 1:
        raise RefdataMissing(key, on, len(rows))
    return rows[0]


def _typed(row: _Row):
    if row.type == "integer":
        return int(row.value)
    if row.type == "decimal":
        return Decimal(row.value)
    if row.type == "boolean":
        return row.value == "true"
    if row.type == "pattern":
        return re.compile(row.value)
    return row.value  # text, enum


def value_on(tx: Session, key: str, on: dt.date) -> Decimal | int | str | bool | re.Pattern:
    """The value of `key` in force on `on`, read as its type. Raises RefdataMissing."""
    return _typed(_row(tx, key, on))


def require_confirmed(tx: Session, key: str, on: dt.date) -> None:
    """For go-live checks: raises unless the row in force is confirmed by the right party
    (po_confirmed for product rows; expert_ or ca_confirmed for tax rows) [RM4-9]."""
    row = _row(tx, key, on)
    if row.status not in CONFIRMED[row.kind]:
        raise RefdataUnconfirmed(key, on, row.status, row.kind)


def state_name(tx: Session, code: str, on: dt.date) -> str | None:
    """The state or UT name for a two-digit GST code on `on`, or None if the code isn't
    valid on that date. Asking is not an error: an unknown code is user input."""
    if isinstance(on, dt.datetime) or not isinstance(on, dt.date):
        raise TypeError("`on` is a business date (Clock.today()), not a datetime")
    names = [
        name
        for name, valid_from, valid_to in _current(tx).states.get(code, ())
        if valid_from <= on and (valid_to is None or on < valid_to)
    ]
    return names[0] if len(names) == 1 else None


def _reset_cache() -> None:
    """Tests only: forget the snapshot."""
    global _snapshot
    with _lock:
        _snapshot = None


def state_codes(tx: Session, on: dt.date) -> list[tuple[str, str]]:
    """Every (code, name) loaded and valid on `on`, by code. Only what refdata holds:
    a code missing from the load is missing here."""
    if isinstance(on, dt.datetime) or not isinstance(on, dt.date):
        raise TypeError("`on` is a business date (Clock.today()), not a datetime")
    out = []
    for code, rows in _current(tx).states.items():
        names = [name for name, valid_from, valid_to in rows if valid_from <= on and (valid_to is None or on < valid_to)]
        if len(names) == 1:
            out.append((code, names[0]))
    return sorted(out)

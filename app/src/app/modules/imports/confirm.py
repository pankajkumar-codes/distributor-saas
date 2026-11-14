"""What stands between a staged run and confirming it (R1-M7 slice 1, r1-m7-gstr1-build.md).

Read-only: `check` writes nothing and decides nothing about tax. It lists the reasons confirming is
refused, each with a count and the row numbers (never a cell value, a GSTIN or a document number), so
the user can fix the file or decide the rows and look again. Wording comes from refdata
`imports.confirm.<code>.label`. The gates:

- the run is staged, and its layout is verified (LLD-7 L7-13; a local demo may open that gate, below);
- the profile names the date that puts a row in a return (`imports.profile.<id>.period_field`);
  Flipkart and Meesho have none until CA item 1 is answered, so they are refused;
- every held row is decided, and no row is invalid or in conflict (nothing is left out silently);
- the lines of one document agree on its date, original invoice, buyer GSTIN and total;
- no live row of an earlier or parallel file has the same cross-run key and different values;
- no included row has fewer HSN digits than the rule for its date allows.

Included rows are the new and changed rows plus held rows the user accepted or fixed, never a row set
aside. A fix replaces the HSN for the check only; the row itself is never changed.
"""

import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import text

from app.modules.business.interface import fy_of, hsn_band_missing, hsn_min_digits
from app.modules.refdata import first_valid_from, value_on
from platform_common.auth import debug_env
from platform_common.errors import Conflict
from platform_common.uow import UnitOfWork

from . import runs
from .readers import reader_for_run

ROW_LIST_LIMIT = 20
LEFT_OUT_STATUSES = ("already_imported", "duplicate", "skipped_zero")
_NAME = re.compile(r"[a-z][a-z0-9_]*")


@dataclass(frozen=True)
class Blocker:
    code: str
    label: str
    count: int
    rows: tuple[int, ...] = ()  # row numbers, the first ROW_LIST_LIMIT


@dataclass(frozen=True)
class Note:
    code: str
    label: str


@dataclass(frozen=True)
class ConfirmCheck:
    run_id: uuid.UUID
    can_confirm: bool
    included: int
    changed: int  # included rows that differ from a confirmed earlier file (their accept or skip is chosen at confirm)
    left_out: dict[str, int] = field(default_factory=dict)
    blockers: tuple[Blocker, ...] = ()
    notes: tuple[Note, ...] = ()


@dataclass(frozen=True)
class _Row:
    id: uuid.UUID
    number: int
    status: str
    hold_reason: str | None
    values: dict
    content_hash: str | None
    resolution: str | None
    fix_field: str | None
    fix_value: str | None


def demo_verified() -> bool:
    """A local demo (`DEMO_READERS=1`, debug environment only, never on Lambda) opens the verified-layout
    gate so synthetic files can be taken end to end. Production profiles stay unverified."""
    return os.environ.get("DEMO_READERS") == "1" and debug_env()


def _label(uow: UnitOfWork, code: str, today: date) -> str:
    return str(value_on(uow.tx, f"imports.confirm.{code}.label", today))


def _load(uow: UnitOfWork, run_id: uuid.UUID) -> list[_Row]:
    found = uow.tx.execute(
        text(f"with latest as ({runs.LATEST})"
             " select w.id, w.row_number, w.status, w.hold_reason, w.normalized, w.content_hash,"
             " l.kind, l.fix_field, l.fix_value from imports.import_rows w left join latest l on l.row_id = w.id"
             " where w.run_id = :r and w.business_id = :b order by w.row_number"),
        {"r": run_id, "b": uow.principal.business_id},
    ).all()
    return [_Row(w.id, w.row_number, w.status, w.hold_reason, w.normalized or {}, w.content_hash, w.kind,
                 w.fix_field, w.fix_value) for w in found]


def _period_fields(uow: UnitOfWork, reader, today: date) -> tuple[str, ...] | None:
    key = f"imports.profile.{reader.id}.period_field"
    if first_valid_from(uow.tx, key) is None:
        return None
    return tuple(f.strip() for f in str(value_on(uow.tx, key, today)).split(",") if f.strip())


def _date_of(values: dict, fields: tuple[str, ...]) -> date | None:
    for name in fields:
        raw = values.get(name)
        if raw:
            try:
                return date.fromisoformat(str(raw).partition("T")[0])
            except ValueError:
                return None
    return None


def _same(a, b) -> bool:
    """Two cells agree when equal as numbers (if both read as numbers) or as trimmed, case-folded text."""
    a, b = ("" if a is None else str(a).strip()), ("" if b is None else str(b).strip())
    try:
        return Decimal(a) == Decimal(b)
    except InvalidOperation:
        return a.casefold() == b.casefold()


def _included(row: _Row) -> bool:
    if row.resolution == "set_aside":
        return False
    if row.status == "held":
        return row.resolution in ("accepted", "fixed")
    return row.status in ("new", "changed")


def _folded(value) -> str:
    return "".join(str(value or "").split()).upper()


def disagreeing_rows(rows: list[_Row], key: tuple[str, ...], agree: tuple[str, ...], period: tuple[str, ...]) -> list[int]:
    """Row numbers of documents whose included lines differ on one of `agree`. A document is its `key` plus
    the financial year of its date, so a number reused in another year is another document."""
    groups: dict[tuple, list[_Row]] = {}
    for row in rows:
        if not _included(row):
            continue
        d = _date_of(row.values, period)
        fy = None if d is None else fy_of(d)
        groups.setdefault((*(_folded(row.values.get(k)) for k in key), fy), []).append(row)
    bad: list[int] = []
    for lines in groups.values():
        first = lines[0].values
        if any(not _same(first.get(f), r.values.get(f)) for r in lines[1:] for f in agree):
            bad.extend(r.number for r in lines)
    return sorted(bad)


def _other_rows(uow: UnitOfWork, run, key: tuple[str, ...], mine: list[_Row]):
    for name in key:
        if not _NAME.fullmatch(name):
            raise ValueError(f"bad cross-run field name {name!r}")
    params: dict = {"b": uow.principal.business_id, "m": run.marketplace, "t": run.report_type, "r": run.id}
    wheres = []
    for i, name in enumerate(key):
        params[f"v{i}"] = sorted({str(r.values[name]) for r in mine if r.values.get(name) not in (None, "")})
        wheres.append(f" and w.normalized ->> '{name}' = any(:v{i})")
    return uow.tx.execute(
        text(f"with latest as ({runs.LATEST})"
             " select w.normalized, w.content_hash from imports.import_rows w"
             " join imports.import_runs r on r.id = w.run_id and r.business_id = w.business_id"
             " left join latest l on l.row_id = w.id"
             " where w.business_id = :b and r.marketplace = :m and r.report_type = :t and r.id <> :r"
             " and r.status in ('staged', 'confirmed') and w.status in ('new', 'changed', 'already_imported', 'held')"
             " and coalesce(l.kind, '') <> 'set_aside'" + "".join(wheres)),
        params,
    ).all()


def conflicting_rows(uow: UnitOfWork, run, reader, rows: list[_Row]) -> dict[uuid.UUID, int]:
    """This run's included rows (id -> row number) that share the reader's cross-run key with a live row of
    another file but differ in values. The older file's row is not offered a decision here: a staged file is
    discarded, and a confirmed row stays."""
    key = getattr(reader, "cross_run_key", None)
    mine = [r for r in rows if _included(r) and r.content_hash]
    if not key or not mine:
        return {}
    theirs: dict[tuple, set[str]] = {}
    for other in _other_rows(uow, run, key, mine):
        theirs.setdefault(tuple(str(other.normalized.get(k)) for k in key), set()).add(other.content_hash)
    return {r.id: r.number for r in mine
            if (hashes := theirs.get(tuple(str(r.values.get(k)) for k in key))) and not hashes <= {r.content_hash}}


def conflicting_row_ids(uow: UnitOfWork, run_id: uuid.UUID) -> set[uuid.UUID]:
    """For the row list: which rows of a staged run may be set aside because of a cross-run clash."""
    run = runs.get_run(uow, run_id)
    reader = reader_for_run(run.section, run.report_type)
    if run.status != "staged" or reader is None or not getattr(reader, "cross_run_key", None):
        return set()
    return set(conflicting_rows(uow, run, reader, _load(uow, run_id)))


def check(uow: UnitOfWork, run_id: uuid.UUID, today: date) -> ConfirmCheck:
    run = runs.get_run(uow, run_id)  # a run of another business is a 404
    if run.status != "staged":
        raise Conflict("run_not_staged", "This file has already been used, so it can't be confirmed.")
    reader = reader_for_run(run.section, run.report_type)
    rows = _load(uow, run_id)
    blockers: list[Blocker] = []

    def block(code: str, numbers: list[int] | None = None) -> None:
        count = 1 if numbers is None else len(numbers)
        blockers.append(Blocker(code, _label(uow, code, today), count, tuple((numbers or [])[:ROW_LIST_LIMIT])))

    if not (run.profile_verified or demo_verified()):
        block("profile_not_verified")
    period = None if reader is None else _period_fields(uow, reader, today)
    if period is None:
        block("period_date_unconfirmed")

    undecided = [r.number for r in rows if r.status == "held" and r.resolution is None]
    invalid = [r.number for r in rows if r.status == "invalid"]
    clashing = [r.number for r in rows if r.status == "conflict"]
    for code, numbers in (("rows_undecided", undecided), ("rows_invalid", invalid), ("rows_conflict", clashing)):
        if numbers:
            block(code, numbers)

    included = [r for r in rows if _included(r)]
    if reader is not None:
        key, agree = getattr(reader, "document_key", None), getattr(reader, "document_agree", None)
        if key and agree and period is not None and (numbers := disagreeing_rows(rows, key, agree, period)):
            block("document_rows_disagree", numbers)
        if clash := conflicting_rows(uow, run, reader, rows):  # reported even while the period date is open
            block("rows_conflict_across_runs", sorted(clash.values()))

    notes: list[Note] = []
    if period is not None:
        short: list[int] = []
        digits: dict[date, int] = {}
        band_missing = False
        for r in included:
            d = _date_of(r.values, period)
            if d is None:
                continue
            if d not in digits:
                digits[d] = hsn_min_digits(uow.tx, d)
                band_missing = band_missing or hsn_band_missing(uow.tx, d) is not None
            hsn = r.fix_value if (r.resolution == "fixed" and r.fix_field == "hsn") else r.values.get("hsn")
            if len(str(hsn or "")) < digits[d]:
                short.append(r.number)
        if short:
            block("hsn_too_short", short)
        if band_missing:
            notes.append(Note("hsn_band_missing", _label(uow, "hsn_band_missing", today)))

    left_out = {"set_aside": sum(1 for r in rows if r.resolution == "set_aside")}
    for status in LEFT_OUT_STATUSES:
        left_out[status] = sum(1 for r in rows if r.status == status and r.resolution != "set_aside")
    return ConfirmCheck(
        run_id=run_id, can_confirm=not blockers, included=len(included),
        changed=sum(1 for r in included if r.status == "changed"), left_out=left_out,
        blockers=tuple(blockers), notes=tuple(notes),
    )

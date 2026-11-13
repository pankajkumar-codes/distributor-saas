"""Reads of staged runs and their rows for the preview (R1-M3, LLD-7 §8).

A run is what one file said; rows are insert-only. The labels and effect notes for a held
row come from refdata (`imports.held.<reason>.*`), never from code, so the wording can be
settled with the platform reader spec without a release. Every query filters `business_id`
as well as relying on row-level security; an unknown or foreign id is a 404.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text

from app.modules.refdata import value_on
from platform_common.errors import Deny, Invalid
from platform_common.uow import UnitOfWork

from .readers import HOLD_REASONS

ROW_STATUSES = ("new", "already_imported", "changed", "duplicate", "conflict", "invalid", "held", "skipped_zero")
COUNT_KEYS = ROW_STATUSES
SKIPPED_ZERO_LABEL = "Zero value: nothing to file."


@dataclass(frozen=True)
class Run:
    id: uuid.UUID
    upload_id: uuid.UUID | None
    section: str | None
    marketplace: str
    profile_id: str
    profile_verified: bool
    gstin: str | None
    status: str
    summary: dict
    held_by_reason: dict[str, int]


@dataclass(frozen=True)
class Row:
    id: uuid.UUID
    run_id: uuid.UUID
    file_name: str
    row_number: int
    status: str
    hold_reason: str | None
    values: dict
    errors: list
    reason_label: str | None
    needs_ca_check: bool
    ca_check_note: str | None


def _business(uow: UnitOfWork) -> uuid.UUID:
    return uow.principal.business_id


def get_run(uow: UnitOfWork, run_id: uuid.UUID) -> Run:
    r = uow.tx.execute(
        text("select r.id, r.upload_id, u.section, r.marketplace, r.profile_id, r.profile_verified, r.gstin, r.status,"
             " r.summary from imports.import_runs r left join imports.uploads u"
             " on u.id = r.upload_id and u.business_id = r.business_id where r.id = :r and r.business_id = :b"),
        {"r": run_id, "b": _business(uow)},
    ).one_or_none()
    if r is None:
        raise Deny("not_found")
    held = {
        reason: n
        for reason, n in uow.tx.execute(
            text("select hold_reason, count(*) from imports.import_rows where run_id = :r and business_id = :b"
                 " and status = 'held' group by hold_reason"),
            {"r": run_id, "b": _business(uow)},
        )
    }
    return Run(r.id, r.upload_id, r.section, r.marketplace, r.profile_id, r.profile_verified, r.gstin, r.status,
               r.summary or {}, held)


def counts(run: Run) -> dict[str, int]:
    return {k: int(run.summary.get(k, 0)) for k in COUNT_KEYS}


def list_rows(uow: UnitOfWork, run_id: uuid.UUID, status: str | None, limit: int, offset: int,
              today: date) -> tuple[list[Row], bool]:
    get_run(uow, run_id)  # 404 for a run that isn't this business's
    if status is not None and status not in ROW_STATUSES:
        raise Invalid("unknown_status", "That isn't a row status.", field="status")
    found = uow.tx.execute(
        text("select w.id, w.run_id, r.filename, w.row_number, w.status, w.hold_reason, w.raw, w.errors"
             " from imports.import_rows w join imports.import_runs r on r.id = w.run_id and r.business_id = w.business_id"
             " where w.run_id = :r and w.business_id = :b and (cast(:s as text) is null or w.status = :s)"
             " order by w.row_number limit :n offset :o"),
        {"r": run_id, "b": _business(uow), "s": status, "n": limit + 1, "o": offset},
    ).all()
    labels: dict[str, tuple[str, bool]] = {}

    def held_words(reason: str) -> tuple[str, bool]:
        if reason not in labels:
            labels[reason] = (str(value_on(uow.tx, f"imports.held.{reason}.label", today)),
                              bool(value_on(uow.tx, f"imports.held.{reason}.needs_ca_check", today)))
        return labels[reason]

    rows = []
    for w in found[:limit]:
        label, ca = None, False
        if w.status == "held" and w.hold_reason in HOLD_REASONS:
            label, ca = held_words(w.hold_reason)
        elif w.status == "skipped_zero":
            label = SKIPPED_ZERO_LABEL
        rows.append(Row(w.id, w.run_id, w.filename, w.row_number, w.status, w.hold_reason,
                        {k: "" if v is None else str(v) for k, v in (w.raw or {}).items()},
                        _errors(w.errors), label, ca, None))
    return rows, len(found) > limit


def _errors(value) -> list[dict]:
    items = json.loads(value) if isinstance(value, str) else (value or [])
    return [{"field": e.get("field"), "code": e.get("code"), "message": e.get("message")} for e in items]

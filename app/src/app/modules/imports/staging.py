"""Stores a parsed report as an import run with one row per source row.

Staging is idempotent: the same bytes for the same business and report type always map
to one run, so a retried upload (or two concurrent ones) returns the existing run.
Rows are compared against earlier *confirmed* runs of the same report type to tell a
new record from one already imported, or one whose values changed since.

The caller runs inside a business unit of work (LLD-0), which has checked the caller's
active membership and set app.tenant_id (the business id) for row-level security. Every query here still
filters by business_id explicitly.
"""

import datetime as dt
import hashlib
import json
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from platform_common.clock import Clock
from platform_common.ids import uuid7

from .models import ImportRow, ImportRun, RunStatus, StagedRowStatus
from .parsing import MappingProfile, RowStatus, SourceTable, parse

_LOOKUP_BATCH = 500


class RunStateError(ValueError):
    pass


def stage(
    session: Session, *, business_id: uuid.UUID, user_id: uuid.UUID, table: SourceTable, profile: MappingProfile
) -> tuple[ImportRun, bool]:
    """Returns (run, created). created is False when this file was already staged."""
    existing = _find_run(session, business_id, profile, table.checksum_sha256)
    if existing is not None:
        return existing, False

    result = parse(table, profile)
    keys = {r.row_number: _key_digest(r.dedup_key) for r in result.rows if r.dedup_key is not None}
    previous = _latest_confirmed_hashes(session, business_id, profile, set(keys.values()))

    run = ImportRun(
        id=uuid7(),
        business_id=business_id,
        marketplace=profile.marketplace,
        report_type=profile.report_type,
        profile_id=profile.profile_id,
        profile_verified=profile.verified,
        filename=table.filename[:255],
        checksum_sha256=table.checksum_sha256,
        sheet=table.sheet,
        header_row_number=result.header_row_number,
        status=RunStatus.staged,
        uploaded_by=user_id,
    )
    rows = []
    counts = {s.value: 0 for s in StagedRowStatus}
    for parsed in result.rows:
        key = keys.get(parsed.row_number)
        status = _staged_status(parsed.status, previous.get(key), parsed.content_hash)
        counts[status.value] += 1
        rows.append(
            ImportRow(
                id=uuid7(),
                run_id=run.id,
                business_id=business_id,
                row_number=parsed.row_number,
                status=status,
                raw=parsed.raw,
                normalized=_jsonable(parsed.normalized),
                errors=_errors(parsed),
                dedup_values=list(parsed.dedup_key) if parsed.dedup_key is not None else None,
                dedup_key=key,
                content_hash=parsed.content_hash,
            )
        )
    counts["total"] = len(rows)
    counts["skipped_blank"] = result.skipped_blank_rows
    run.summary = {
        **counts,
        # Header names only: personal and unmapped columns are read but never stored.
        "columns_not_stored": result.personal_headers + result.unmapped_headers,
    }

    try:
        with session.begin_nested():
            session.add(run)
            session.flush()
            session.add_all(rows)
            session.flush()
    except IntegrityError:
        # A concurrent upload of the same file won the race; use its run.
        existing = _find_run(session, business_id, profile, table.checksum_sha256)
        if existing is None:
            raise
        return existing, False
    return run, True


def confirm(
    session: Session, *, business_id: uuid.UUID, run_id: uuid.UUID, user_id: uuid.UUID, clock: Clock | None = None
) -> ImportRun:
    """Marks a staged run confirmed. Repeating it is a no-op.

    Handing confirmed rows to commerce is a separate, versioned contract (plan task
    T-202); until it exists, confirming only records the decision.
    """
    run = _get_run(session, business_id, run_id)
    if run.status == RunStatus.confirmed:
        return run
    if run.status != RunStatus.staged:
        raise RunStateError(f"run is {run.status.value}; only a staged run can be confirmed")
    run.status = RunStatus.confirmed
    run.confirmed_by = user_id
    run.confirmed_at = (clock or Clock()).now()
    session.flush()
    return run


def discard(session: Session, *, business_id: uuid.UUID, run_id: uuid.UUID) -> ImportRun:
    run = _get_run(session, business_id, run_id)
    if run.status == RunStatus.discarded:
        return run
    if run.status != RunStatus.staged:
        raise RunStateError(f"run is {run.status.value}; only a staged run can be discarded")
    run.status = RunStatus.discarded
    session.flush()
    return run


def _get_run(session: Session, business_id: uuid.UUID, run_id: uuid.UUID) -> ImportRun:
    run = session.scalar(
        select(ImportRun).where(ImportRun.id == run_id, ImportRun.business_id == business_id).with_for_update()
    )
    if run is None:
        raise LookupError("import run not found")
    return run


def _find_run(session, business_id, profile, checksum) -> ImportRun | None:
    return session.scalar(
        select(ImportRun).where(
            ImportRun.business_id == business_id,
            ImportRun.marketplace == profile.marketplace,
            ImportRun.report_type == profile.report_type,
            ImportRun.checksum_sha256 == checksum,
            ImportRun.status != RunStatus.discarded,
        )
    )


def _latest_confirmed_hashes(session, business_id, profile, keys: set[str]) -> dict[str, str]:
    latest: dict[str, str] = {}
    ordered = sorted(keys)
    for start in range(0, len(ordered), _LOOKUP_BATCH):
        batch = ordered[start : start + _LOOKUP_BATCH]
        found = session.execute(
            select(ImportRow.dedup_key, ImportRow.content_hash)
            .join(ImportRun, ImportRun.id == ImportRow.run_id)
            .where(
                ImportRow.business_id == business_id,
                ImportRun.business_id == business_id,
                ImportRun.marketplace == profile.marketplace,
                ImportRun.report_type == profile.report_type,
                ImportRun.status == RunStatus.confirmed,
                ImportRow.status.in_([StagedRowStatus.new, StagedRowStatus.changed]),
                ImportRow.dedup_key.in_(batch),
            )
            .order_by(ImportRun.confirmed_at, ImportRow.row_number)
        )
        for key, content_hash in found:
            latest[key] = content_hash  # later confirmations overwrite earlier ones
    return latest


def _staged_status(parsed: RowStatus, previous_hash: str | None, content_hash: str | None) -> StagedRowStatus:
    if parsed == RowStatus.invalid:
        return StagedRowStatus.invalid
    if parsed == RowStatus.duplicate:
        return StagedRowStatus.duplicate
    if parsed == RowStatus.conflict:
        return StagedRowStatus.conflict
    if previous_hash is None:
        return StagedRowStatus.new
    return StagedRowStatus.already_imported if previous_hash == content_hash else StagedRowStatus.changed


def _errors(parsed) -> list[dict]:
    errors = [
        {"field": e.field, "code": e.code, "message": e.message, "related_rows": parsed.related_rows}
        for e in parsed.errors
    ]
    if parsed.status == RowStatus.duplicate:
        errors.append(
            {"field": None, "code": "duplicate", "message": "repeats an earlier row in this file",
             "related_rows": parsed.related_rows}
        )
    return errors


def _key_digest(key: tuple[str, ...]) -> str:
    return hashlib.sha256(json.dumps(list(key)).encode()).hexdigest()


def _jsonable(values: dict | None) -> dict | None:
    if values is None:
        return None
    out = {}
    for name, value in values.items():
        if isinstance(value, Decimal):
            out[name] = str(value)  # string, never float, so no precision is lost
        elif isinstance(value, (dt.date, dt.datetime)):
            out[name] = value.isoformat()
        else:
            out[name] = value
    return out

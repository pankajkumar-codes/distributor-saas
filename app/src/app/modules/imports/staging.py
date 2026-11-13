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
from collections.abc import Callable
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from platform_common.clock import Clock
from platform_common.ids import uuid7

from .models import ImportRow, ImportRun, RunStatus, StagedRowStatus
from .parsing import MappingProfile, ParsedRow, ParseResult, RowStatus, SourceTable, parse

_LOOKUP_BATCH = 500


class RunStateError(ValueError):
    pass


class StaleRun(RunStateError):
    """Another file confirmed since staging changed what this run's rows would be."""


Classify = Callable[[ParsedRow], "tuple[StagedRowStatus, str | None] | None"]


def stage(
    session: Session,
    *,
    business_id: uuid.UUID,
    user_id: uuid.UUID,
    table: SourceTable,
    profile: MappingProfile,
    upload_id: uuid.UUID | None = None,
    gstin: str | None = None,
    classify: Classify | None = None,
    flag_live_overlap: bool = False,
    result: ParseResult | None = None,
    months: list[str] | None = None,
) -> tuple[ImportRun, bool]:
    """Returns (run, created). created is False when this file was already staged.

    `classify` is the reader's hold rule. It sees only rows that parsed as valid and may
    return (held, reason) or (skipped_zero, None); a held or skipped row is kept with that
    status and is not counted as new, already imported or changed.

    With `flag_live_overlap` (the upload path), a record already held by another live staged file
    of the same report type is shown as a duplicate, so the preview never promises a count that
    confirming both files would double. The first file staged keeps the record; discarding it frees
    it. Off by default: the older flow compares only against confirmed runs and settles overlap at
    confirm (StaleRun).

    `months` (from `coverage_months`) are the calendar months this file covers, stored in `summary.months`
    when the run is inserted (the app role cannot update a run afterwards). That is for the coverage view
    only: it is not the return period, which the build decides once the CA has answered (spec section 5,
    item 1). `result` is the file already parsed with this profile, so the caller can read its months first.
    `summary.already_uploaded_of` is the id of an earlier preview of this same file that was discarded."""
    existing = _find_run(session, business_id, profile, table.checksum_sha256)
    if existing is not None:
        return existing, False

    result = result if result is not None else parse(table, profile)
    keys = {r.row_number: _key_digest(r.dedup_key) for r in result.rows if r.dedup_key is not None}
    previous = _latest_confirmed_hashes(
        session, business_id, profile.marketplace, profile.report_type, set(keys.values())
    )

    elsewhere: set[str] = set()
    if flag_live_overlap:
        # Same lock as confirm, held until this transaction ends: two jobs staging overlapping
        # files of one report type are serialised, so the second sees the first's rows.
        _lock_report_type(session, business_id, profile.marketplace, profile.report_type)
        elsewhere = _live_staged_keys(session, business_id, profile, set(keys.values()))

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
        upload_id=upload_id,
        gstin=gstin,
    )
    rows = []
    counts = {s.value: 0 for s in StagedRowStatus}
    for parsed in result.rows:
        key = keys.get(parsed.row_number)
        status = _staged_status(parsed.status, previous.get(key), parsed.content_hash)
        hold_reason = None
        extra_errors: list[dict] = []
        if status == StagedRowStatus.new and key in elsewhere:
            # Another live, unconfirmed file of this report type already has this record: show it as
            # a duplicate so the preview never promises a count that confirming both would double.
            status = StagedRowStatus.duplicate
            extra_errors = [{"field": None, "code": "duplicate_in_other_file",
                             "message": "already in another uploaded file", "related_rows": []}]
        elif classify is not None and parsed.status == RowStatus.valid:
            verdict = classify(parsed)
            if verdict is not None:
                status, hold_reason = verdict
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
                errors=_errors(parsed) + extra_errors,
                dedup_values=list(parsed.dedup_key) if parsed.dedup_key is not None else None,
                dedup_key=key,
                content_hash=parsed.content_hash,
                hold_reason=hold_reason,
            )
        )
    counts["total"] = len(rows)
    counts["skipped_blank"] = result.skipped_blank_rows
    earlier = session.scalar(
        select(ImportRun.id).where(
            ImportRun.business_id == business_id, ImportRun.marketplace == profile.marketplace,
            ImportRun.report_type == profile.report_type, ImportRun.checksum_sha256 == table.checksum_sha256,
            ImportRun.status == RunStatus.discarded).order_by(ImportRun.uploaded_at.desc()).limit(1))
    run.summary = {
        **counts,
        "months": list(months or []),
        **({"already_uploaded_of": str(earlier)} if earlier is not None else {}),
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

    Row statuses were worked out at staging. If another file of the same report type
    was confirmed since, a row this run calls `new` may already be imported, so the
    statuses are checked again under a per-report-type lock and a stale run is refused
    (StaleRun: discard it and stage the file again). Two confirms of overlapping files
    therefore never both import the same record.

    Handing confirmed rows to commerce is a separate, versioned contract (plan task
    T-202); until it exists, confirming only records the decision.
    """
    run = _get_run(session, business_id, run_id)
    if run.status == RunStatus.confirmed:
        return run
    if run.status != RunStatus.staged:
        raise RunStateError(f"run is {run.status.value}; only a staged run can be confirmed")
    _lock_report_type(session, business_id, run.marketplace, run.report_type)
    stale = _stale_rows(session, run)
    if stale:
        raise StaleRun(
            f"{stale} row(s) changed status because another file was confirmed or discarded after this one was "
            "staged; discard this run and stage the file again"
        )
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


def _live_staged_keys(session, business_id, profile, keys: set[str]) -> set[str]:
    """Record keys that a live staged run of the same report type already holds as real rows
    (not invalid or duplicate there). The first file staged keeps them; discarding it frees them."""
    found: set[str] = set()
    ordered = sorted(keys)
    for start in range(0, len(ordered), _LOOKUP_BATCH):
        batch = ordered[start : start + _LOOKUP_BATCH]
        found.update(
            session.scalars(
                select(ImportRow.dedup_key)
                .join(ImportRun, ImportRun.id == ImportRow.run_id)
                .where(
                    ImportRow.business_id == business_id,
                    ImportRun.business_id == business_id,
                    ImportRun.marketplace == profile.marketplace,
                    ImportRun.report_type == profile.report_type,
                    ImportRun.status == RunStatus.staged,
                    ImportRow.status.in_([StagedRowStatus.new, StagedRowStatus.changed, StagedRowStatus.held,
                                          StagedRowStatus.skipped_zero]),
                    ImportRow.dedup_key.in_(batch),
                )
            )
        )
    return found


def coverage_months(result: ParseResult, field: str | None) -> list[str]:
    """The calendar months of one parsed date field, for the coverage view."""
    return sorted({f"{r.normalized[field]:%Y-%m}" for r in result.rows
                   if field and r.normalized and r.normalized.get(field) is not None})


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


def _lock_report_type(session: Session, business_id: uuid.UUID, marketplace: str, report_type: str) -> None:
    # Serialises confirms of one business's report type until the transaction ends.
    if session.get_bind().dialect.name != "postgresql":
        return  # SQLite unit tests: one connection, nothing runs concurrently
    key = f"imports.confirm:{business_id}:{marketplace}:{report_type}"
    session.execute(text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": key})


def _stale_rows(session: Session, run: ImportRun) -> int:
    compared = (StagedRowStatus.new, StagedRowStatus.already_imported, StagedRowStatus.changed)
    rows = session.execute(
        select(ImportRow.status, ImportRow.dedup_key, ImportRow.content_hash).where(
            ImportRow.run_id == run.id, ImportRow.business_id == run.business_id, ImportRow.status.in_(compared)
        )
    ).all()
    previous = _latest_confirmed_hashes(
        session, run.business_id, run.marketplace, run.report_type, {r.dedup_key for r in rows if r.dedup_key}
    )
    stale = sum(
        1 for r in rows if _staged_status(RowStatus.valid, previous.get(r.dedup_key), r.content_hash) != r.status
    )
    return stale + _orphaned_overlaps(session, run)


def _orphaned_overlaps(session: Session, run: ImportRun) -> int:
    """Rows staged as `duplicate_in_other_file` whose record no other live or confirmed run holds
    any more (the file that had it was discarded). Rows are insert-only, so they cannot be
    re-evaluated; the run is stale instead and its file is staged again."""
    marked = [
        (r.dedup_key, r.errors)
        for r in session.execute(
            select(ImportRow.dedup_key, ImportRow.errors).where(
                ImportRow.run_id == run.id, ImportRow.business_id == run.business_id,
                ImportRow.status == StagedRowStatus.duplicate, ImportRow.dedup_key.is_not(None),
            )
        )
    ]
    keys = {k for k, errors in marked if any(e.get("code") == "duplicate_in_other_file" for e in (errors or []))}
    if not keys:
        return 0
    held: set[str] = set()
    ordered = sorted(keys)
    for start in range(0, len(ordered), _LOOKUP_BATCH):
        held.update(
            session.scalars(
                select(ImportRow.dedup_key)
                .join(ImportRun, ImportRun.id == ImportRow.run_id)
                .where(
                    ImportRow.business_id == run.business_id,
                    ImportRun.business_id == run.business_id,
                    ImportRun.id != run.id,
                    ImportRun.marketplace == run.marketplace,
                    ImportRun.report_type == run.report_type,
                    ImportRun.status.in_([RunStatus.staged, RunStatus.confirmed]),
                    ImportRow.status.in_([StagedRowStatus.new, StagedRowStatus.changed, StagedRowStatus.held,
                                          StagedRowStatus.skipped_zero]),
                    ImportRow.dedup_key.in_(ordered[start : start + _LOOKUP_BATCH]),
                )
            )
        )
    return len(keys - held)


def _latest_confirmed_hashes(session, business_id, marketplace, report_type, keys: set[str]) -> dict[str, str]:
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
                ImportRun.marketplace == marketplace,
                ImportRun.report_type == report_type,
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

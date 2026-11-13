"""The parse job's reading step (LLD-7 §3, R1-M3): from an uploaded file's bytes to staged runs.

Unpacks a zip (guarded), reads each file into a table, finds the one reader of the section
that recognises it, checks the file is the business's own (seller GSTIN), and stages it
through `staging.stage`, which applies the reader's hold rule. A file that cannot be used
raises `Refused` with a code the upload keeps as its reject reason; nothing is staged for
it. Staging runs in the caller's transaction, so a crash leaves no half run.

Cell values never reach a log or an audit row from here; only ids and counts do.
"""

import dataclasses
import logging
import uuid

from app.modules.business.interface import business_card
from app.modules.refdata import first_valid_from, value_on
from platform_common.uow import UnitOfWork

from . import staging
from .models import ImportRun, StagedRowStatus
from .parsing import FileRejected, open_zip, read_table, sheet_names
from .readers import HOLD_REASONS, Reader, readers_for

log = logging.getLogger(__name__)


class Refused(Exception):
    """The file can't be used. `code` is the upload's reject reason."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def read_upload(uow: UnitOfWork, *, upload_id: uuid.UUID, section: str, file_name: str, content: bytes,
                today) -> list[ImportRun]:
    """Stages every file in the upload and returns its runs in file order."""
    readers = readers_for(section)
    files = _files(uow, file_name, content, readers, today)
    business_id = uow.principal.business_id
    card = business_card(uow.tx, [business_id])
    own_gstin = card[0].gstin if card else None

    parsed = []
    for name, data in files:
        for table in _tables(name, data, readers):
            matches = [r for r in readers if _sheet_ok(r, table) and r.detect(table)]
            if not matches:
                raise Refused("unknown_layout")
            if len(matches) > 1:
                raise Refused("needs_choice")  # the choose endpoint arrives with a second reader of one layout
            reader = matches[0]
            # Every file is checked before any is staged, so a refusal never leaves a run behind.
            file_gstin = reader.gstin(table)
            if not file_gstin:
                raise Refused("gstin_missing")
            if own_gstin is None or file_gstin.strip().upper() != own_gstin:
                raise Refused("wrong_gstin")
            parsed.append((table, reader))

    runs: list[ImportRun] = []
    created_runs: list[ImportRun] = []
    for table, reader in parsed:
        run, created = staging.stage(
            uow.tx,
            business_id=business_id,
            user_id=uow.principal.user_id,
            table=table,
            profile=_profile(uow, reader, today),
            upload_id=upload_id,
            gstin=own_gstin,
            classify=_classifier(reader),
            flag_live_overlap=True,
            coverage_field=getattr(reader, "coverage_field", None),
        )
        log.info("upload %s staged run %s (created=%s)", upload_id, run.id, created)
        runs.append(run)
        if created:
            created_runs.append(run)
    # A sheet with no rows (a month with no cash-back) has no dates of its own: it covers the months of
    # the other sheets of the same file.
    shared = sorted({m for r in created_runs for m in r.summary.get("months", [])})
    for r in created_runs:
        if not r.summary.get("months") and shared:
            r.summary = {**r.summary, "months": shared}
    return runs


def _same_sheet(a: str | None, b: str | None) -> bool:
    return a is not None and b is not None and a.strip().lower() == b.strip().lower()


def _sheet_ok(reader: Reader, table) -> bool:
    wanted = getattr(reader, "sheet", None)
    return wanted is None or _same_sheet(wanted, table.sheet)


def _tables(name: str, data: bytes, readers: list[Reader]) -> list:
    """The tables to read from one file. A workbook with several sheets is read sheet by sheet: each
    sheet a reader of the section names becomes a table; other sheets (a Help sheet) are not read.
    A workbook none of whose sheets any reader names is read as before, which refuses it if it
    has several."""
    try:
        if name.lower().endswith(".xlsx"):
            wanted = [s for s in sheet_names(data) if any(_same_sheet(getattr(r, "sheet", None), s) for r in readers)]
            if wanted:
                tables = [read_table(data, name, sheet=s) for s in wanted]
                return [t for t in tables if len(t.rows) > 1] or tables  # a sheet with a header and no rows has nothing to stage
        return [read_table(data, name)]
    except FileRejected:
        raise Refused("unreadable_file") from None


def _files(uow, file_name, content, readers: list[Reader], today) -> list[tuple[str, bytes]]:
    if not file_name.lower().endswith(".zip"):
        return [(file_name, content)]
    try:
        return open_zip(
            content,
            accepts=lambda name: any(r.accepts(name) for r in readers),
            max_entries=int(value_on(uow.tx, "imports.zip.max_entries", today)),
            max_inflate_bytes=int(value_on(uow.tx, "imports.zip.max_inflate_bytes", today)),
        )
    except FileRejected:
        raise Refused("bad_zip") from None


def _profile(uow, reader: Reader, today):
    """The reader's profile, usable as verified only when refdata also says so (LLD-7 L7-13).
    A reader with no refdata row counts as not verified."""
    profile = reader.profile()
    key = f"imports.profile.{reader.id}.verified"
    flag = bool(value_on(uow.tx, key, today)) if first_valid_from(uow.tx, key) is not None else False
    return dataclasses.replace(profile, verified=profile.verified and flag)


def _classifier(reader: Reader):
    def classify(parsed):
        verdict = reader.classify(parsed)
        if verdict is None:
            return None
        status, reason = verdict
        if status == StagedRowStatus.held and reason not in HOLD_REASONS:
            raise ValueError(f"reader {reader.id!r} chose a hold reason it may not: {reason!r}")
        if status == StagedRowStatus.skipped_zero:
            return status, None
        if status != StagedRowStatus.held:
            raise ValueError(f"reader {reader.id!r} may only hold or skip a row, not {status!r}")
        return status, reason

    return classify


__all__ = ["Refused", "read_upload"]
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
from app.modules.refdata import first_valid_from, state_codes, value_on
from platform_common.uow import UnitOfWork

from . import staging
from .pdf import Limits, PdfRefused, to_table
from .pdf.sandbox import read_sandboxed
from .models import ImportRun, StagedRowStatus
from .parsing import FileRejected, open_zip, parse, read_table, sheet_names
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
    tables = [table for name, data in files for table in _tables(name, data, readers)]
    return stage_tables(uow, upload_id=upload_id, readers=readers, tables=tables, today=today)


# What a refused PDF is called on the upload. The three ways the child can die or run out (killed for time or memory,
# unreadable) all say "we could not read it", never what the file held.
PDF_REJECTS = {"not_a_pdf": "not_a_pdf", "encrypted": "pdf_encrypted", "ambiguous_split": "pdf_ambiguous",
               "too_many_pages": "pdf_too_big", "too_many_documents": "pdf_too_big"}
MB = 1024 * 1024


def read_pdf(uow: UnitOfWork, *, upload_id: uuid.UUID, file_name: str, content: bytes, today) -> list[ImportRun]:
    """Reads an own-invoice PDF in the sandbox and stages its invoices like a spreadsheet's rows. A PDF with a page that
    has no text layer (a scan or a photo) is refused whole: a page with no text has no row to hold, and OCR is a later
    slice."""
    tx = uow.tx
    limits = Limits(max_pages=int(value_on(tx, "imports.pdf.max_pages", today)),
                    max_chars_per_page=int(value_on(tx, "imports.pdf.max_chars_per_page", today)),
                    max_documents=int(value_on(tx, "imports.pdf.max_documents", today)),
                    max_seconds=int(value_on(tx, "imports.pdf.max_seconds", today)))
    try:
        result = read_sandboxed(content, limits, value_on(tx, "hsn.pattern", today).pattern,
                                max_memory_bytes=int(value_on(tx, "imports.pdf.max_memory_mb", today)) * MB)
    except PdfRefused as refused:
        raise Refused(PDF_REJECTS.get(refused.code, "read_failed")) from None
    if result.unreadable_pages or not result.invoices:
        raise Refused("no_text_layer")
    table = to_table(result.invoices, filename=file_name, pdf=content)
    return stage_tables(uow, upload_id=upload_id, readers=readers_for("own_invoices_pdf"), tables=[table],
                        today=today)


def stage_tables(uow: UnitOfWork, *, upload_id: uuid.UUID, readers: list[Reader], tables: list,
                 today) -> list[ImportRun]:
    """Checks each table against the section's readers and the business's own GSTIN, then stages them. Shared by
    the files read from a spreadsheet and the table made from a PDF's extraction (R1-M6)."""
    business_id = uow.principal.business_id
    card = business_card(uow.tx, [business_id])
    own_gstin = card[0].gstin if card else None

    parsed = []
    for table in tables:
        matches = [r for r in readers if _sheet_ok(r, table) and r.detect(table)]
        if not matches:
            raise Refused("unknown_layout")
        if len(matches) > 1:
            raise Refused("needs_choice")  # the choose endpoint arrives with a second reader of one layout
        reader = matches[0]
        # Every file is checked before any is staged, so a refusal never leaves a run behind.
        file_gstin = reader.gstin(table)
        if not file_gstin:
            has_rows = getattr(reader, "has_rows", None)
            if has_rows is not None and not has_rows(table):
                parsed.append((table, reader))  # a header and no rows: an empty run, nothing to check
                continue
            raise Refused("gstin_missing")
        if own_gstin is None or file_gstin.strip().upper() != own_gstin:
            raise Refused("wrong_gstin")
        parsed.append((table, reader))

    # Parse every table first, so a sheet with no rows (a month with no cash-back) can take the months of the
    # other sheets of its file when its run is inserted: the app role cannot update a run afterwards.
    profiles = [_profile(uow, reader, today) for _, reader in parsed]
    results = [parse(table, profile) for (table, _), profile in zip(parsed, profiles, strict=True)]
    own = [staging.coverage_months(res, getattr(reader, "coverage_field", None))
           for res, (_, reader) in zip(results, parsed, strict=True)]
    shared = sorted({m for months in own for m in months})

    runs: list[ImportRun] = []
    for (table, reader), profile, result, months in zip(parsed, profiles, results, own, strict=True):
        run, created = staging.stage(
            uow.tx,
            business_id=business_id,
            user_id=uow.principal.user_id,
            table=table,
            profile=profile,
            upload_id=upload_id,
            gstin=own_gstin,
            classify=_classifier(reader, _context(uow, reader, today)),
            flag_live_overlap=True,
            result=result,
            months=months or shared,
        )
        log.info("upload %s staged run %s (created=%s)", upload_id, run.id, created)
        runs.append(run)
    return runs


def _same_sheet(a: str | None, b: str | None) -> bool:
    return a is not None and b is not None and a.strip().lower() == b.strip().lower()


def _sheet_ok(reader: Reader, table) -> bool:
    wanted = getattr(reader, "sheet", None)
    # `any_sheet`: the reader's sheet name picks its sheet out of a workbook with several, but a CSV or a
    # workbook with one (renamed) sheet is still its file if the headers match.
    return wanted is None or _same_sheet(wanted, table.sheet) or bool(getattr(reader, "any_sheet", False))


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
                return [t for t in tables if t.rows] or tables  # a sheet with nothing at all is not a layout
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


def _context(uow, reader: Reader, today) -> dict | None:
    """What a reader that names `refdata_keys` is given to decide a hold: the state list (codes and names,
    case-folded) and each key's value on `today`. None for a reader that needs nothing."""
    keys = getattr(reader, "refdata_keys", None)
    if keys is None:
        return None
    states = {part.casefold() for code, name in state_codes(uow.tx, today) for part in (code, " ".join(name.split()))}
    return {"states": states, **{key: value_on(uow.tx, key, today) for key in keys}}


def _classifier(reader: Reader, context: dict | None = None):
    def classify(parsed):
        verdict = reader.classify(parsed) if context is None else reader.classify(parsed, context)
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
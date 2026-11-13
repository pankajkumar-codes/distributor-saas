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
from .parsing import FileRejected, open_zip, read_table
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
        try:
            table = read_table(data, name)
        except FileRejected:
            raise Refused("unreadable_file") from None
        matches = [r for r in readers if r.detect(table)]
        if not matches:
            raise Refused("unknown_layout")
        if len(matches) > 1:
            raise Refused("needs_choice")  # the choose endpoint arrives with a second reader of one layout
        parsed.append((table, matches[0]))

    runs: list[ImportRun] = []
    for table, reader in parsed:
        file_gstin = reader.gstin(table)
        if not file_gstin:
            raise Refused("gstin_missing")
        if own_gstin is None or file_gstin.strip().upper() != own_gstin:
            raise Refused("wrong_gstin")
        run, created = staging.stage(
            uow.tx,
            business_id=business_id,
            user_id=uow.principal.user_id,
            table=table,
            profile=_profile(uow, reader, today),
            upload_id=upload_id,
            gstin=own_gstin,
            classify=_classifier(reader),
        )
        log.info("upload %s staged run %s (created=%s)", upload_id, run.id, created)
        runs.append(run)
    return runs


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
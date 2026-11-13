"""Uploads (LLD-7 §2.1, §3; R1-M3): a file goes to the object store on a presigned POST,
`complete` checks it arrived, and the parse job reads it.

An upload belongs to a section (a platform, or the user's own invoices) and holds no cell
values. This slice stops before staging: a section with no registered reader rejects the
file with a plain message, and a PDF for the own-invoice section is stored and marked read
with no rows (reading it is R1-M6). Staging, held rows and the preview come next.

Every query filters `business_id` explicitly as well as relying on row-level security. The
caller runs inside a business unit of work, whose route has checked the permission.
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import text

from app.modules.refdata import value_on
from platform_common import audit, storage
from platform_common.errors import Conflict, Deny, Invalid
from platform_common.ids import uuid7
from platform_common.uow import UnitOfWork

from .readers import SECTIONS

MAX_FILE_NAME = 255
CONTENT_TYPES = {
    ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".zip": "application/zip",
    ".pdf": "application/pdf",
}
# Which extensions each section takes. Platform reports may come zipped (Amazon, Meesho);
# the own-invoice Excel sheet and the PDF invoices may not.
ALLOWED = {
    "amazon": (".csv", ".xlsx", ".zip"),
    "flipkart": (".csv", ".xlsx", ".zip"),
    "meesho": (".csv", ".xlsx", ".zip"),
    "own_invoices_excel": (".csv", ".xlsx"),
    "own_invoices_pdf": (".pdf",),
}
# Plain words for each way a file can be turned away, shown beside the upload.
REJECT_MESSAGES = {
    "no_reader": "We can't read this kind of report yet.",
    "not_a_pdf": "This file isn't a PDF.",
    "upload_changed": "The file in storage isn't the one you chose. Upload it again.",
    "not_allowed": "Whoever started this upload can no longer upload files.",
}
PDF_MAGIC = b"%PDF-"


@dataclass(frozen=True)
class Upload:
    id: uuid.UUID
    section: str
    s3_key: str
    file_name: str
    size_bytes: int
    status: str
    reject_reason: str | None
    checksum_sha256: str | None
    run_id: uuid.UUID | None
    raw_deleted_at: datetime | None
    created_at: datetime

    @property
    def reject_message(self) -> str | None:
        return None if self.reject_reason is None else REJECT_MESSAGES.get(self.reject_reason, "We couldn't read this file.")


_COLUMNS = ("id, section, s3_key, file_name, size_bytes, status, reject_reason, checksum_sha256, run_id,"
            " raw_deleted_at, created_at")


def _business(uow: UnitOfWork) -> uuid.UUID:
    return uow.principal.business_id


def content_type_for(file_name: str) -> str:
    dot = file_name.rfind(".")
    return CONTENT_TYPES[file_name[dot:].lower()]


def get(uow: UnitOfWork, upload_id: uuid.UUID, *, lock: bool = False) -> Upload:
    row = uow.tx.execute(
        text(f"select {_COLUMNS} from imports.uploads where id = :u and business_id = :b" + (" for update" if lock else "")),
        {"u": upload_id, "b": _business(uow)},
    ).one_or_none()
    if row is None:
        raise Deny("not_found")  # unknown, or another business's upload
    return Upload(*row)


def list_uploads(uow: UnitOfWork, section: str | None, limit: int, offset: int) -> tuple[list[Upload], bool]:
    if section is not None and section not in SECTIONS:
        raise Invalid("unknown_section", "That isn't an upload section.", field="section")
    rows = uow.tx.execute(
        text(f"select {_COLUMNS} from imports.uploads where business_id = :b and (cast(:s as text) is null or section = :s)"
             " order by created_at desc, id desc limit :n offset :o"),
        {"b": _business(uow), "s": section, "n": limit + 1, "o": offset},
    ).all()
    return [Upload(*r) for r in rows[:limit]], len(rows) > limit


def start(uow: UnitOfWork, section: str, file_name: str, size_bytes: int, today: date) -> Upload:
    """A `pending` upload and the exact key its file must be posted to."""
    if section not in SECTIONS:
        raise Invalid("unknown_section", "That isn't an upload section.", field="section")
    name = (file_name or "").strip()
    if not name or len(name) > MAX_FILE_NAME or not name.isprintable():
        raise Invalid("file_name_invalid", "Give the file's name", field="file_name")
    dot = name.rfind(".")
    ext = name[dot:].lower() if dot >= 0 else ""
    if ext not in ALLOWED[section]:
        wanted = ", ".join(ALLOWED[section])
        raise Invalid("file_type_not_allowed", f"This section takes {wanted} files", field="file_name")
    most = int(value_on(uow.tx, "imports.max_file_bytes", today))
    if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or not 0 < size_bytes <= most:
        raise Invalid("file_too_large", f"The file can be at most {most // (1024 * 1024)} MB", field="size_bytes")
    upload_id = uuid7()
    uow.tx.execute(
        text("insert into imports.uploads (id, business_id, section, s3_key, file_name, size_bytes, created_by)"
             " values (:i, :b, :s, :k, :n, :z, :me)"),
        {"i": upload_id, "b": _business(uow), "s": section, "k": storage.key_for(_business(uow), "uploads", upload_id),
         "n": name, "z": size_bytes, "me": uow.principal.user_id},
    )
    return get(uow, upload_id)


def received(uow: UnitOfWork, upload_id: uuid.UUID, today: date) -> Upload:
    """The complete route: the store is asked, never the client. Calling it again after the
    upload moved on returns it unchanged, so the route returns the same job."""
    up = get(uow, upload_id, lock=True)
    if up.status in ("rejected", "expired"):
        raise Conflict("upload_closed", "This upload was closed. Upload the file again")
    if up.status != "pending":
        return up
    info = storage.get_store().head(_business(uow), storage.check_key(_business(uow), up.s3_key))
    if info is None:
        raise Conflict("upload_not_received", "The file hasn't finished uploading. Upload it again")
    most = int(value_on(uow.tx, "imports.max_file_bytes", today))
    if not 0 < info.size <= most:
        raise Invalid("file_too_large", f"The file can be at most {most // (1024 * 1024)} MB", field="size_bytes")
    if info.size != up.size_bytes:
        raise Conflict("upload_size_mismatch", "The uploaded file isn't the one you chose. Upload it again")
    _set(uow, upload_id, status="received")
    audit.record(uow, "imports.upload_received", "upload", upload_id, data={"section": up.section, "upload_id": str(upload_id)})
    return get(uow, upload_id)


def _set(uow: UnitOfWork, upload_id: uuid.UUID, **cols) -> None:
    sets = ", ".join(f"{k} = :{k}" for k in cols)
    uow.tx.execute(
        text(f"update imports.uploads set {sets}, updated_at = now() where id = :u and business_id = :b"),
        {**cols, "u": upload_id, "b": _business(uow)},
    )


def reject(uow: UnitOfWork, upload_id: uuid.UUID, reason: str) -> None:
    section = get(uow, upload_id).section
    _set(uow, upload_id, status="rejected", reject_reason=reason)
    audit.record(uow, "imports.rejected", "upload", upload_id,
                 data={"section": section, "upload_id": str(upload_id), "reason": reason})


def read_object(uow: UnitOfWork, up: Upload) -> bytes:
    """For the parse job: the uploaded bytes, from this business's key only."""
    return storage.get_store().get_bytes(_business(uow), storage.check_key(_business(uow), up.s3_key))


def process(uow: UnitOfWork, upload_id: uuid.UUID) -> Upload:
    """The parse job's body. Moves a received upload to parsed or rejected, in the job's
    transaction, so a crash leaves it received and the retry starts again."""
    from .readers import readers_for

    up = get(uow, upload_id, lock=True)
    if up.status in ("parsed", "rejected", "expired"):
        return up  # a redelivery
    content = read_object(uow, up)
    if len(content) != up.size_bytes:
        reject(uow, upload_id, "upload_changed")
        return get(uow, upload_id)
    sha = hashlib.sha256(content).hexdigest()
    _set(uow, upload_id, checksum_sha256=sha)
    if up.section == "own_invoices_pdf":
        # Stored for later: reading a PDF invoice is R1-M6. No rows, no run.
        if not content.startswith(PDF_MAGIC):
            reject(uow, upload_id, "not_a_pdf")
        else:
            _set(uow, upload_id, status="parsed")
        return get(uow, upload_id)
    if not readers_for(up.section):
        reject(uow, upload_id, "no_reader")
        return get(uow, upload_id)
    # A reader exists: the next slice stages its rows here.
    raise NotImplementedError("staging an upload through a reader comes in the next slice")

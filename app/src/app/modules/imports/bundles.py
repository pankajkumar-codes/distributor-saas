"""Bundle upload, slice 2 (bundle-upload-plan): the stored side of `bundle.py`.

A bundle is one ZIP of mixed report files. The zip goes to the object store on a presigned POST, like any upload. A job
opens it (`bundle.open_bundle`) and sorts each file by its content (`bundle.classify`), and records what it found; no
rows are read and no file contents are kept in the database or the logs. The user then sees the list, may move a file to
another section or drop it (each choice is a new row, nothing is edited), and asks to stage. A second job writes one
ordinary upload per file that is going to be read and queues the usual parse job for it, so dedup, held rows, review and
confirm stay exactly as they are for a single upload.

The two jobs run on the worker Lambda (1024 MB, 900 s). Peak memory is about the zip, plus everything it inflates to
(capped at `imports.bundle.max_total_bytes`, 100 MB, shared by every level), plus one file being copied out; it is not
proportional to row counts, because classification reads only each table's header rows.

Every query filters `business_id` explicitly as well as relying on row-level security.
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import text

from app.modules.business.interface import channels
from app.modules.refdata import value_on
from platform_common import audit, jobs, storage
from platform_common.errors import Conflict, Deny, Invalid
from platform_common.ids import uuid7
from platform_common.uow import UnitOfWork

from . import bundle as engine
from . import uploads
from .readers import SECTIONS

MAX_NAME = uploads.MAX_FILE_NAME
PARSE_JOB = "imports.parse"  # the single-upload parse job (`jobs.PARSE`); named here so this module need not import it
# Why a file cannot be moved to a section: there is nothing readable in it to move.
IMMOVABLE = ("empty", "too_large", "system_file", "old_excel", "not_a_report", "utf16", "unreadable")
BUNDLE_REJECTS = {
    **engine.REFUSALS,
    "upload_changed": "The file in storage isn't the one you chose. Upload it again.",
    "read_failed": "We couldn't read this zip. Try uploading it again, or contact support.",
    "bundle_changed": "The zip can't be opened the same way twice. Upload it again.",
    "not_allowed": "Whoever started this upload can no longer upload files.",
}
PDF_NOTE = "Will be read as your invoices. Any we can't read clearly are held for you to look at."


@dataclass(frozen=True)
class Bundle:
    id: uuid.UUID
    s3_key: str
    file_name: str
    size_bytes: int
    status: str
    reject_reason: str | None
    checksum_sha256: str | None
    created_at: datetime

    @property
    def reject_message(self) -> str | None:
        if self.reject_reason is None:
            return None
        return BUNDLE_REJECTS.get(self.reject_reason, "We couldn't read this zip.")


@dataclass(frozen=True)
class FileView:
    n: int
    file_name: str
    size_bytes: int
    found_section: str | None  # what the content said; None when no section took it
    section: str | None  # where it goes now (the user's choice, else what was found)
    state: str  # used | not_used | not_selected | dropped
    moved: bool
    reason_code: str | None
    reason: str | None
    note: str | None
    upload_id: uuid.UUID | None  # once staged


_COLUMNS = "id, s3_key, file_name, size_bytes, status, reject_reason, checksum_sha256, created_at"


def _business(uow: UnitOfWork) -> uuid.UUID:
    return uow.principal.business_id


def get(uow: UnitOfWork, bundle_id: uuid.UUID, *, lock: bool = False) -> Bundle:
    row = uow.tx.execute(
        text(f"select {_COLUMNS} from imports.bundles where id = :i and business_id = :b" + (" for update" if lock else "")),
        {"i": bundle_id, "b": _business(uow)},
    ).one_or_none()
    if row is None:
        raise Deny("not_found")  # unknown, or another business's bundle
    return Bundle(*row)


def _set(uow: UnitOfWork, bundle_id: uuid.UUID, **cols) -> None:
    sets = ", ".join(f"{k} = :{k}" for k in cols)
    uow.tx.execute(
        text(f"update imports.bundles set {sets}, updated_at = now() where id = :i and business_id = :b"),
        {**cols, "i": bundle_id, "b": _business(uow)},
    )


def _reject(uow: UnitOfWork, bundle_id: uuid.UUID, reason: str) -> None:
    _set(uow, bundle_id, status="rejected", reject_reason=reason)
    audit.record(uow, "imports.bundle_rejected", "bundle", bundle_id, data={"bundle_id": str(bundle_id), "reason": reason})


def selected_sections(uow: UnitOfWork) -> frozenset[str] | None:
    """The sections the business chose at setup, or None when it has not answered (then nothing is left out)."""
    c = channels(uow.tx)
    if not c.answered:
        return None
    out = {m for m in ("amazon", "flipkart", "meesho") if getattr(c, m)}
    if c.own_invoices:
        out |= {"own_invoices_excel", "own_invoices_pdf"}
    return frozenset(out)


def selectable(uow: UnitOfWork) -> list[str]:
    chosen = selected_sections(uow)
    return [s for s in SECTIONS if chosen is None or s in chosen]


def start(uow: UnitOfWork, file_name: str, size_bytes: int, today: date) -> Bundle:
    """A `pending` bundle and the exact key its zip must be posted to."""
    name = (file_name or "").strip()
    if not name or len(name) > MAX_NAME or not name.isprintable():
        raise Invalid("file_name_invalid", "Give the file's name", field="file_name")
    if not name.lower().endswith(".zip"):
        raise Invalid("file_type_not_allowed", "A bundle is a .zip file", field="file_name")
    most = int(value_on(uow.tx, "imports.bundle.max_total_bytes", today))
    if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or not 0 < size_bytes <= most:
        raise Invalid("file_too_large", f"The zip can be at most {most // (1024 * 1024)} MB", field="size_bytes")
    bundle_id = uuid7()
    # the zip lives in the uploads area, so it expires like any raw file
    uow.tx.execute(
        text("insert into imports.bundles (id, business_id, s3_key, file_name, size_bytes, created_by)"
             " values (:i, :b, :k, :n, :z, :me)"),
        {"i": bundle_id, "b": _business(uow), "k": storage.key_for(_business(uow), "uploads", bundle_id),
         "n": name, "z": size_bytes, "me": uow.principal.user_id},
    )
    return get(uow, bundle_id)


def received(uow: UnitOfWork, bundle_id: uuid.UUID, today: date) -> Bundle:
    """The complete route: the store is asked, never the client. Calling it again after it moved on changes nothing."""
    b = get(uow, bundle_id, lock=True)
    if b.status in ("rejected", "expired"):
        raise Conflict("upload_closed", "This upload was closed. Upload the file again")
    if b.status != "pending":
        return b
    info = storage.get_store().head(_business(uow), storage.check_key(_business(uow), b.s3_key))
    if info is None:
        raise Conflict("upload_not_received", "The file hasn't finished uploading. Upload it again")
    most = int(value_on(uow.tx, "imports.bundle.max_total_bytes", today))
    if not 0 < info.size <= most:
        raise Invalid("file_too_large", f"The zip can be at most {most // (1024 * 1024)} MB", field="size_bytes")
    if info.size != b.size_bytes:
        raise Conflict("upload_size_mismatch", "The uploaded file isn't the one you chose. Upload it again")
    _set(uow, bundle_id, status="received")
    audit.record(uow, "imports.bundle_upload", "bundle", bundle_id, data={"bundle_id": str(bundle_id)})
    return get(uow, bundle_id)


def _clip(name: str) -> str:
    """A name that fits the column, keeping the extension (a folder's name in front can make one long)."""
    if len(name) <= MAX_NAME:
        return name
    dot = name.rfind(".")
    ext = name[dot:] if 0 <= dot and len(name) - dot <= 10 else ""
    return name[: MAX_NAME - len(ext)] + ext


def _bytes(uow: UnitOfWork, b: Bundle) -> bytes:
    return storage.get_store().get_bytes(_business(uow), storage.check_key(_business(uow), b.s3_key))


def process(uow: UnitOfWork, bundle_id: uuid.UUID, today: date) -> Bundle:
    """The classify job's body: `received` to `classified` (or `rejected`), in the job's transaction, so a crash leaves
    it received and the retry starts again. Records counts in the audit log, never a name or a cell."""
    b = get(uow, bundle_id, lock=True)
    if b.status != "received":
        return b  # a redelivery, or nothing to do
    content = _bytes(uow, b)
    if len(content) != b.size_bytes:
        _reject(uow, bundle_id, "upload_changed")
        return get(uow, bundle_id)
    _set(uow, bundle_id, checksum_sha256=hashlib.sha256(content).hexdigest())
    try:
        files = engine.open_bundle(content, engine.limits_on(uow.tx, today))
    except engine.BundleRefused as refused:
        _reject(uow, bundle_id, refused.code)
        return get(uow, bundle_id)
    outcomes = engine.classify(files, selected=selected_sections(uow))
    uow.tx.execute(
        text("insert into imports.bundle_files (bundle_id, business_id, n, file_name, size_bytes, section, state, reason_code)"
             " values (:i, :b, :n, :name, :size, :section, :state, :code)"),
        [{"i": bundle_id, "b": _business(uow), "n": o.n, "name": _clip(o.name), "size": o.size, "section": o.section,
          "state": o.state, "code": o.reason_code} for o in outcomes],
    )
    _set(uow, bundle_id, status="classified")
    counts = {s: sum(1 for o in outcomes if o.state == s) for s in ("used", "not_used", "not_selected")}
    audit.record(uow, "imports.bundle_classified", "bundle", bundle_id,
                 data={"bundle_id": str(bundle_id), "files": len(outcomes), **counts})
    return get(uow, bundle_id)


def files(uow: UnitOfWork, bundle_id: uuid.UUID) -> list[FileView]:
    """Every file with where it goes now: what the content said, unless the user chose otherwise."""
    rows = uow.tx.execute(
        text("select f.n, f.file_name, f.size_bytes, f.section, f.state, f.reason_code, c.id is not null as chosen,"
             "   c.section as chosen_section, bu.upload_id"
             " from imports.bundle_files f"
             " left join lateral (select id, section from imports.bundle_choices c"
             "    where c.bundle_id = f.bundle_id and c.n = f.n and c.business_id = f.business_id"
             "    order by created_at desc, id desc limit 1) c on true"
             " left join imports.bundle_uploads bu on bu.bundle_id = f.bundle_id and bu.n = f.n and bu.business_id = f.business_id"
             " where f.bundle_id = :i and f.business_id = :b order by f.n"),
        {"i": bundle_id, "b": _business(uow)},
    ).all()
    out = []
    for r in rows:
        if r.chosen and r.chosen_section is None:
            state, section, code = "dropped", None, None
        elif r.chosen:
            state, section, code = "used", r.chosen_section, None
        else:
            state, section, code = r.state, r.section, r.reason_code
        reason = engine.REASONS.get(code) if code else None
        out.append(FileView(
            n=r.n, file_name=r.file_name, size_bytes=r.size_bytes, found_section=r.section, section=section,
            state=state, moved=bool(r.chosen), reason_code=code, reason=reason,
            note=PDF_NOTE if state == "used" and section == "own_invoices_pdf" else None, upload_id=r.upload_id,
        ))
    return out


def choose(uow: UnitOfWork, bundle_id: uuid.UUID, n: int, section: str | None) -> list[FileView]:
    """Move one file to a section, or drop it (None). A new row each time; the latest wins."""
    b = get(uow, bundle_id, lock=True)
    if b.status != "classified":
        raise Conflict("bundle_not_open", "This bundle can't be changed now.")
    view = next((f for f in files(uow, bundle_id) if f.n == n), None)
    if view is None:
        raise Deny("not_found")
    if section is not None:
        if section not in SECTIONS:
            raise Invalid("unknown_section", "That isn't an upload section.", field="section")
        if view.reason_code in IMMOVABLE:
            raise Invalid("file_cannot_be_moved", "There is nothing in this file we can read.", field="section")
        if section not in selectable(uow):
            raise Invalid("section_not_selected", "That report is not selected for your business.", field="section")
        name = view.file_name.lower()
        if not name.endswith(uploads.ALLOWED[section]):
            wanted = ", ".join(uploads.ALLOWED[section])
            raise Invalid("file_type_not_allowed", f"That section takes {wanted} files", field="section")
    uow.tx.execute(
        text("insert into imports.bundle_choices (id, bundle_id, business_id, n, section, chosen_by)"
             " values (:id, :i, :b, :n, :s, :me)"),
        {"id": uuid7(), "i": bundle_id, "b": _business(uow), "n": n, "s": section, "me": uow.principal.user_id},
    )
    return files(uow, bundle_id)


def to_stage(views: list[FileView]) -> list[FileView]:
    return [f for f in views if f.state == "used" and f.upload_id is None]


def request_stage(uow: UnitOfWork, bundle_id: uuid.UUID) -> Bundle:
    """The stage route: `classified` to `staging`. Asking again while staging or staged changes nothing."""
    b = get(uow, bundle_id, lock=True)
    if b.status in ("staging", "staged"):
        return b
    if b.status != "classified":
        raise Conflict("bundle_not_open", "This bundle can't be staged now.")
    if not to_stage(files(uow, bundle_id)):
        raise Invalid("nothing_to_stage", "No file in this bundle is going to be read.")
    _set(uow, bundle_id, status="staging")
    return get(uow, bundle_id)


def stage(uow: UnitOfWork, bundle_id: uuid.UUID, today: date) -> Bundle:
    """The stage job's body: one ordinary upload per file that is going to be read, each with its own parse job.
    The zip is opened again, and a file must be the one that was listed (same name and size) or the bundle is refused."""
    b = get(uow, bundle_id, lock=True)
    if b.status != "staging":
        return b
    views = to_stage(files(uow, bundle_id))
    content = _bytes(uow, b)
    if hashlib.sha256(content).hexdigest() != b.checksum_sha256:
        _reject(uow, bundle_id, "bundle_changed")  # not the zip that was listed
        return get(uow, bundle_id)
    opened = {f.n: f for f in engine.open_bundle(content, engine.limits_on(uow.tx, today))}
    store = storage.get_store()
    business = _business(uow)
    for v in views:
        f = opened.get(v.n)
        if f is None or _clip(f.name) != v.file_name or f.size != v.size_bytes or not f.data:
            _reject(uow, bundle_id, "bundle_changed")
            return get(uow, bundle_id)
        upload_id = uuid7()
        key = storage.key_for(business, "uploads", upload_id)
        store.put(business, key, f.data, uploads.content_type_for(v.file_name))
        uow.tx.execute(
            text("insert into imports.uploads (id, business_id, section, s3_key, file_name, size_bytes, status,"
                 " checksum_sha256, created_by) values (:i, :b, :s, :k, :n, :z, 'received', :h, :me)"),
            {"i": upload_id, "b": business, "s": v.section, "k": key, "n": v.file_name, "z": f.size,
             "h": hashlib.sha256(f.data).hexdigest(), "me": uow.principal.user_id},
        )
        uow.tx.execute(
            text("insert into imports.bundle_uploads (bundle_id, business_id, n, upload_id) values (:i, :b, :n, :u)"),
            {"i": bundle_id, "b": business, "n": v.n, "u": upload_id},
        )
        audit.record(uow, "imports.upload_received", "upload", upload_id,
                     data={"section": v.section, "upload_id": str(upload_id)})
        jobs.create(uow, PARSE_JOB, natural_key=str(upload_id))
    _set(uow, bundle_id, status="staged")
    audit.record(uow, "imports.bundle_staged", "bundle", bundle_id, data={"bundle_id": str(bundle_id), "uploads": len(views)})
    return get(uow, bundle_id)

"""Purchase invoices (R2-M2): upload, reading, and the business's review before anything is confirmed.

A business uploads a supplier's invoice, as a PDF or as a photo of a paper bill. A PDF with a text layer is read in the
sandbox by the same reader as the own-invoice PDFs; a photo, or a scan, is stored and gets one blank draft, because no
reader for pictures is switched on (Bedrock is off, the OCR reader runs only locally and in CI). Whatever was read, or
left blank, is shown to the business on a review screen. The business confirms with the values it checked, or discards.
Nothing here reaches the catalog or stock: a confirmed purchase is the input to R2-M3.

Drafts and reviews are insert-only. Every confirmed line points back to the draft line it came from (none when the
business typed it in) and every draft to the file and its pages, so a value can be traced to the paper. Values read and
values typed never reach a log or an audit row from here; only ids, counts and field names do.
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import re

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.modules.catalog.interface import (ConfirmedPurchaseLine, NewCatalogItem, product_for_line,
                                           receive_confirmed_purchase_line)
from app.modules.business.interface import check_gstin, fy_of, gstin_message
from app.modules.refdata import value_on
from platform_common import audit, storage
from platform_common.clock import get_clock
from platform_common.errors import Conflict, Deny, Invalid
from platform_common.ids import uuid7
from platform_common.uow import UnitOfWork

from .pdf import PdfRefused
from .pdf.sandbox import read_sandboxed
from .reading import MB, PDF_REJECTS, pdf_limits

MAX_FILE_NAME = 255
PDF_MAGIC = b"%PDF-"
HEIC_BRAND_AT = len(b"\x00\x00\x00\x00")  # an ISO-media file names its brand right after the 4-byte box size
EXTENSIONS = {
    ".pdf": ("pdf", "application/pdf"),
    ".jpg": ("image", "image/jpeg"),
    ".jpeg": ("image", "image/jpeg"),
    ".png": ("image", "image/png"),
    ".heic": ("image", "image/heic"),
}
REJECT_MESSAGES = {
    "not_a_pdf": "This file isn't a PDF.",
    "not_an_image": "This file isn't a photo we can keep. Use a JPG, PNG or HEIC picture.",
    "already_uploaded": "You have already uploaded this exact file.",
    "pdf_encrypted": "This PDF is password protected. Save an unprotected copy and upload it again.",
    "pdf_ambiguous": "We couldn't tell where one invoice ends and the next begins. Upload each invoice as its own PDF.",
    "pdf_too_big": "This PDF has more pages or invoices than we can read at once. Split it and upload the parts.",
    "pdf_too_complex": "This PDF is too complex for us to read here. Upload it as a photo, or type the lines.",
    "upload_changed": "The file in storage isn't the one you chose. Upload it again.",
    "read_failed": "We couldn't read this file. Try uploading it again, or contact support.",
    "not_allowed": "Whoever started this upload can no longer upload files.",
}
DOC_FIELDS = ("seller_gstin", "doc_number", "doc_date", "invoice_total")  # what a draft must show, read or not
_FIELD_NAME = {"seller_gstin": "supplier_gstin"}


@dataclass(frozen=True)
class PurchaseFile:
    id: uuid.UUID
    file_name: str
    size_bytes: int
    kind: str
    status: str
    reject_reason: str | None
    s3_key: str
    created_at: datetime

    @property
    def reject_message(self) -> str | None:
        return None if self.reject_reason is None else REJECT_MESSAGES.get(self.reject_reason, "We couldn't read this file.")


@dataclass(frozen=True)
class DraftLine:
    id: uuid.UUID
    line_no: int
    page: int
    hsn: str | None
    quantity: str | None
    unit: str | None
    taxable_value: str | None
    gst_rate: str | None
    igst: str | None
    cgst: str | None
    sgst: str | None
    cess: str | None
    unclear: list[str]


@dataclass(frozen=True)
class Draft:
    id: uuid.UUID
    file_id: uuid.UUID
    file_name: str
    ordinal: int
    reader_id: str
    pages: list[int]
    doc_type: str | None
    supplier_gstin: str | None
    doc_number: str | None
    doc_date: str | None
    invoice_total: str | None
    unclear: list[str]
    lines: list[DraftLine]
    decision: str | None  # None until the business has confirmed or discarded it


@dataclass(frozen=True)
class ItemIn:
    """What the business says about a new catalog item; the name and HSN are the line's own."""

    code: str
    uqc: str
    tax_category: str
    gst_rate: str | None = None
    rate_valid_from: date | None = None
    has_cess: bool = False


@dataclass(frozen=True)
class LineIn:
    """A line as the business confirms it. `draft_line_id` is None for a line it typed in."""

    draft_line_id: uuid.UUID | None
    product_id: uuid.UUID | None  # an existing catalog product, or None with `new_item`
    new_item: ItemIn | None  # a product to create from this line; exactly one of the two
    product_name: str
    hsn: str
    quantity: Decimal
    unit: str | None
    taxable_value: Decimal
    gst_rate: Decimal
    igst: Decimal = Decimal()
    cgst: Decimal = Decimal()
    sgst: Decimal = Decimal()
    cess: Decimal = Decimal()


@dataclass(frozen=True)
class Confirmed:
    review_id: uuid.UUID
    draft_id: uuid.UUID
    supplier_gstin: str
    supplier_name: str | None
    doc_number: str
    doc_date: date
    invoice_total: Decimal | None
    line_count: int
    created_at: datetime
    received: tuple = ()  # per line: (line_no, product_id, created_product, price_needed), set at confirm
    warnings: tuple = ()  # (line_no, code): things worth a second look that never block the confirm


def _business(uow: UnitOfWork) -> uuid.UUID:
    return uow.principal.business_id


_FILE_COLUMNS = "id, file_name, size_bytes, kind, status, reject_reason, s3_key, created_at"


def get_file(uow: UnitOfWork, file_id: uuid.UUID, *, lock: bool = False) -> PurchaseFile:
    row = uow.tx.execute(
        text(f"select {_FILE_COLUMNS} from imports.purchase_files where id = :f and business_id = :b"
             + (" for update" if lock else "")), {"f": file_id, "b": _business(uow)}).one_or_none()
    if row is None:
        raise Deny("not_found")  # unknown, or another business's file
    return PurchaseFile(*row)


def list_files(uow: UnitOfWork, limit: int, offset: int) -> tuple[list[PurchaseFile], bool]:
    rows = uow.tx.execute(
        text(f"select {_FILE_COLUMNS} from imports.purchase_files where business_id = :b"
             " order by created_at desc, id desc limit :n offset :o"),
        {"b": _business(uow), "n": limit + 1, "o": offset}).all()
    return [PurchaseFile(*r) for r in rows[:limit]], len(rows) > limit


def content_type_for(file_name: str) -> str:
    return EXTENSIONS[file_name[file_name.rfind("."):].lower()][1]


def start(uow: UnitOfWork, file_name: str, size_bytes: int, today: date) -> PurchaseFile:
    """A `pending` file and the exact key it must be posted to."""
    name = (file_name or "").strip()
    if not name or len(name) > MAX_FILE_NAME or not name.isprintable():
        raise Invalid("file_name_invalid", "Give the file's name", field="file_name")
    ext = name[name.rfind("."):].lower() if "." in name else ""
    if ext not in EXTENSIONS:
        raise Invalid("file_type_not_allowed", "Upload a PDF, or a JPG, PNG or HEIC photo", field="file_name")
    most = int(value_on(uow.tx, "imports.max_file_bytes", today))
    if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or not 0 < size_bytes <= most:
        raise Invalid("file_too_large", f"The file can be at most {most // MB} MB", field="size_bytes")
    file_id = uuid7()
    uow.tx.execute(
        text("insert into imports.purchase_files (id, business_id, s3_key, file_name, size_bytes, kind, created_by)"
             " values (:i, :b, :k, :n, :z, :kind, :me)"),
        {"i": file_id, "b": _business(uow), "k": storage.key_for(_business(uow), "uploads", file_id), "n": name,
         "z": size_bytes, "kind": EXTENSIONS[ext][0], "me": uow.principal.user_id})
    return get_file(uow, file_id)


def received(uow: UnitOfWork, file_id: uuid.UUID, today: date) -> PurchaseFile:
    """The complete route: the store is asked, never the client. Calling it again returns the file unchanged."""
    f = get_file(uow, file_id, lock=True)
    if f.status == "rejected":
        raise Conflict("upload_closed", "This upload was closed. Upload the file again")
    if f.status != "pending":
        return f
    info = storage.get_store().head(_business(uow), storage.check_key(_business(uow), f.s3_key))
    if info is None:
        raise Conflict("upload_not_received", "The file hasn't finished uploading. Upload it again")
    most = int(value_on(uow.tx, "imports.max_file_bytes", today))
    if not 0 < info.size <= most:
        raise Invalid("file_too_large", f"The file can be at most {most // MB} MB", field="size_bytes")
    if info.size != f.size_bytes:
        raise Conflict("upload_size_mismatch", "The uploaded file isn't the one you chose. Upload it again")
    _set(uow, file_id, status="received")
    audit.record(uow, "imports.purchase_file_received", "purchase_file", file_id, data={"file_id": str(file_id)})
    return get_file(uow, file_id)


def _set(uow: UnitOfWork, file_id: uuid.UUID, **cols) -> None:
    sets = ", ".join(f"{k} = :{k}" for k in cols)
    uow.tx.execute(text(f"update imports.purchase_files set {sets}, updated_at = now() where id = :f and business_id = :b"),
                   {**cols, "f": file_id, "b": _business(uow)})


def reject(uow: UnitOfWork, file_id: uuid.UUID, reason: str) -> None:
    _set(uow, file_id, status="rejected", reject_reason=reason)
    audit.record(uow, "imports.purchase_file_rejected", "purchase_file", file_id,
                 data={"file_id": str(file_id), "reason": reason})


def _is_image(content: bytes) -> bool:
    return content.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")) or content.startswith(b"ftyp", HEIC_BRAND_AT)


def process(uow: UnitOfWork, file_id: uuid.UUID) -> PurchaseFile:
    """The parse job's body: from a received file to its drafts, in the job's transaction, so a crash leaves it
    received and the retry starts again."""
    f = get_file(uow, file_id, lock=True)
    if f.status in ("read", "rejected"):
        return f  # a redelivery
    content = storage.get_store().get_bytes(_business(uow), storage.check_key(_business(uow), f.s3_key))
    if len(content) != f.size_bytes:
        reject(uow, file_id, "upload_changed")
        return get_file(uow, file_id)
    sha = hashlib.sha256(content).hexdigest()
    if f.kind == "pdf" and not content.startswith(PDF_MAGIC):
        reject(uow, file_id, "not_a_pdf")
        return get_file(uow, file_id)
    if f.kind == "image" and not _is_image(content):
        reject(uow, file_id, "not_an_image")
        return get_file(uow, file_id)
    if uow.tx.execute(text("select 1 from imports.purchase_files where business_id = :b and checksum_sha256 = :s"
                           " and status = 'read' and id <> :f"), {"b": _business(uow), "s": sha, "f": file_id}).first():
        reject(uow, file_id, "already_uploaded")
        return get_file(uow, file_id)
    today = get_clock().today()
    invoices = ()
    reader_id = "none"
    if f.kind == "pdf":
        invoices, reader_id = _read_pdf(uow, file_id, content, today)
    _set(uow, file_id, status="read", checksum_sha256=sha)
    if not invoices:
        _insert_draft(uow, file_id, 1, "none", pages=[1], doc_type=None, values={}, unclear=list(DOC_FIELDS), lines=())
    for n, inv in enumerate(invoices, 1):
        values = {name: getattr(inv, name) for name in DOC_FIELDS}
        _insert_draft(uow, file_id, n, reader_id, pages=list(inv.pages), doc_type=inv.doc_type, values=values,
                      unclear=sorted(inv.unclear & set(DOC_FIELDS)), lines=inv.lines)
    audit.record(uow, "imports.purchase_file_read", "purchase_file", file_id,
                 data={"file_id": str(file_id), "drafts": max(len(invoices), 1), "reader": reader_id})
    return get_file(uow, file_id)


def _read_pdf(uow: UnitOfWork, file_id: uuid.UUID, content: bytes, today):
    """The text-layer reader in the sandbox. A scan (a page with no text) or a PDF with no invoice in it is not
    refused: it becomes a blank draft the business fills in, because the file is the paper to check against."""
    tx = uow.tx
    try:
        result = read_sandboxed(content, pdf_limits(tx, today), value_on(tx, "hsn.pattern", today).pattern,
                                max_memory_bytes=int(value_on(tx, "imports.pdf.max_memory_mb", today)) * MB)
    except PdfRefused as refused:
        reject(uow, file_id, PDF_REJECTS.get(refused.code, "read_failed"))
        raise _Settled from None
    if result.unreadable_pages or not result.invoices:
        return (), "none"
    return result.invoices, "pdf_text_v1"


class _Settled(Exception):
    """The file was rejected inside `process`; the caller returns it as it stands."""


def process_or_settled(uow: UnitOfWork, file_id: uuid.UUID) -> PurchaseFile:
    try:
        return process(uow, file_id)
    except _Settled:
        return get_file(uow, file_id)


def _insert_draft(uow: UnitOfWork, file_id: uuid.UUID, ordinal: int, reader_id: str, *, pages: list[int],
                  doc_type: str | None, values: dict, unclear: list[str], lines) -> None:
    draft_id = uuid7()
    uow.tx.execute(
        text("insert into imports.purchase_drafts (id, business_id, file_id, ordinal, reader_id, pages, doc_type,"
             " supplier_gstin, doc_number, doc_date, invoice_total, unclear)"
             " values (:i, :b, :f, :o, :r, :pg, :dt, :g, :n, :d, :t, :u)"),
        {"i": draft_id, "b": _business(uow), "f": file_id, "o": ordinal, "r": reader_id, "pg": pages, "dt": doc_type,
         "g": values.get("seller_gstin"), "n": values.get("doc_number"), "d": values.get("doc_date"),
         "t": values.get("invoice_total"), "u": [_FIELD_NAME.get(x, x) for x in unclear]})
    for no, line in enumerate(lines, 1):
        uow.tx.execute(
            text("insert into imports.purchase_draft_lines (id, business_id, draft_id, line_no, page, hsn, quantity,"
                 " unit, taxable_value, gst_rate, igst, cgst, sgst, cess, unclear)"
                 " values (:i, :b, :d, :n, :pg, :hsn, :q, :un, :tv, :gr, :ig, :cg, :sg, :ce, :u)"),
            {"i": uuid7(), "b": _business(uow), "d": draft_id, "n": no, "pg": line.page, "hsn": line.hsn,
             "q": line.quantity, "un": line.unit, "tv": line.taxable_value, "gr": line.gst_rate, "ig": line.igst,
             "cg": line.cgst, "sg": line.sgst, "ce": line.cess, "u": sorted(line.unclear)})


_DRAFT_COLUMNS = ("d.id, d.file_id, f.file_name, d.ordinal, d.reader_id, d.pages, d.doc_type, d.supplier_gstin,"
                  " d.doc_number, d.doc_date, d.invoice_total, d.unclear,"
                  " (select r.decision from imports.purchase_reviews r where r.draft_id = d.id and r.business_id = d.business_id)"
                  " as decision")


def _draft(uow: UnitOfWork, row) -> Draft:
    lines = uow.tx.execute(
        text("select id, line_no, page, hsn, quantity, unit, taxable_value, gst_rate, igst, cgst, sgst, cess, unclear"
             " from imports.purchase_draft_lines where draft_id = :d and business_id = :b order by line_no"),
        {"d": row[0], "b": _business(uow)}).all()
    cols = dict(row._mapping)
    cols["unclear"] = list(cols["unclear"])
    return Draft(**cols, lines=[DraftLine(**{**r._mapping, "unclear": list(r.unclear)}) for r in lines])


def get_draft(uow: UnitOfWork, draft_id: uuid.UUID) -> Draft:
    row = uow.tx.execute(
        text(f"select {_DRAFT_COLUMNS} from imports.purchase_drafts d join imports.purchase_files f"
             " on f.id = d.file_id and f.business_id = d.business_id where d.id = :d and d.business_id = :b"),
        {"d": draft_id, "b": _business(uow)}).one_or_none()
    if row is None:
        raise Deny("not_found")
    return _draft(uow, row)


def list_drafts(uow: UnitOfWork, *, file_id: uuid.UUID | None, open_only: bool, limit: int, offset: int):
    rows = uow.tx.execute(
        text(f"select {_DRAFT_COLUMNS} from imports.purchase_drafts d join imports.purchase_files f"
             " on f.id = d.file_id and f.business_id = d.business_id where d.business_id = :b"
             " and (cast(:f as uuid) is null or d.file_id = :f)"
             " and (not :o or not exists (select 1 from imports.purchase_reviews r where r.draft_id = d.id"
             "                            and r.business_id = d.business_id))"
             " order by d.created_at desc, d.id desc limit :n offset :off"),
        {"b": _business(uow), "f": file_id, "o": open_only, "n": limit + 1, "off": offset}).all()
    return [_draft(uow, r) for r in rows[:limit]], len(rows) > limit


_PLAIN_AMOUNT = re.compile(r"^[0-9]+(\.[0-9]+)?$")


def to_decimal(value: str, field: str) -> Decimal:
    """An amount sent as text, exactly: plain digits with an optional point, no exponent, sign or spaces inside."""
    text_ = (value or "").strip()
    if not _PLAIN_AMOUNT.match(text_):  # ASCII digits only: no sign, exponent, spaces, NaN or look-alike digits like "²"
        raise Invalid("amount_invalid", "Enter the amount as plain digits, like 1250.50", field=field)
    out = Decimal(text_)
    return out


def _fold(number: str) -> str:
    return "".join(number.split()).upper()


def confirm(uow: UnitOfWork, draft_id: uuid.UUID, *, supplier_gstin: str, supplier_name: str | None, doc_number: str,
            doc_date: date, invoice_total: Decimal | None, lines: list[LineIn], today: date) -> Confirmed:
    """Records what the business checked. The values are validated here, whatever the screen did: the GSTIN and HSN
    patterns and the line cap are refdata; a tax column is never recomputed or "fixed", only checked for shape."""
    draft = get_draft(uow, draft_id)
    get_file(uow, draft.file_id, lock=True)  # serialises two confirms of one file's drafts (the drafts take no lock)
    if get_draft(uow, draft_id).decision is not None:
        raise Conflict("purchase_already_reviewed", "This invoice has already been confirmed or discarded")
    tx = uow.tx
    found = check_gstin(supplier_gstin or "", own=False)  # the shape and check character, never "registered"
    if not found.ok:
        raise Invalid("supplier_gstin_invalid", gstin_message(found.errors[0], supplier_gstin or ""),
                      field="supplier_gstin")
    supplier_gstin = found.normalised
    number = (doc_number or "").strip()
    if not number or len(number) > 40 or not number.isprintable():
        raise Invalid("doc_number_invalid", "Give the invoice number as printed", field="doc_number")
    if doc_date > today:
        raise Invalid("doc_date_in_future", "The invoice date can't be in the future", field="doc_date")
    name = (supplier_name or "").strip() or None
    if name is not None and (len(name) > 120 or not name.isprintable()):
        raise Invalid("supplier_name_invalid", "The supplier's name is too long", field="supplier_name")
    if invoice_total is not None and invoice_total < 0:
        raise Invalid("invoice_total_invalid", "The invoice total can't be negative", field="invoice_total")
    most = int(value_on(tx, "imports.purchase.max_lines", today))
    if not lines or len(lines) > most:
        raise Invalid("lines_invalid", f"An invoice needs between 1 and {most} lines", field="lines")
    own = {ln.id for ln in draft.lines}
    taken: set[uuid.UUID] = set()
    hsn_ok = value_on(tx, "hsn.pattern", today)
    max_rate = Decimal(value_on(tx, "imports.purchase.max_gst_rate", today))
    for i, ln in enumerate(lines):
        _check_line(ln, i, own, taken, hsn_ok, max_rate)
    key = _fold(number)
    fy = fy_of(doc_date)
    if _already_confirmed(tx, _business(uow), supplier_gstin, fy, key):
        raise Conflict("purchase_already_confirmed", "You have already confirmed this invoice from this supplier")
    warnings = _warnings(uow, lines, doc_date, tx)
    review_id = uuid7()
    try:
        with tx.begin_nested():  # two confirms of one invoice from different files can pass the check together
            tx.execute(
                text("insert into imports.purchase_reviews (id, business_id, draft_id, decision, supplier_gstin,"
                     " supplier_name, doc_number, doc_key, fy, doc_date, invoice_total, created_by)"
                     " values (:i, :b, :d, 'confirmed', :g, :sn, :n, :k, :fy, :dd, :t, :me)"),
                {"i": review_id, "b": _business(uow), "d": draft_id, "g": supplier_gstin, "sn": name, "n": number,
                 "k": key, "fy": fy, "dd": doc_date, "t": invoice_total, "me": uow.principal.user_id})
    except IntegrityError as exc:
        if "purchase_reviews_one_confirmed" not in str(exc.orig):
            raise
        raise Conflict("purchase_already_confirmed",
                       "You have already confirmed this invoice from this supplier") from exc
    received = []
    for no, ln in enumerate(lines, 1):
        line_id = uuid7()
        got = _receive(uow, review_id, line_id, ln, doc_date)
        received.append((no, got.product_id, got.created_product, got.price_needed))
        tx.execute(
            text("insert into imports.purchase_review_lines (id, business_id, review_id, line_no, draft_line_id,"
                 " product_id, created_product, product_name, hsn, unit, quantity, taxable_value, gst_rate, igst, cgst,"
                 " sgst, cess) values (:i, :b, :r, :n, :dl, :p, :cp, :pn, :h, :u, :q, :tv, :gr, :ig, :cg, :sg, :ce)"),
            {"i": line_id, "b": _business(uow), "r": review_id, "n": no, "dl": ln.draft_line_id,
             "p": got.product_id, "cp": got.created_product, "pn": ln.product_name.strip(), "h": ln.hsn,
             "u": ln.unit, "q": ln.quantity, "tv": ln.taxable_value, "gr": ln.gst_rate, "ig": ln.igst,
             "cg": ln.cgst, "sg": ln.sgst, "ce": ln.cess})
    audit.record(uow, "imports.purchase_confirmed", "purchase_review", review_id,
                 data={"review_id": str(review_id), "draft_id": str(draft_id), "lines": len(lines)})
    return Confirmed(review_id, draft_id, supplier_gstin, name, number, doc_date, invoice_total, len(lines),
                     get_clock().now(), tuple(received), tuple(warnings))


def _already_confirmed(tx, business_id: uuid.UUID, gstin: str, fy: str, key: str) -> bool:
    return tx.execute(text("select 1 from imports.purchase_reviews where business_id = :b and decision = 'confirmed'"
                           " and supplier_gstin = :g and fy = :fy and doc_key = :k"),
                      {"b": business_id, "g": gstin, "fy": fy, "k": key}).first() is not None


def _warnings(uow: UnitOfWork, lines: list[LineIn], doc_date: date, tx) -> list[tuple[int, str]]:
    """Non-blocking: a tax column that does not match taxable value times rate (nothing is recomputed or fixed), and a unit
    that differs from the unit of the existing product the line is received into."""
    today = get_clock().today()
    tolerance = Decimal(value_on(tx, "imports.purchase.tax_tolerance", today))
    out: list[tuple[int, str]] = []
    for no, ln in enumerate(lines, 1):
        expected = ln.taxable_value * ln.gst_rate / 100
        if abs(expected - (ln.igst + ln.cgst + ln.sgst)) > tolerance:
            out.append((no, "tax_differs_from_rate"))
        if ln.product_id is not None and ln.unit is not None:
            have = product_for_line(tx, ln.product_id, doc_date).uqc
            if have.strip().upper() != ln.unit.strip().upper():
                out.append((no, "unit_differs_from_product"))
    return out


def _unit_cost(ln: LineIn) -> Decimal | None:
    """Per 1 quantity, excluding GST, kept only when it is exact to two places: nothing is rounded for the ledger."""
    cost = ln.taxable_value / ln.quantity
    return cost if cost == cost.quantize(Decimal("0.01")) else None


def _receive(uow: UnitOfWork, review_id: uuid.UUID, line_id: uuid.UUID, ln: LineIn, received_on: date):
    """One confirmed line becomes stock, in this transaction: a new catalog item (its code, UQC and tax category are the
    business's, checked by the catalog) or an existing one, and a stock-in movement once per line."""
    item = ln.new_item
    if item is not None:  # the name and HSN are the ones confirmed on this line
        item = NewCatalogItem(code=item.code, name=ln.product_name.strip(), uqc=item.uqc, hsn=ln.hsn,
                              tax_category=item.tax_category, gst_rate=item.gst_rate,
                              rate_valid_from=item.rate_valid_from, has_cess=item.has_cess)
    return receive_confirmed_purchase_line(
        uow, ConfirmedPurchaseLine(source_id=review_id, source_line_id=line_id, quantity=ln.quantity,
                                   received_on=received_on, product_id=ln.product_id, new_item=item,
                                   unit_cost=_unit_cost(ln)), today=get_clock().today())


def _check_line(ln: LineIn, i: int, own: set, taken: set, hsn_ok, max_rate: Decimal) -> None:
    where = f"lines.{i}"
    name = (ln.product_name or "").strip()
    if not name or len(name) > 120 or not name.isprintable():
        raise Invalid("product_name_invalid", "Give each line's product name", field=f"{where}.product_name")
    if not hsn_ok.match(ln.hsn or ""):
        raise Invalid("hsn_invalid", "Check the HSN code", field=f"{where}.hsn")
    if ln.unit is not None and (not ln.unit.strip() or len(ln.unit) > 40 or not ln.unit.isprintable()):
        raise Invalid("unit_invalid", "Check the unit", field=f"{where}.unit")
    if not _positive(ln.quantity):
        raise Invalid("quantity_invalid", "The quantity must be more than zero", field=f"{where}.quantity")
    for field in ("taxable_value", "gst_rate", "igst", "cgst", "sgst", "cess"):
        v = getattr(ln, field)
        if not isinstance(v, Decimal) or not v.is_finite() or v < 0:
            raise Invalid(f"{field}_invalid", "Amounts can't be negative", field=f"{where}.{field}")
    if ln.gst_rate > max_rate:
        raise Invalid("gst_rate_invalid", "The GST rate can't be more than 100%", field=f"{where}.gst_rate")
    if ln.igst and (ln.cgst or ln.sgst):
        raise Invalid("tax_split_invalid", "A line has IGST, or CGST and SGST, not both", field=f"{where}.igst")
    if (ln.product_id is None) == (ln.new_item is None):
        raise Invalid("product_or_new_item", "Choose an existing product or give the new product's details",
                      field=f"{where}.product_id")
    if ln.draft_line_id is not None:
        if ln.draft_line_id not in own or ln.draft_line_id in taken:
            raise Invalid("draft_line_invalid", "That line is not on this invoice", field=f"{where}.draft_line_id")
        taken.add(ln.draft_line_id)


def _positive(v) -> bool:
    return isinstance(v, Decimal) and v.is_finite() and v > 0


def discard(uow: UnitOfWork, draft_id: uuid.UUID) -> Draft:
    draft = get_draft(uow, draft_id)
    get_file(uow, draft.file_id, lock=True)
    if get_draft(uow, draft_id).decision is not None:
        raise Conflict("purchase_already_reviewed", "This invoice has already been confirmed or discarded")
    review_id = uuid7()
    uow.tx.execute(
        text("insert into imports.purchase_reviews (id, business_id, draft_id, decision, created_by)"
             " values (:i, :b, :d, 'discarded', :me)"),
        {"i": review_id, "b": _business(uow), "d": draft_id, "me": uow.principal.user_id})
    audit.record(uow, "imports.purchase_discarded", "purchase_review", review_id,
                 data={"review_id": str(review_id), "draft_id": str(draft_id)})
    return get_draft(uow, draft_id)


def list_confirmed(uow: UnitOfWork, limit: int, offset: int) -> tuple[list[Confirmed], bool]:
    rows = uow.tx.execute(
        text("select r.id, r.draft_id, r.supplier_gstin, r.supplier_name, r.doc_number, r.doc_date, r.invoice_total,"
             " (select count(*) from imports.purchase_review_lines l where l.review_id = r.id"
             "  and l.business_id = r.business_id), r.created_at"
             " from imports.purchase_reviews r where r.business_id = :b and r.decision = 'confirmed'"
             " order by r.doc_date desc, r.id desc limit :n offset :o"),
        {"b": _business(uow), "n": limit + 1, "o": offset}).all()
    return [Confirmed(*r) for r in rows[:limit]], len(rows) > limit

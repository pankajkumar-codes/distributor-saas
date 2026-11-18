"""The monthly and quarterly sales-and-purchases files (R2-M6, D7).

For a finished month, or a finished quarter for a quarterly filer, this makes two files from the business's own
records: an Excel workbook (a summary, the sales lines, the purchase lines, and the practice documents on a sheet of
their own) and a purchase register in JSON. The GSTR-1 JSON for sales is not remade here: it is the return's own export
(`export_job`), and the answer names the return instances of the period so the screen can link to it. There is no GSTR-3B
JSON (D7, as approved) and the purchase register is our own plain format, not a GST portal file.

Where the rows come from, and nothing else: `filing.v_supply_lines` (a live sales invoice or credit note, or one
confirmed from an upload), `imports.v_purchase_lines` (a purchase invoice the business confirmed, with its file, pages and
read line) and `sales.v_practice_documents` (practice documents: shown apart, in no total, never in a file for filing).
Every amount is Decimal and is written as it is held. Nothing is worked out or rounded for the file.

Asking again for the same period when nothing under it changed returns the export already made: the fingerprint is a hash
of every row that went into it. A changed period (a new purchase confirmed, an invoice finalized) makes a new export and
the old one stays. A period must have ended. Due dates are not in these files: screens say "Check on the GST portal".
"""

import hashlib
import io
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

import openpyxl
from openpyxl.styles import Font
from sqlalchemy import text

from app.modules.business.interface import get_profile, quarter_months, quarter_start
from app.modules.refdata import value_on
from platform_common import audit
from platform_common.errors import Conflict, Deny, Invalid
from platform_common.ids import uuid7
from platform_common.storage import get_store, key_for
from platform_common.uow import UnitOfWork

from . import periods
from .build import M7_OMISSIONS
from .periods import month_end

FORMAT = "period_files_v1"
AREA = "exports"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
JSON = "application/json"
ZERO = Decimal()
SALES_COLUMNS = ("source_kind", "source_ref", "doc_number", "doc_date", "doc_kind", "supply_class", "counterparty_gstin",
                 "pos_state_code", "hsn", "uqc", "quantity", "rate", "taxable_value", "igst", "cgst", "sgst", "cess",
                 "doc_value")
PURCHASE_COLUMNS = ("supplier_gstin", "supplier_name", "doc_number", "doc_date", "file_name", "source_pages",
                    "source_page", "source_line_no", "line_no", "product_name", "hsn", "unit", "quantity", "taxable_value",
                    "gst_rate", "igst", "cgst", "sgst", "cess", "invoice_total")
PRACTICE_COLUMNS = ("doc_kind", "doc_number", "doc_date", "counterparty_gstin", "taxable_total", "igst_total",
                    "cgst_total", "sgst_total", "cess_total", "doc_total")
SALES_HEADERS = ("Source", "Reference", "Number", "Date", "Kind", "Supply class", "Buyer GSTIN", "Place of supply",
                 "HSN", "Unit", "Quantity", "Rate %", "Taxable value", "IGST", "CGST", "SGST/UTGST", "Cess",
                 "Document value")
PURCHASE_HEADERS = ("Supplier GSTIN", "Supplier name", "Invoice number", "Date", "File", "File pages", "Page read from",
                    "Line read from", "Line", "Product", "HSN", "Unit", "Quantity", "Taxable value", "Rate %", "IGST",
                    "CGST", "SGST/UTGST", "Cess", "Invoice total")
PRACTICE_HEADERS = ("Kind", "Number", "Date", "Buyer GSTIN", "Taxable value", "IGST", "CGST", "SGST/UTGST", "Cess", "Total")
REVIEW_AT = len(PURCHASE_COLUMNS)  # review_id follows the view's own columns in each purchase row
HEADER_ROW = len("ab")  # a note on row 1, the headers on row 2
TAXES = ("taxable_value", "igst", "cgst", "sgst", "cess")


@dataclass(frozen=True)
class Period:
    kind: str  # month | quarter
    start: date
    end: date


@dataclass(frozen=True)
class PeriodExport:
    id: uuid.UUID
    gstin: str
    kind: str
    start: date
    end: date
    sales_lines: int
    purchase_lines: int
    practice_documents: int
    created_at: object
    created: bool = False  # true when this call made it; false when it found the one already made


def period_of(tx, kind: str, start: date, today: date) -> Period:
    """The period asked for, if it is a whole finished month, or a whole finished quarter of a quarterly filer."""
    if kind not in ("month", "quarter"):
        raise Invalid("period_kind_invalid", "Choose a month or a quarter", field="kind")
    if start.day != 1 or (kind == "quarter" and quarter_start(start) != start):
        raise Invalid("period_start_invalid", "Give the first day of the month, or of the quarter", field="start")
    end = month_end(start) if kind == "month" else month_end(quarter_months(start)[-1])
    if end >= today:
        raise Conflict("period_not_ended", "That period has not ended yet. Come back after it has")
    if kind == "quarter":
        profile = get_profile(tx)
        if profile is None or not profile.gstin:
            raise Conflict("gstin_required", "Add your GSTIN first")
        if periods.filer_on(tx, profile.gstin, start) != "qrmp":
            raise Conflict("quarter_not_for_monthly_filer", "Quarter files are for businesses that file quarterly")
    return Period(kind, start, end)


def _gstin(tx) -> str:
    profile = get_profile(tx)
    if profile is None or not profile.gstin:
        raise Conflict("gstin_required", "Add your GSTIN first")
    return profile.gstin


def _rows(tx, sql: str, columns: tuple, params: dict) -> list[tuple]:
    got = tx.execute(text(sql), params).all()
    return [tuple(getattr(r, c) for c in columns) for r in got]


def _gather(tx, business: uuid.UUID, period: Period, cap: int):
    p = {"b": business, "s": period.start, "e": period.end, "n": cap + 1}
    sales = _rows(
        tx,
        f"select {', '.join(SALES_COLUMNS)}, source_id from filing.v_supply_lines where business_id = :b"
        " and doc_date between :s and :e order by doc_date, doc_number, source_id, hsn, rate, taxable_value limit :n",
        SALES_COLUMNS + ("source_id",), p)
    purchases = _rows(
        tx,
        f"select {', '.join(PURCHASE_COLUMNS)}, review_id, file_id, line_id from imports.v_purchase_lines"
        " where business_id = :b and doc_date between :s and :e order by doc_date, supplier_gstin, doc_number, review_id,"
        " line_no limit :n",
        PURCHASE_COLUMNS + ("review_id", "file_id", "line_id"), p)
    practice = _rows(
        tx,
        f"select {', '.join(PRACTICE_COLUMNS)}, document_id from sales.v_practice_documents where business_id = :b"
        " and doc_date between :s and :e order by doc_date, doc_number, document_id limit :n",
        PRACTICE_COLUMNS + ("document_id",), p)
    if max(len(sales), len(purchases), len(practice)) > cap:
        raise Conflict("period_too_large", "This period has more rows than one file can hold. Ask for a shorter period")
    return sales, purchases, practice


def _fingerprint(gstin: str, period: Period, sales, purchases, practice) -> str:
    h = hashlib.sha256()
    for part in (FORMAT, gstin, period.kind, period.start.isoformat(), period.end.isoformat()):
        h.update(part.encode() + b"\x1f")
    for name, rows in (("sales", sales), ("purchases", purchases), ("practice", practice)):
        h.update(name.encode() + b"\x1e")
        for row in rows:
            h.update("\x1f".join("" if v is None else str(v) for v in row).encode() + b"\x1e")
    return h.hexdigest()


def _sum(rows, columns, names) -> dict[str, Decimal]:
    index = {c: i for i, c in enumerate(columns)}
    return {n: sum((r[index[n]] or ZERO for r in rows), ZERO) for n in names}


def _text(v) -> str:
    return "" if v is None else str(v)


def build_workbook(gstin: str, period: Period, sales, purchases, practice) -> bytes:
    wb = openpyxl.Workbook()
    wb.properties.creator = "Kartaa"
    wb.properties.created = wb.properties.modified = datetime(period.end.year, period.end.month, period.end.day)  # not the clock
    bold = Font(bold=True)
    s = wb.active
    s.title = "Summary"
    label = f"{period.start:%b %Y}" if period.kind == "month" else f"{period.start:%b}–{period.end:%b %Y}"
    rows: list[tuple] = [
        ("Sales and purchases", label), ("GSTIN", gstin), ("Period", f"{period.start:%d-%m-%Y} to {period.end:%d-%m-%Y}"),
        (), ("A working file from your own records. It is not a return and nothing here is filed.",), (),
    ]
    for title, kind in (("Sales: invoices", "invoice"), ("Sales: credit notes", "credit_note")):
        picked = [r for r in sales if r[SALES_COLUMNS.index("doc_kind")] == kind]
        docs = len({(r[0], r[-1]) for r in picked})
        t = _sum(picked, SALES_COLUMNS, TAXES)
        rows += [(title, f"{docs} document(s), {len(picked)} line(s)"),
                 ("Taxable value", t["taxable_value"]), ("IGST", t["igst"]), ("CGST", t["cgst"]),
                 ("SGST/UTGST", t["sgst"]), ("Cess", t["cess"]), ()]
    pt = _sum(purchases, PURCHASE_COLUMNS, TAXES)
    rows += [("Purchases: confirmed invoices", f"{len({r[REVIEW_AT] for r in purchases})} invoice(s), {len(purchases)} line(s)"),
             ("Taxable value", pt["taxable_value"]), ("IGST", pt["igst"]), ("CGST", pt["cgst"]),
             ("SGST/UTGST", pt["sgst"]), ("Cess", pt["cess"]),
             ("Input tax credit is not decided here: purchases are listed as you confirmed them. Ask your CA.",), (),
             ("Practice documents (on their own sheet, in no total above)", f"{len(practice)} document(s)"), (),
             ("Due dates", "Check on the GST portal"), (),
             ("Not in the sales figures:",)]
    rows += [(text_,) for _, text_ in M7_OMISSIONS]
    rows += [(), ("The GSTR-1 file for sales is made from the return screen, not here.",),
             ("Amounts are exactly as held; nothing is rounded for this file.",)]
    for r in rows:
        _append(s, list(r))
    s["A1"].font = bold
    for name, headers, data, cols, note in (
        ("Sales", SALES_HEADERS, sales, SALES_COLUMNS, "Live invoices and credit notes only. Credit notes are shown, not netted."),
        ("Purchases", PURCHASE_HEADERS, purchases, PURCHASE_COLUMNS, "Confirmed purchase invoices. File, pages and line show where each came from."),
        ("Practice (not filed)", PRACTICE_HEADERS, practice, PRACTICE_COLUMNS, "Practice documents. They are not filed and are in no total."),
    ):
        ws = wb.create_sheet(name)
        _append(ws, [note])
        _append(ws, list(headers))
        for c in ws[HEADER_ROW]:
            c.font = bold
        width = len(cols)
        for row in data:
            _append(ws, [_cell(v) for v in row[:width]])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _append(ws, values: list) -> None:
    """Append a row with every text value forced to a string cell. openpyxl turns a string that starts with "=" into a live
    formula, and names, document numbers and file names are typed by users (formula injection), so text stays text."""
    ws.append(values)
    for c in ws[ws.max_row]:
        if isinstance(c.value, str):
            c.data_type = "s"


def _cell(v):
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v)
    if isinstance(v, date):
        return v.strftime("%d-%m-%Y")
    return v


def build_register(gstin: str, period: Period, purchases) -> bytes:
    """Our own plain purchase register: not a GST portal format. Invoices in date order, each with its source file and
    lines. Amounts are text, exactly as held. No time in it, so the same data gives the same bytes."""
    idx = {c: i for i, c in enumerate(PURCHASE_COLUMNS + ("review_id", "file_id", "line_id"))}
    invoices: dict = {}
    for r in purchases:
        g = lambda name: r[idx[name]]  # noqa: E731
        inv = invoices.setdefault(g("review_id"), {
            "supplier_gstin": g("supplier_gstin"), "supplier_name": g("supplier_name"), "number": g("doc_number"),
            "date": g("doc_date").isoformat(), "invoice_total": _text(g("invoice_total")) or None,
            "source": {"file_id": str(g("file_id")), "file_name": g("file_name"), "pages": list(g("source_pages"))},
            "lines": []})
        inv["lines"].append({
            "line_no": g("line_no"), "line_id": str(g("line_id")), "product_name": g("product_name"), "hsn": g("hsn"),
            "unit": g("unit"), "quantity": _text(g("quantity")), "taxable_value": _text(g("taxable_value")),
            "rate": _text(g("gst_rate")), "igst": _text(g("igst")), "cgst": _text(g("cgst")), "sgst": _text(g("sgst")),
            "cess": _text(g("cess")),
            "read_from": None if g("source_page") is None else {"page": g("source_page"), "line": g("source_line_no")}})
    doc = {"format": "purchase_register_v1", "portal_file": False, "gstin": gstin,
           "period": {"from": period.start.isoformat(), "to": period.end.isoformat()}, "invoices": list(invoices.values())}
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def generate(uow: UnitOfWork, kind: str, start: date, today: date) -> PeriodExport:
    from . import entitlement

    tx = uow.tx
    business = uow.principal.business_id
    if not entitlement.allowed(tx, business):  # before any work: a refusal must not build or store anything
        raise Conflict("download_not_available", "Downloading the file is not available for your plan yet.")
    period = period_of(tx, kind, start, today)
    gstin = _gstin(tx)
    cap = int(value_on(tx, "filing.period_files.max_rows", today))
    sales, purchases, practice = _gather(tx, business, period, cap)
    fp = _fingerprint(gstin, period, sales, purchases, practice)
    tx.execute(text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"period_files:{business}:{fp}"})
    found = _find(tx, business, period, fp)
    if found is not None:
        return found
    export_id = uuid7()
    files = {"workbook": (XLSX, build_workbook(gstin, period, sales, purchases, practice)),
             "purchase_register": (JSON, build_register(gstin, period, purchases))}
    store = get_store()
    tx.execute(
        text("insert into filing.period_exports (id, business_id, gstin, kind, period_start, period_end, fingerprint,"
             " sales_lines, purchase_lines, practice_documents, created_by)"
             " values (:i, :b, :g, :k, :s, :e, :f, :sl, :pl, :pd, :me)"),
        {"i": export_id, "b": business, "g": gstin, "k": kind, "s": period.start, "e": period.end, "f": fp,
         "sl": len(sales), "pl": len(purchases), "pd": len(practice), "me": uow.principal.user_id})
    for name, (ctype, data) in files.items():
        key = key_for(business, AREA, export_id, f"{name}-{period.start:%Y%m}.{'xlsx' if name == 'workbook' else 'json'}")
        store.put(business, key, data, ctype)
        tx.execute(
            text("insert into filing.period_export_files (export_id, business_id, name, object_key, sha256, size_bytes)"
                 " values (:i, :b, :n, :k, :h, :z)"),
            {"i": export_id, "b": business, "n": name, "k": key, "h": hashlib.sha256(data).hexdigest(), "z": len(data)})
    audit.record(uow, "filing.period_files_made", "period_export", export_id,
                 data={"export_id": str(export_id), "kind": kind, "period": f"{period.start:%Y-%m}",
                       "sales_lines": len(sales), "purchase_lines": len(purchases)})
    got = _find(tx, business, period, fp)
    return PeriodExport(**{**got.__dict__, "created": True})


_COLUMNS = "id, gstin, kind, period_start, period_end, sales_lines, purchase_lines, practice_documents, created_at"


def _find(tx, business: uuid.UUID, period: Period, fp: str) -> PeriodExport | None:
    r = tx.execute(
        text(f"select {_COLUMNS} from filing.period_exports where business_id = :b and kind = :k"
             " and period_start = :s and fingerprint = :f"),
        {"b": business, "k": period.kind, "s": period.start, "f": fp}).one_or_none()
    return None if r is None else PeriodExport(*r)


def list_exports(uow: UnitOfWork, limit: int, offset: int) -> tuple[list[PeriodExport], bool]:
    rows = uow.tx.execute(
        text(f"select {_COLUMNS} from filing.period_exports where business_id = :b"
             " order by period_start desc, created_at desc, id desc limit :n offset :o"),
        {"b": uow.principal.business_id, "n": limit + 1, "o": offset}).all()
    return [PeriodExport(*r) for r in rows[:limit]], len(rows) > limit


def get_export(uow: UnitOfWork, export_id: uuid.UUID) -> PeriodExport:
    r = uow.tx.execute(
        text(f"select {_COLUMNS} from filing.period_exports where id = :i and business_id = :b"),
        {"i": export_id, "b": uow.principal.business_id}).one_or_none()
    if r is None:
        raise Deny("not_found")
    return PeriodExport(*r)


def links(uow: UnitOfWork, export: PeriodExport) -> list[dict]:
    """60-second links to the files, with their hashes. The download rule is the GSTR-1 export's (`entitlement`)."""
    from . import entitlement

    business = uow.principal.business_id
    if not entitlement.allowed(uow.tx, business):
        raise Conflict("download_not_available", "Downloading the file is not available for your plan yet.")
    store = get_store()
    rows = uow.tx.execute(
        text("select name, object_key, sha256, size_bytes from filing.period_export_files"
             " where export_id = :i and business_id = :b order by name"),
        {"i": export.id, "b": business}).all()
    ext = {"workbook": "xlsx", "purchase_register": "json"}
    return [{"name": r.name, "sha256": r.sha256, "size_bytes": r.size_bytes,
             "url": store.presign_get(business, r.object_key, download_name=f"{r.name}_{export.start:%Y%m}.{ext[r.name]}")}
            for r in rows]


def returns_in(uow: UnitOfWork, export: PeriodExport) -> list:
    """The return instances (GSTR-1, IFF) of the period, for the link to the GSTR-1 file."""
    return periods.instances_between(uow.tx, export.gstin, export.start, export.end)

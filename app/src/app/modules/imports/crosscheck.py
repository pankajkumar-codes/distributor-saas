"""Excel versus PDF cross-check of the seller's own sales invoices (R1-M6 slice 3; BRD GF-13, GF-14).

Read-only and computed on request: nothing is stored and nothing reaches a return. The seller uploaded the
same invoices twice, once typed into our Excel template and once as the invoice PDFs, and this lists every
difference so they can fix whichever side is wrong. It never decides which side is right.

Compared per document (seller GSTIN, document type, document number; trimmed and case-folded), not per line,
so a different line split does not flood the screen: date, buyer GSTIN, place of supply, the sum of each money
column, the invoice total and the number of lines. Money is compared on exact Decimal equality; whether a
rounding difference may be tolerated is a CA question (OPEN_QUESTIONS), so none is applied.

Which rows count on each side: rows of a live run (staged or confirmed, never discarded). A row the seller set
aside is left out, as it will be left out of the return, so the difference it makes shows. A held row the seller
has not decided makes its document `not_compared` (its amounts are not known to be right) and is counted. A held
row the seller accepted or fixed counts, with a fixed place of supply applied. A row with no document number or
seller GSTIN (invalid) cannot be placed on a document and is counted as `unplaced`. A row shown as a duplicate is
the same record as a row of another live file and is not counted twice.

`show_validate_note` is the R1 rule: the note "upload invoices and we can validate" is shown only when a live
Excel upload exists and no live PDF upload does.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import text

from app.modules.refdata import state_codes
from platform_common.uow import UnitOfWork

EXCEL, PDF = "invoices", "invoices_pdf"
MONEY = ("taxable_value", "igst", "cgst", "sgst", "cess")
HEADER = ("doc_date", "buyer_gstin", "place_of_supply")

_ROWS = (
    "with latest as (select distinct on (row_id) row_id, kind, fix_field, fix_value from imports.row_resolutions"
    " where business_id = :b order by row_id, created_at desc, id desc)"
    " select w.id, r.report_type, w.status, w.normalized, l.kind, l.fix_field, l.fix_value"
    " from imports.import_rows w join imports.import_runs r on r.id = w.run_id and r.business_id = w.business_id"
    " left join latest l on l.row_id = w.id"
    " where w.business_id = :b and r.marketplace = 'own_invoices' and r.report_type in ('invoices', 'invoices_pdf')"
    " and r.status in ('staged', 'confirmed')")


@dataclass(frozen=True)
class DocRef:
    seller_gstin: str
    doc_type: str
    doc_number: str


@dataclass
class Doc:
    ref: DocRef
    row_ids: list[uuid.UUID] = field(default_factory=list)
    held: int = 0  # held rows the seller has not decided
    lines: int = 0
    totals: dict[str, Decimal] = field(default_factory=dict)
    values: dict[str, set] = field(default_factory=lambda: {k: set() for k in (*HEADER, "invoice_total")})


@dataclass(frozen=True)
class Difference:
    field: str
    excel: str
    pdf: str


@dataclass(frozen=True)
class Mismatch:
    doc: DocRef
    differences: tuple[Difference, ...]
    excel_rows: tuple[uuid.UUID, ...]
    pdf_rows: tuple[uuid.UUID, ...]


@dataclass(frozen=True)
class NotCompared:
    doc: DocRef
    excel_held: int
    pdf_held: int


@dataclass(frozen=True)
class Side:
    live: bool
    documents: int
    unplaced_rows: int


@dataclass(frozen=True)
class CrossCheck:
    show_validate_note: bool
    compared: bool  # an Excel and a PDF upload are both live
    excel: Side
    pdf: Side
    matching: int
    only_in_excel: tuple[DocRef, ...]
    only_in_pdf: tuple[DocRef, ...]
    mismatches: tuple[Mismatch, ...]
    not_compared: tuple[NotCompared, ...]


def _fold(value) -> str:
    return " ".join(str(value or "").split()).casefold()


def _dec(value) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal(0)


def _states(uow: UnitOfWork, today: date) -> dict[str, str]:
    """A state's name or code, folded, to its code, so 'West Bengal' on one side and '19' on the other agree."""
    out = {}
    for code, name in state_codes(uow.tx, today):
        out[_fold(code)] = code
        out[_fold(name)] = code
    return out


def _collect(uow: UnitOfWork, today: date):
    states = _states(uow, today)
    docs: dict[str, dict[tuple, Doc]] = {EXCEL: {}, PDF: {}}
    unplaced = {EXCEL: 0, PDF: 0}
    live = {EXCEL: False, PDF: False}
    for row_id, report_type, status, normalized, kind, fix_field, fix_value in uow.tx.execute(
            text(_ROWS), {"b": uow.principal.business_id}):
        live[report_type] = True
        n = dict(normalized or {})
        key = (_fold(n.get("seller_gstin")), _fold(n.get("doc_type")), _fold(n.get("doc_number")))
        if status == "duplicate":
            continue
        if status in ("invalid", "conflict") or not all(key):
            unplaced[report_type] += 1
            continue
        if kind == "set_aside":
            continue
        ref = DocRef(str(n["seller_gstin"]).strip(), " ".join(str(n["doc_type"]).split()),
                     " ".join(str(n["doc_number"]).split()))
        doc = docs[report_type].setdefault(key, Doc(ref))
        doc.row_ids.append(row_id)
        if status == "held" and kind is None:
            doc.held += 1
            continue
        if kind == "fixed" and fix_field == "state":
            n["place_of_supply"] = fix_value
        doc.lines += 1
        for name in MONEY:
            doc.totals[name] = doc.totals.get(name, Decimal(0)) + _dec(n.get(name))
        place = _fold(n.get("place_of_supply"))
        total = None if n.get("invoice_total") in (None, "") else _dec(n["invoice_total"])
        for name, value in (("doc_date", n.get("doc_date")), ("buyer_gstin", _fold(n.get("buyer_gstin")).upper()),
                            ("place_of_supply", states.get(place, place)), ("invoice_total", total)):
            if value not in (None, ""):
                doc.values[name].add(value)
    return docs, unplaced, live


def _shown(values: set) -> str:
    return ", ".join(sorted(str(v) for v in values))


def _differences(excel: Doc, pdf: Doc) -> list[Difference]:
    out = [Difference(name, _shown(excel.values[name]), _shown(pdf.values[name]))
           for name in (*HEADER, "invoice_total") if excel.values[name] != pdf.values[name]]
    zero = Decimal(0)
    out += [Difference(name, str(excel.totals.get(name, zero)), str(pdf.totals.get(name, zero)))
            for name in MONEY if excel.totals.get(name, zero) != pdf.totals.get(name, zero)]
    if excel.lines != pdf.lines:
        out.append(Difference("lines", str(excel.lines), str(pdf.lines)))
    return out


def check(uow: UnitOfWork, today: date) -> CrossCheck:
    docs, unplaced, live = _collect(uow, today)
    excel, pdf = docs[EXCEL], docs[PDF]
    sides = {t: Side(live[t], len(docs[t]), unplaced[t]) for t in (EXCEL, PDF)}
    show_note = live[EXCEL] and not live[PDF]
    if not (live[EXCEL] and live[PDF]):
        return CrossCheck(show_note, False, sides[EXCEL], sides[PDF], 0, (), (), (), ())
    matching, mismatches, held = 0, [], []
    for key in sorted(excel.keys() & pdf.keys()):
        e, p = excel[key], pdf[key]
        if e.held or p.held:
            held.append(NotCompared(e.ref, e.held, p.held))
            continue
        diffs = _differences(e, p)
        if diffs:
            mismatches.append(Mismatch(e.ref, tuple(diffs), tuple(e.row_ids), tuple(p.row_ids)))
        else:
            matching += 1
    return CrossCheck(
        show_note, True, sides[EXCEL], sides[PDF], matching,
        tuple(excel[k].ref for k in sorted(excel.keys() - pdf.keys())),
        tuple(pdf[k].ref for k in sorted(pdf.keys() - excel.keys())),
        tuple(mismatches), tuple(held))

"""Documents from a run's included rows (R1-M7 slice 2). Pure: no database, no refdata.

Only the seller's own invoices are mapped. A marketplace report's treatment (which charges are lines, how a
cancel or a cash-back note enters the return, which date places it) waits for the CA (platform-reader-spec
section 5), so those readers have no mapper and confirm is refused for them (`treatment_unconfirmed`).

A document is the seller GSTIN, kind, number (case and spaces folded) and the financial year of its date
(document-fields.md, Rule 46(b); needs CA check), so one number reused in another year is another document.
Values are kept exactly as typed.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

KINDS = {"invoice": "invoice", "credit note": "credit_note", "debit note": "debit_note"}


@dataclass(frozen=True)
class Line:
    row_id: object
    row_number: int
    line_key: str
    hsn: str
    hsn_from: str  # "file" or "fixed"
    unit: str | None
    quantity: Decimal | None
    rate: Decimal
    taxable_value: Decimal
    igst: Decimal
    cgst: Decimal
    sgst: Decimal
    cess: Decimal


@dataclass
class Doc:
    gstin: str
    kind: str  # invoice, credit_note, debit_note
    number: str
    key: str
    date: date
    original_number: str | None
    original_date: date | None
    buyer_gstin: str | None
    pos: str
    inter_state: bool
    stated_total: Decimal | None  # "Invoice total" as typed, if it was
    lines: list[Line] = field(default_factory=list)

    @property
    def taxable(self) -> Decimal:
        return sum((ln.taxable_value for ln in self.lines), Decimal(0))

    @property
    def total(self) -> Decimal:
        """The total as stated on the document, else the sum of its lines."""
        if self.stated_total is not None:
            return self.stated_total
        return sum((ln.taxable_value + ln.igst + ln.cgst + ln.sgst + ln.cess for ln in self.lines), Decimal(0))


def fold(value) -> str:
    return "".join(str(value or "").split()).upper()


def dec(value, default: Decimal | None = Decimal(0)) -> Decimal | None:
    if value in (None, ""):
        return default
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return default


def _date(value) -> date | None:
    try:
        return date.fromisoformat(str(value).partition("T")[0]) if value else None
    except ValueError:
        return None


def state_code(place: str | None, states: dict[str, str]) -> str | None:
    """A state code from the place of supply as written (a name or a two-digit code), or None."""
    return states.get(" ".join(str(place or "").split()).casefold())


def own_documents(rows, fy_of, states: dict[str, str]) -> tuple[list[Doc], list[tuple[str, list[int]]]]:
    """Documents from the included rows of an own-invoice run, in file order, and the problems found:
    (code, row numbers). `rows` are (number, id, values, line_key, fixed_hsn, fixed_state) in file order."""
    docs: dict[tuple, Doc] = {}
    problems: dict[str, list[int]] = {}
    for number, row_id, v, line_key, fixed_hsn, fixed_state in rows:
        d = _date(v.get("doc_date"))
        kind = KINDS.get(" ".join(str(v.get("doc_type") or "").split()).casefold())
        pos = fixed_state or state_code(v.get("place_of_supply"), states)
        if d is None or kind is None or pos is None:
            problems.setdefault("row_unusable", []).append(number)  # held earlier; cannot happen for included rows
            continue
        gstin = str(v.get("seller_gstin") or "").strip().upper()
        key = (gstin, kind, fold(v.get("doc_number")), fy_of(d))
        doc = docs.get(key)
        if doc is None:
            buyer = str(v.get("buyer_gstin") or "").strip().upper() or None
            doc = docs[key] = Doc(
                gstin=gstin, kind=kind, number=str(v.get("doc_number")).strip(), key=key[2], date=d,
                original_number=(str(v.get("original_number") or "").strip() or None),
                original_date=_date(v.get("original_date")), buyer_gstin=buyer, pos=pos,
                inter_state=pos != gstin[:2], stated_total=dec(v.get("invoice_total"), None))
        elif doc.pos != pos:
            problems.setdefault("place_of_supply_disagrees", []).append(number)
        doc.lines.append(Line(
            row_id=row_id, row_number=number, line_key=line_key,
            hsn=str(fixed_hsn or v.get("hsn") or "").strip(), hsn_from="fixed" if fixed_hsn else "file",
            unit=(str(v.get("unit") or "").strip() or None), quantity=dec(v.get("quantity"), None),
            rate=dec(v.get("gst_rate")), taxable_value=dec(v.get("taxable_value")),
            igst=dec(v.get("igst")), cgst=dec(v.get("cgst")), sgst=dec(v.get("sgst")), cess=dec(v.get("cess"))))
    return list(docs.values()), [(code, sorted(nums)) for code, nums in problems.items()]


def supply_class(kind: str, buyer: str | None, inter_state: bool, total: Decimal, b2cl_threshold: Decimal,
                 original_class: str | None) -> str | None:
    """B2B, B2CL, B2CS, CDNR or CDNUR (LLD-4 §3.3, LLD-7 L7-7); None for a debit note, which the builder has no
    section for yet. A note to a registered buyer is CDNR; to anyone else it follows its original: CDNUR for a
    B2CL original, otherwise netted into B2CS. An original not in the app is netted into B2CS and flagged by
    the caller (needs CA check)."""
    if kind == "debit_note":
        return None
    if kind == "invoice":
        return "B2B" if buyer else ("B2CL" if inter_state and total > b2cl_threshold else "B2CS")
    return "CDNR" if buyer else ("CDNUR" if original_class == "B2CL" else "B2CS")

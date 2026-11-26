"""From a page's visual rows to invoice facts (R1-M6 S1). Pure functions: rows in, facts out.

It anchors on printed labels and on the line table's column headings, never on fixed positions, and says
nothing about a field it cannot place: that field stays blank and is named in `unclear`. What it does not
do: no tax logic, no rate inference, no arithmetic check (R1-M7 does those), no buyer name, address or item
description reaches an own-invoice table (`table.to_table` drops it; purchases use it as the product name to check,
D-107), and no number is parsed through binary float.
The HSN shape is the caller's refdata `hsn.pattern` (format only; the minimum length by turnover is a CA
question this module never decides). Numeric dates are read day first (DD/MM/YYYY); a date that is not a real
calendar date that way is left blank. Two further layouts are read (slice 4c): a tax group over "Rate" and "Amt"
sub-headings (the amount column is used; a rate under IGST is the rate only when there is no GST % column, and a
CGST or SGST rate is never doubled into one), and a row of labels over a row of values (joined into "label: value"
only when every label has a value under it and the row holds nothing else).
"""

import re
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation

from .interface import ExtractedInvoice, ExtractedLine, PdfRefused
from .layout import Cell, Row

GSTIN = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9]Z[A-Z0-9]\b")
TOKEN = r"([A-Za-z0-9][A-Za-z0-9/\-]{0,19})"
ORIGINAL = re.compile(r"(?:original|against|ref(?:erence)?)\s*(?:tax\s*)?invoice\s*(?:no|number|num|#)\.?\s*[:\-]?\s*"
                      + TOKEN, re.I)
NUMBER = re.compile(r"(?:invoice|inv|bill|credit\s*note|debit\s*note|document)\s*(?:no|number|num|#)\.?\s*[:\-]?\s*"
                    + TOKEN, re.I)
DATE_TOKENS = (
    (re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b"), "{0}-{1}-{2}", "%d-%m-%Y"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "{0}-{1}-{2}", "%Y-%m-%d"),
    (re.compile(r"\b(\d{1,2})[ -]([A-Za-z]{3})[a-z]*[ ,-]+(\d{4})\b"), "{0} {1} {2}", "%d %b %Y"),
)
BUYER = re.compile(r"bill(?:ed)?\s*to|buyer|receiver|consignee|ship(?:ped)?\s*to|customer|recipient", re.I)
SELLER = re.compile(r"seller|supplier|sold\s*by", re.I)
TOTAL = re.compile(r"grand\s*total|total\s*amount|invoice\s*total|total\s*invoice\s*value|amount\s*payable|net\s*payable",
                   re.I)
TABLE_END = re.compile(r"^(grand\s*)?total\b|amount\s*in\s*words|bank|terms|declaration|authori[sz]ed", re.I)
MONEY = re.compile(r"^[₹]?\s*(?:rs\.?\s*)?(-?\d[\d,]*(?:\.\d+)?)$", re.I)
QTY_UNIT = re.compile(r"^(\d[\d,]*(?:\.\d+)?)\s*([A-Za-z]{1,10})?$")
DOC_TYPES = (("credit note", "Credit note"), ("debit note", "Debit note"), ("tax invoice", "Invoice"),
             ("invoice", "Invoice"))
TITLE_ROWS = 6
LABEL_ONLY = re.compile(
    r"^(?:original\s+)?(?:(?:tax\s+)?invoice|credit\s*note|debit\s*note)\s*(?:no|number|date)\.?$"
    r"|^date$|^place\s+of\s+supply$|^gstin$", re.I)
SUB_RATE = re.compile(r"^(?:rate(?:\s*%)?|%)$", re.I)
SUB_AMOUNT = re.compile(r"^(?:amt|amount)\.?$", re.I)
SUB_REACH = 40  # float-ok: points; a Rate or Amt cell farther than this from every tax heading is not under one
TAX_COLUMNS = ("igst", "cgst", "sgst", "cess")


def text_of(row: Row) -> str:
    return " ".join(c.text for c in row)


def money(text: str) -> str | None:
    m = MONEY.match(text.strip())
    if not m:
        return None
    clean = m.group(1).replace(",", "")
    try:
        return format(Decimal(clean), "f")
    except InvalidOperation:
        return None


def parse_date(text: str) -> str | None:
    for pattern, fmt_in, fmt in DATE_TOKENS:
        m = pattern.search(text)
        if m:
            try:
                return datetime.strptime(fmt_in.format(*m.groups()), fmt).strftime("%d-%m-%Y")  # noqa: DTZ007
            except ValueError:
                return None
    return None


@dataclass
class PageFacts:
    page: int
    numbers: set[str] = field(default_factory=set)
    original_numbers: set[str] = field(default_factory=set)
    dates: set[str] = field(default_factory=set)
    doc_type: set[str] = field(default_factory=set)
    seller: set[str] = field(default_factory=set)
    buyer: set[str] = field(default_factory=set)
    places: set[str] = field(default_factory=set)
    totals: list[str] = field(default_factory=list)
    lines: list[ExtractedLine] = field(default_factory=list)
    table_found: bool = False
    has_title: bool = False


def _overlap(a: Cell, b: Cell) -> float:  # float-ok: page geometry in points, never money
    return min(a.x1, b.x1) - max(a.x0, b.x0)


def join_stacked_labels(rows: list[Row]) -> list[Row]:
    """A row of labels over a row of values becomes one row of "label: value" cells. Only when every cell of the
    first row is a known label and each has its own value cell under it; otherwise both rows are left as they are."""
    out: list[Row] = []
    i = 0
    while i < len(rows):
        row = rows[i]
        nxt = rows[i + 1] if i + 1 < len(rows) else None
        if nxt is not None and all(LABEL_ONLY.match(c.text.strip()) for c in row):
            used: set[int] = set()
            joined: Row = []
            for label in row:
                best = max(((j, _overlap(label, v)) for j, v in enumerate(nxt) if j not in used),
                           key=lambda t: t[1], default=(None, 0))
                if best[0] is None or best[1] <= 0:
                    joined = []
                    break
                used.add(best[0])
                value = nxt[best[0]]
                joined.append(Cell(f"{label.text.strip().rstrip(':')}: {value.text}", min(label.x0, value.x0),
                                   max(label.x1, value.x1)))
            if joined and len(used) == len(row) and len(nxt) == len(row):
                out.append(joined)
                i += 2
                continue
        if all(LABEL_ONLY.match(c.text.strip()) for c in row):
            i += 1  # labels with no value under them carry no fact, and read as text they would invent one
            continue
        out.append(row)
        i += 1
    return out


def read_page(page: int, rows: list[Row], hsn: re.Pattern) -> PageFacts:
    f = PageFacts(page)
    rows = join_stacked_labels(rows)
    texts = [text_of(r) for r in rows]
    for t in texts[:TITLE_ROWS]:
        if ":" in t:
            continue  # "Invoice Date: ..." is a field, not the document's title
        low = t.casefold()
        for needle, kind in DOC_TYPES:
            if needle in low:
                f.doc_type.add(kind)
                break
        if "invoice" in low or "credit note" in low or "debit note" in low:
            f.has_title = True
    side = None  # None until a label says whose block we are in; the letterhead is the seller's
    for row, t in zip(rows, texts, strict=True):
        if BUYER.search(t):
            side = "buyer"
        elif SELLER.search(t):
            side = "seller"
        for g in GSTIN.findall(t):
            (f.buyer if side == "buyer" else f.seller).add(g)
        original = ORIGINAL.search(t)
        rest = t
        if original:
            f.original_numbers.add(original.group(1))
            rest = t[:original.start()] + " " + t[original.end():]
        number = NUMBER.search(rest)
        if number:
            f.numbers.add(number.group(1))
        low = rest.casefold()
        if "date" in low and "due" not in low and "original" not in low and not original:
            d = parse_date(rest[low.index("date"):])
            if d:
                f.dates.add(d)
        pos = re.search(r"place\s+of\s+supply\s*[:\-]?\s*(.+)$", t, re.I)
        if pos:
            value = pos.group(1).strip()
            code = re.search(r"\b(\d{2})\b", value)
            f.places.add(code.group(1) if code else re.sub(r"[^A-Za-z &]", "", value).strip()[:40])
        if TOTAL.search(t):
            nums = [money(c.text) for c in row]
            nums = [n for n in nums if n is not None]
            if nums:
                f.totals.append(nums[-1])
    f.lines, f.table_found = _table(page, rows, hsn)
    return f


DESCRIPTION_MAX = 100  # the sandbox's cap on any field read (sandbox.MAX_TEXT)
DESCRIPTION_HEAD = re.compile(r"^(?:description|item|product|particulars|goods|name\s+of\s+(?:goods|product|item))", re.I)
NOT_DESCRIPTION = re.compile(r"\b(?:code|no|sr|sl|id)\b\.?", re.I)


def _is_description(s: str) -> bool:
    return bool(DESCRIPTION_HEAD.match(s)) and not NOT_DESCRIPTION.search(s)


SERIAL_HEAD = re.compile(r"^(?:s|sr|sl)\.?\s*(?:no\.?)?$|^#$|^no\.?$", re.I)

HEADER_KEYS = (
    ("serial", lambda s: bool(SERIAL_HEAD.match(s))),  # a column of its own, so its numbers never join the description
    ("hsn", lambda s: "hsn" in s or "sac" in s),
    ("description", _is_description),
    ("quantity", lambda s: s.startswith("qty") or s.startswith("quantity")),
    ("unit", lambda s: s in ("unit", "uom") or s.startswith("unit of")),
    ("taxable_value", lambda s: "taxable" in s),
    ("gst_rate", lambda s: ("gst" in s or s.startswith("tax")) and ("%" in s or "rate" in s) and "amt" not in s
     and not any(t in s for t in ("igst", "cgst", "sgst", "utgst"))),
    ("igst", lambda s: s.startswith("igst") and "%" not in s and "rate" not in s),
    ("cgst", lambda s: s.startswith("cgst") and "%" not in s and "rate" not in s),
    ("sgst", lambda s: (s.startswith("sgst") or s.startswith("utgst")) and "%" not in s and "rate" not in s),
    ("cess", lambda s: s.startswith("cess") and "%" not in s and "rate" not in s),
)


def _columns(row: Row) -> dict[str, Cell] | None:
    cols: dict[str, Cell] = {}
    for cell in row:
        s = " ".join(cell.text.casefold().split())
        for name, test in HEADER_KEYS:
            if test(s):
                if name in ("description", "serial") and name in cols:
                    break  # "Item" and "Description" both: the first is kept; a second never spoils the table
                if name in cols:
                    return None  # the same heading twice: not a table we can read
                cols[name] = cell
                break
    return cols if "hsn" in cols and "taxable_value" in cols else None


def _table(page: int, rows: list[Row], hsn: re.Pattern) -> tuple[list[ExtractedLine], bool]:
    for i, row in enumerate(rows):
        cols = _columns(row)
        if cols is None:
            continue
        lines = []
        start = i + 1
        if start < len(rows) and _split_tax_headings(cols, rows[start]):
            start += 1
        for data in rows[start:]:
            if TABLE_END.search(data[0].text):
                break
            line = _line(page, data, cols, hsn)
            if line is not None:
                lines.append(line)
            elif lines and lines[-1].description is not None:
                more = _wrapped_description(data, cols)
                if more:
                    lines[-1] = replace(lines[-1], description=_description(f"{lines[-1].description} {more}"))
        return lines, True
    return [], False


def _parent(cell: Cell, cols: dict[str, Cell]) -> str | None:
    """The tax heading a sub-heading sits under: the one it overlaps most, else the one whose centre is nearest."""
    taxes = {n: cols[n] for n in TAX_COLUMNS if n in cols}
    if not taxes:
        return None
    name, head = max(taxes.items(), key=lambda kv: _overlap(cell, kv[1]))
    if _overlap(cell, head) > 0:
        return name
    centre = (cell.x0 + cell.x1) / 2
    name, head = min(taxes.items(), key=lambda kv: abs((kv[1].x0 + kv[1].x1) / 2 - centre))
    return name if abs((head.x0 + head.x1) / 2 - centre) < SUB_REACH else None


def _split_tax_headings(cols: dict[str, Cell], sub: Row) -> bool:
    """The row under the headings holds only "Rate" and "Amt" cells, each under a tax heading: use the amount cell as
    that tax's column and keep the rate cell out of the way. Returns True when the row was such a sub-heading row."""
    kinds = []
    for cell in sub:
        text = cell.text.strip()
        kind = "rate" if SUB_RATE.match(text) else "amount" if SUB_AMOUNT.match(text) else None
        parent = _parent(cell, cols)
        if kind is None or parent is None:
            return False
        kinds.append((kind, parent, cell))
    for kind, parent, cell in kinds:
        if kind == "amount":
            cols[parent] = cell
        elif parent == "igst" and "gst_rate" not in cols:
            cols["gst_rate"] = cell
        else:
            cols[f"{parent}_rate"] = cell
    return bool(kinds)


def _column_for(cell: Cell, cols: dict[str, Cell]) -> str | None:
    best, best_overlap = None, 0.0  # float-ok: page geometry in points, never money
    for name, head in cols.items():
        overlap = min(cell.x1, head.x1) - max(cell.x0, head.x0)
        if overlap > best_overlap:
            best, best_overlap = name, overlap
    if best is not None:
        return best
    centre = (cell.x0 + cell.x1) / 2
    name, head = min(cols.items(), key=lambda kv: abs((kv[1].x0 + kv[1].x1) / 2 - centre))
    return name if abs((head.x0 + head.x1) / 2 - centre) < 40 else None


def _description(text: str) -> str | None:
    """Spaces folded; over the cap it is cut at the last whole word that fits (the business checks it anyway)."""
    text = " ".join(text.split())
    if len(text) > DESCRIPTION_MAX:
        cut = text[:DESCRIPTION_MAX + 1].rsplit(" ", 1)[0]
        text = cut if 0 < len(cut) <= DESCRIPTION_MAX else text[:DESCRIPTION_MAX]
    return text or None


def _wrapped_description(data: Row, cols: dict[str, Cell]) -> str | None:
    """A row whose every cell sits under the description heading is the line above's description, wrapped."""
    if "description" not in cols or any(_column_for(c, cols) != "description" for c in data):
        return None
    return " ".join(c.text for c in data)


def _line(page: int, data: Row, cols: dict[str, Cell], hsn: re.Pattern) -> ExtractedLine | None:
    got: dict[str, list[str]] = {}
    for cell in data:
        name = _column_for(cell, cols)
        if name:
            got.setdefault(name, []).append(cell.text)
    hsn_text = " ".join(got.get("hsn", []))
    taxable = money(" ".join(got.get("taxable_value", []))) if "taxable_value" in got else None
    if not hsn.fullmatch(hsn_text) and taxable is None:
        return None  # a wrapped description or a sub-heading, not a line
    unclear: set[str] = set()
    values: dict[str, str | None] = {"hsn": hsn_text if hsn.fullmatch(hsn_text) else None, "taxable_value": taxable}
    quantity = unit = None
    q = QTY_UNIT.match(" ".join(got.get("quantity", [])).strip())
    if q:
        quantity = q.group(1).replace(",", "")
        unit = q.group(2)
    if "unit" in got and got["unit"]:
        unit = " ".join(got["unit"]).strip() or unit
    values.update(quantity=quantity, unit=unit)
    values["description"] = _description(" ".join(got.get("description", []))) if "description" in got else None
    rate = " ".join(got.get("gst_rate", [])).replace("%", "").strip()
    values["gst_rate"] = money(rate) if rate else None
    for name in ("igst", "cgst", "sgst", "cess"):
        text = " ".join(got.get(name, [])).strip()
        values[name] = money(text) if text and text != "-" else None  # a blank or dash column is "not charged"
    for name in ("hsn", "quantity", "unit", "taxable_value", "gst_rate"):
        if values[name] is None:
            unclear.add(name)
    return ExtractedLine(page=page, unclear=frozenset(unclear), **values)


def one(values: set[str]) -> str | None:
    return next(iter(values)) if len(values) == 1 else None


def assemble(pages: list[PageFacts], max_documents: int) -> list[ExtractedInvoice]:
    """Pages to documents. A page naming a different document number starts a new document; a page with no
    number continues the document before it only when it carries no title or date of its own. Anything else is
    an ambiguous boundary and the whole PDF is refused: a boundary is never guessed."""
    docs: list[list[PageFacts]] = []
    for f in pages:
        if len(f.numbers) > 1:
            raise PdfRefused("ambiguous_split")
        number = one(f.numbers)
        current = docs[-1] if docs else None
        if current is None:
            docs.append([f])
        elif number is None:
            if f.has_title or f.dates:
                raise PdfRefused("ambiguous_split")
            current.append(f)
        elif number == one(current[0].numbers):
            current.append(f)
        else:
            docs.append([f])
        if len(docs) > max_documents:
            raise PdfRefused("too_many_documents")
    return [_invoice(d) for d in docs]


def _agree(sets: list[set[str]]) -> str | None:
    union = set().union(*sets)
    return one(union)


def _invoice(group: list[PageFacts]) -> ExtractedInvoice:
    unclear: set[str] = set()

    def pick(name: str, sets: list[set[str]]) -> str | None:
        value = _agree(sets)
        if value is None:
            unclear.add(name)
        return value

    kinds = set().union(*(f.doc_type for f in group))
    kind = one(kinds) if len(kinds) == 1 else None
    if kind is None:
        unclear.add("doc_type")
    totals = [t for f in group for t in f.totals]
    originals = set().union(*(f.original_numbers for f in group))
    if kind in ("Credit note", "Debit note") and len(originals) != 1:
        unclear.add("original_number")
    lines = tuple(line for f in group for line in f.lines)
    if not lines:
        unclear.add("lines")
    return ExtractedInvoice(
        pages=tuple(f.page for f in group),
        seller_gstin=pick("seller_gstin", [f.seller for f in group]),
        doc_type=kind,
        doc_number=pick("doc_number", [f.numbers for f in group]),
        doc_date=pick("doc_date", [f.dates for f in group]),
        original_number=one(originals) if len(originals) == 1 else None,
        buyer_gstin=_agree([f.buyer for f in group]),  # a B2C invoice has none: blank is not unclear
        place_of_supply=pick("place_of_supply", [f.places for f in group]),
        invoice_total=totals[-1] if totals else None,
        lines=lines,
        unclear=frozenset(unclear),
    )

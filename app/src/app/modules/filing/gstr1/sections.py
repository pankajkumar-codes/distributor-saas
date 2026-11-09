"""GSTR-1 sections from supply lines (LLD-5 §5, gstr1-examples Part A). Pure: no
database, no refdata. Classification happened at finalize with the dated refdata
thresholds (`gstr1.b2cl_threshold`, LLD-4 §3.3), so the builder routes by the stored
`supply_class` and never re-classifies (LLD-5 §5, E1/E2).

Which lines go in (the member sets of LLD-5 §5: a quarter's liability lines exclude
locked IFF members, its Table 12 includes every IFF month) is the caller's query; this
module gets the two sets and builds the rows.
"""

from collections.abc import Iterable
from decimal import Decimal

from .model import (
    Amounts,
    B2BRow,
    B2CLRow,
    B2CSRow,
    CDNRRow,
    CDNURRow,
    Gstr1Sections,
    HSNRow,
    ReturnKind,
    SupplyLine,
)

# (doc_kind, supply_class) -> section. LLD-4 §3.3 sets a credit note's class: CDNR for a
# registered buyer, CDNUR when the original was B2CL, otherwise B2CS (netted into Table 7).
ROUTE = {
    ("invoice", "B2B"): "b2b",
    ("invoice", "B2CL"): "b2cl",
    ("invoice", "B2CS"): "b2cs",
    ("credit_note", "CDNR"): "cdnr",
    ("credit_note", "CDNUR"): "cdnur",
    ("credit_note", "B2CS"): "b2cs",
}
# Table 12's tab follows the class; a note's class already follows its original (A6, HSN3).
HSN_TAB = {"B2B": "b2b", "CDNR": "b2b", "B2CL": "b2c", "B2CS": "b2c", "CDNUR": "b2c"}
# An IFF carries B2B invoices and registered notes only, and no Table 12 or 13 (IFFQ FAQ 10).
IFF_SECTIONS = frozenset({"b2b", "cdnr"})

# What these rows rely on that the CA (or QA) has not confirmed yet; the build carries
# the list so checks (C-16) and the CA pack can show it.
PENDING = (
    "gstr1-examples A6 [CA]: credit notes are netted in Table 12",
    "CA-2: row tax is the sum of the invoice lines' tax, not the offline tool's recompute",
    "CA-3: Table 12 quantity keeps 3 decimals here; the export rounds",
    "LLD-5 C-12 / QA open item 3: a B2CS row that nets negative is kept, and blocked at export",
    "b2cs Type E and the e-commerce GSTIN (R1b, template open issue 4): own sales are Type OE",
)
QUARTER_PENDING = "gstr1-examples Part B [CA]: the quarter's Table 12 covers its IFF months"


class BadSupplyLine(ValueError):
    """A supply line the builder must not guess about (CLAUDE.md rule 10)."""


def build_sections(
    lines: Iterable[SupplyLine],
    *,
    kind: ReturnKind = "GSTR1",
    hsn_lines: Iterable[SupplyLine] | None = None,
) -> Gstr1Sections:
    """`lines`: the liability member set (Tables 4A, 5, 7, 9B). `hsn_lines`: Table 12's
    member set when it differs (a QRMP quarter: the quarter plus every IFF month);
    `None` uses `lines`. An IFF gets no B2C and no Table 12."""
    if kind == "IFF" and hsn_lines is not None:
        raise BadSupplyLine("an IFF has no Table 12, so it takes no hsn_lines")
    lines = tuple(lines)
    routed: dict[str, list[SupplyLine]] = {s: [] for s in ("b2b", "b2cl", "b2cs", "cdnr", "cdnur")}
    for ln in lines:
        section = _route(ln)
        if kind == "IFF" and section not in IFF_SECTIONS:
            raise BadSupplyLine(f"{ln.source_ref}: an IFF carries B2B invoices and registered notes only")
        routed[section].append(ln)
    pending = PENDING
    if kind == "IFF":
        hsn_b2b = hsn_b2c = ()
    else:
        summary = lines if hsn_lines is None else tuple(hsn_lines)
        for ln in summary:
            _route(ln)
        hsn_b2b = _hsn(ln for ln in summary if HSN_TAB[ln.supply_class] == "b2b")
        hsn_b2c = _hsn(ln for ln in summary if HSN_TAB[ln.supply_class] == "b2c")
        if hsn_lines is not None:
            pending = (*PENDING, QUARTER_PENDING)
    return Gstr1Sections(
        kind=kind,
        b2b=tuple(_b2b(routed["b2b"])),
        b2cl=tuple(_b2cl(routed["b2cl"])),
        b2cs=_b2cs(routed["b2cs"]),
        cdnr=tuple(_cdnr(routed["cdnr"])),
        cdnur=tuple(_cdnur(routed["cdnur"])),
        hsn_b2b=hsn_b2b,
        hsn_b2c=hsn_b2c,
        pending=pending,
    )


def liability(*builds: Gstr1Sections) -> Amounts:
    """Tables 4A + 5 + 7 − 9B per head (gstr1-examples A8), over one or more builds."""
    total = Amounts()
    for b in builds:
        for row in (*b.b2b, *b.b2cl, *b.b2cs):
            total += row.amounts
        for row in (*b.cdnr, *b.cdnur):
            total -= row.amounts
    return total


def hsn_total(build: Gstr1Sections) -> Amounts:
    """Table 12 B2B + B2C per head."""
    total = Amounts()
    for row in (*build.hsn_b2b, *build.hsn_b2c):
        total += row.amounts
    return total


def reconciliation_gap(build: Gstr1Sections, *, iff_builds: Iterable[Gstr1Sections] = ()) -> Amounts:
    """Liability minus Table 12, per head; zero when they agree (L5-7, A8). A QRMP
    quarter's Table 12 also covers its locked IFF months, so pass those IFF builds too
    (LLD-5 erratum [S6-2], D-043; gstr1-examples Part B)."""
    return liability(build, *iff_builds) - hsn_total(build)


# -- internals ---------------------------------------------------------------------------


def _route(ln: SupplyLine) -> str:
    if ln.source_kind == "marketplace_row":
        raise BadSupplyLine(f"{ln.source_ref}: marketplace rows (Table 14) are R1b")
    section = ROUTE.get((ln.doc_kind, ln.supply_class))
    if section is None:
        raise BadSupplyLine(f"{ln.source_ref}: a {ln.doc_kind} can't be {ln.supply_class}")
    if section in ("b2b", "cdnr") and not ln.counterparty_gstin:
        raise BadSupplyLine(f"{ln.source_ref}: {ln.supply_class} needs the buyer's GSTIN")
    return section


def _amounts(ln: SupplyLine) -> Amounts:
    return Amounts(ln.taxable_value, ln.igst, ln.cgst, ln.sgst, ln.cess)


def _signed(ln: SupplyLine) -> Amounts:
    return -_amounts(ln) if ln.doc_kind == "credit_note" else _amounts(ln)


def _per_document_rate(lines: list[SupplyLine]):
    """Group a document's lines by rate, in document then rate order; the header columns
    must agree across a document's lines (they come from one document row)."""
    groups: dict[tuple, list[SupplyLine]] = {}
    for ln in lines:
        groups.setdefault((ln.source_id, ln.rate), []).append(ln)
    for (_, rate), group in sorted(groups.items(), key=lambda kv: (kv[1][0].doc_date, kv[1][0].doc_number, kv[0][1])):
        first = group[0]
        header = _header(first)
        for ln in group[1:]:
            if _header(ln) != header:
                raise BadSupplyLine(f"{first.source_ref}: lines of one document disagree on {header} vs {_header(ln)}")
        total = Amounts()
        for ln in group:
            total += _amounts(ln)
        yield first, rate, total, tuple(sorted({ln.source_ref for ln in group}))


def _header(ln: SupplyLine) -> tuple:
    return (
        ln.doc_number,
        ln.doc_date,
        ln.doc_value,
        ln.pos_state_code,
        ln.counterparty_gstin,
        ln.original_doc_number,
        ln.original_doc_date,
    )


def _b2b(lines):
    for d, rate, amounts, refs in _per_document_rate(lines):
        yield B2BRow(
            d.counterparty_gstin, d.counterparty_name, d.doc_number, d.doc_date, d.doc_value,
            d.pos_state_code, rate, amounts, refs,
        )  # fmt: skip


def _b2cl(lines):
    for d, rate, amounts, refs in _per_document_rate(lines):
        yield B2CLRow(d.doc_number, d.doc_date, d.doc_value, d.pos_state_code, rate, amounts, refs)


def _cdnr(lines):
    for d, rate, amounts, refs in _per_document_rate(lines):
        yield CDNRRow(
            d.counterparty_gstin, d.counterparty_name, d.doc_number, d.doc_date, d.doc_value,
            d.pos_state_code, rate, amounts, d.original_doc_number, d.original_doc_date, refs,
        )  # fmt: skip


def _cdnur(lines):
    for d, rate, amounts, refs in _per_document_rate(lines):
        yield CDNURRow(
            d.doc_number, d.doc_date, d.doc_value, d.pos_state_code, rate, amounts,
            d.original_doc_number, d.original_doc_date, refs,
        )  # fmt: skip


def _b2cs(lines) -> tuple[B2CSRow, ...]:
    """Per PoS x rate, invoices minus B2CS notes. A row that nets to zero in every head is
    dropped; a negative one is kept for check C-12 (E3)."""
    groups: dict[tuple, tuple[Amounts, set]] = {}
    for ln in lines:
        amounts, refs = groups.get((ln.pos_state_code, ln.rate), (Amounts(), set()))
        groups[(ln.pos_state_code, ln.rate)] = (amounts + _signed(ln), refs | {ln.source_ref})
    return tuple(
        B2CSRow(pos, rate, amounts, tuple(sorted(refs)))
        for (pos, rate), (amounts, refs) in sorted(groups.items())
        if not amounts.is_zero()
    )


def _hsn(lines) -> tuple[HSNRow, ...]:
    """Per HSN x UQC x rate, credit notes reducing quantity and value [CA, A6]. A row
    that nets to zero in quantity and every head is dropped."""
    groups: dict[tuple, tuple[Decimal, Amounts, set]] = {}
    for ln in lines:
        key = (ln.hsn, ln.uqc, ln.rate)
        qty, amounts, refs = groups.get(key, (Decimal(), Amounts(), set()))
        sign = -1 if ln.doc_kind == "credit_note" else 1
        groups[key] = (qty + sign * ln.quantity, amounts + _signed(ln), refs | {ln.source_ref})
    return tuple(
        HSNRow(hsn, uqc, rate, qty, amounts, tuple(sorted(refs)))
        for (hsn, uqc, rate), (qty, amounts, refs) in sorted(groups.items())
        if not (qty == 0 and amounts.is_zero())
    )

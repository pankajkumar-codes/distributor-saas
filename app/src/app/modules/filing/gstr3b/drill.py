"""The GSTR-1 rows behind one figure of the GSTR-3B worksheet (BRD GF-22 drill-down). Pure.

`rows_behind` lists exactly the rows `build_outward` adds up for 3.1(a) or for one place of supply of 3.2, with credit notes as
negative rows, so the signed rows sum to the figure on the screen. A row's `source_refs` are the document numbers behind it, as in
the GSTR-1 section lists. The upload file and row a document came from are not part of the filing view yet (OPEN_QUESTIONS).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.modules.filing.gstr1 import Amounts, Gstr1Sections


@dataclass(frozen=True)
class DrillRow:
    section: str  # b2b, b2cl, b2cs, cdnr, cdnur
    kind: str  # invoice, credit_note, debit_note, or b2cs_group (several small invoices of one place of supply and rate)
    doc_number: str | None
    doc_date: date | None
    pos_state_code: str
    rate: Decimal
    amounts: Amounts  # signed: a credit note is negative
    source_refs: tuple[str, ...]


def _invoice(section: str, r) -> DrillRow:
    return DrillRow(section, "invoice", r.invoice_number, r.invoice_date, r.pos_state_code, r.rate, r.amounts, r.source_refs)


def _note(section: str, r) -> DrillRow:
    kind = "credit_note" if r.note_type == "C" else "debit_note"
    return DrillRow(section, kind, r.note_number, r.note_date, r.pos_state_code, r.rate, r.signed, r.source_refs)


def _group(r) -> DrillRow:
    return DrillRow("b2cs", "b2cs_group", None, None, r.pos_state_code, r.rate, r.amounts, r.source_refs)


def rows_behind(builds: Iterable[Gstr1Sections], supplier_state: str, figure: str, state: str | None = None) -> list[DrillRow]:
    """`figure` is "3_1_a" (all outward rows) or "3_2" (inter-state rows to unregistered buyers at place of supply `state`)."""
    out: list[DrillRow] = []
    for b in builds:
        invoices = [*(_invoice("b2b", r) for r in b.b2b), *(_invoice("b2cl", r) for r in b.b2cl), *(_group(r) for r in b.b2cs)]
        notes = [*(_note("cdnr", r) for r in b.cdnr), *(_note("cdnur", r) for r in b.cdnur)]
        if figure == "3_1_a":
            out += invoices + notes
        elif figure == "3_2":
            out += [r for r in invoices if r.section in ("b2cl", "b2cs") and r.pos_state_code == state != supplier_state]
            out += [r for r in notes if r.section == "cdnur" and r.pos_state_code == state != supplier_state]
        else:
            raise ValueError(f"unknown figure {figure!r}")
    return out

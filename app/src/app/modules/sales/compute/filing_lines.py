"""A finalized document's supply lines (LLD-4 §10, HLD §3.1): what `sales.v_filing_lines`
publishes for it, built here from compute's output so the GSTR-1 golden tests can run
compute → supply lines → sections without a database. The view (S6) must produce the
same rows; its contract test can compare against this function.

One supply line per document line (a line has one rate). Credit note amounts stay
positive; filing applies the sign (LLD-5 §3). UTGST goes in the `sgst` column.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from app.modules.filing.interface import SupplyLine
from platform_common.errors import Invalid

from .model import Computation

ZERO = Decimal()
_COLUMN = {"IGST": "igst", "CGST": "cgst", "SGST": "sgst", "UTGST": "sgst"}


@dataclass(frozen=True)
class FilingHeader:
    """The document row's columns that compute doesn't decide."""

    source_id: uuid.UUID
    doc_number: str
    doc_date: date
    doc_kind: Literal["invoice", "credit_note"]
    gstin: str
    counterparty_gstin: str | None = None
    counterparty_name: str | None = None
    # A credit note's class is set at finalize from its original (LLD-4 §3.3): CDNR,
    # CDNUR or B2CS. An invoice takes compute's class, so leave it None.
    note_supply_class: Literal["CDNR", "CDNUR", "B2CS"] | None = None
    original_doc_number: str | None = None
    original_doc_date: date | None = None
    return_instance_id: uuid.UUID | None = None
    return_period: str | None = None


def filing_lines(header: FilingHeader, comp: Computation) -> tuple[SupplyLine, ...]:
    """Raises Invalid for a computation that could not be finalized (blocks, or no
    class or place of supply): only finalized documents have supply lines."""
    if comp.blocks or comp.supply_class is None or comp.pos_state_code is None:
        raise Invalid("not_finalizable", "Only a finalized document has supply lines.")
    if header.doc_kind == "credit_note":
        if header.note_supply_class is None:
            raise Invalid("note_class_missing", "A credit note needs its class from the original.")
        supply_class = header.note_supply_class
        source_kind = "own_credit_note"
    else:
        if header.note_supply_class is not None:
            raise Invalid("note_class_on_invoice", "An invoice takes its class from compute.")
        supply_class = comp.supply_class
        source_kind = "own_invoice"
    out = []
    for ln in comp.lines:
        if ln.rate is None:  # a finalizable line always has one; never write a line without it
            raise Invalid(
                "line_rate_missing",
                "A line without a GST rate has no supply line.",
                field=f"lines.{ln.line_no - 1}.product_id",
            )
        heads = {"igst": ZERO, "cgst": ZERO, "sgst": ZERO}
        for tax in ln.taxes:
            heads[_COLUMN[tax.component]] += tax.amount
        out.append(
            SupplyLine(
                source_kind=source_kind,
                source_id=header.source_id,
                source_ref=header.doc_number,
                gstin=header.gstin,
                doc_date=header.doc_date,
                doc_number=header.doc_number,
                doc_kind=header.doc_kind,
                supply_class=supply_class,
                pos_state_code=comp.pos_state_code,
                rate=ln.rate,
                hsn=ln.product.hsn,
                uqc=ln.product.uqc,
                quantity=ln.quantity,
                taxable_value=ln.taxable,
                cess=ZERO,  # no cess products in R1 (compute blocks them)
                doc_value=comp.doc_total,
                counterparty_gstin=header.counterparty_gstin,
                counterparty_name=header.counterparty_name,
                return_instance_id=header.return_instance_id,
                return_period=header.return_period,
                original_doc_number=header.original_doc_number,
                original_doc_date=header.original_doc_date,
                **heads,
            )
        )
    return tuple(out)

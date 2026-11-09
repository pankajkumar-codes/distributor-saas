"""Supply lines in, GSTR-1 section rows out (LLD-5 §3, §5; gstr1-examples Part A).

`SupplyLine` is HLD §3.1's supply line (LLD-5 §3 view contract v1) plus `doc_value`,
the document's total repeated on each of its lines, which LLD-5 §5 needs for the
invoice and note value columns but the v1 column list leaves out (raised with the EM;
see docs/OPEN_QUESTIONS.md, GSTR-1 sections). Section rows carry portal fields [MAN1]; the
template's sheet names, list texts and fixed values (Reverse Charge N, Invoice Type,
b2cs Type OE) are the export's mapping (LLD-5 §7), not the builder's.

Credit notes come in with positive amounts and `doc_kind = "credit_note"`; the builder
applies the sign (LLD-5 §3). All money is Decimal, summed as stored, never re-rounded
(gstr1-examples §0); quantities keep 3 decimals (CA-3 decides the export's rounding).
"""

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal

SourceKind = Literal["own_invoice", "own_credit_note", "marketplace_row"]
DocKind = Literal["invoice", "credit_note"]
SupplyClass = Literal["B2B", "B2CL", "B2CS", "CDNR", "CDNUR"]
ReturnKind = Literal["GSTR1", "IFF"]
HEADS = ("taxable_value", "igst", "cgst", "sgst", "cess")


@dataclass(frozen=True)
class SupplyLine:
    """One row of filing.v_supply_lines. `sgst` carries UTGST for a UT (LLD-4 §10)."""

    source_kind: SourceKind
    source_id: uuid.UUID
    source_ref: str  # the document number, for drill-down (GF-3)
    gstin: str
    doc_date: date
    doc_number: str
    doc_kind: DocKind
    supply_class: SupplyClass
    pos_state_code: str
    rate: Decimal
    hsn: str
    uqc: str
    quantity: Decimal
    taxable_value: Decimal
    igst: Decimal
    cgst: Decimal
    sgst: Decimal
    cess: Decimal
    doc_value: Decimal  # the document's total, on every line (not in view contract v1)
    counterparty_gstin: str | None = None
    counterparty_name: str | None = None
    return_instance_id: uuid.UUID | None = None
    return_period: str | None = None
    original_doc_number: str | None = None
    original_doc_date: date | None = None
    operator_gstin: str | None = None  # R1b
    marketplace: str | None = None  # R1b


@dataclass(frozen=True)
class Amounts:
    taxable_value: Decimal = Decimal()
    igst: Decimal = Decimal()
    cgst: Decimal = Decimal()
    sgst: Decimal = Decimal()
    cess: Decimal = Decimal()

    def __add__(self, other: "Amounts") -> "Amounts":
        return Amounts(*(getattr(self, h) + getattr(other, h) for h in HEADS))

    def __neg__(self) -> "Amounts":
        return Amounts(*(-getattr(self, h) for h in HEADS))

    def __sub__(self, other: "Amounts") -> "Amounts":
        return self + -other

    def is_zero(self) -> bool:
        return all(getattr(self, h) == 0 for h in HEADS)


@dataclass(frozen=True)
class B2BRow:  # Table 4A: one row per invoice x rate
    recipient_gstin: str
    recipient_name: str | None
    invoice_number: str
    invoice_date: date
    invoice_value: Decimal
    pos_state_code: str
    rate: Decimal
    amounts: Amounts
    source_refs: tuple[str, ...]


@dataclass(frozen=True)
class B2CLRow:  # Table 5: one row per invoice x rate
    invoice_number: str
    invoice_date: date
    invoice_value: Decimal
    pos_state_code: str
    rate: Decimal
    amounts: Amounts
    source_refs: tuple[str, ...]


@dataclass(frozen=True)
class B2CSRow:  # Table 7: one row per place of supply x rate, net of B2CS credit notes
    pos_state_code: str
    rate: Decimal
    amounts: Amounts  # may be negative (check C-12 decides, gstr1-examples E3)
    source_refs: tuple[str, ...]


@dataclass(frozen=True)
class CDNRRow:  # Table 9B registered: one row per note x rate, amounts positive
    recipient_gstin: str
    recipient_name: str | None
    note_number: str
    note_date: date
    note_value: Decimal
    pos_state_code: str
    rate: Decimal
    amounts: Amounts
    original_doc_number: str | None
    original_doc_date: date | None
    source_refs: tuple[str, ...]
    note_type: Literal["C"] = "C"


@dataclass(frozen=True)
class CDNURRow:  # Table 9B unregistered: notes against B2CL invoices (gstr1-examples E4)
    note_number: str
    note_date: date
    note_value: Decimal
    pos_state_code: str
    rate: Decimal
    amounts: Amounts
    original_doc_number: str | None
    original_doc_date: date | None
    source_refs: tuple[str, ...]
    note_type: Literal["C"] = "C"
    ur_type: Literal["B2CL"] = "B2CL"


@dataclass(frozen=True)
class HSNRow:  # Table 12, per tab: one row per HSN x UQC x rate, credit notes netted [CA]
    hsn: str
    uqc: str
    rate: Decimal
    quantity: Decimal
    amounts: Amounts
    source_refs: tuple[str, ...]


@dataclass(frozen=True)
class Gstr1Sections:
    kind: ReturnKind
    b2b: tuple[B2BRow, ...] = ()
    b2cl: tuple[B2CLRow, ...] = ()
    b2cs: tuple[B2CSRow, ...] = ()
    cdnr: tuple[CDNRRow, ...] = ()
    cdnur: tuple[CDNURRow, ...] = ()
    hsn_b2b: tuple[HSNRow, ...] = ()
    hsn_b2c: tuple[HSNRow, ...] = ()
    pending: tuple[str, ...] = field(default=())  # [CA] items these rows rely on

    @property
    def line_items(self) -> int:
        """Data rows in every section (gstr1-examples Part D's line count; Table 13 is
        added by the full build)."""
        return sum(len(s) for s in (self.b2b, self.b2cl, self.b2cs, self.cdnr, self.cdnur, self.hsn_b2b, self.hsn_b2c))

"""Outward supplies of a GSTR-3B worksheet from GSTR-1 section rows (BRD GF-22; utility V5.8 Tables 3.1 and 3.2).

The figures come from exactly the rows the period's GSTR-1 build holds, so the worksheet and the GSTR-1 agree to the paisa:
3.1(a) is Tables 4A + 5 + 7 minus 9B (the same sum as `gstr1.liability`). Money is Decimal throughout and never re-rounded.

What is not decided here, and is carried as a flag in the result (CLAUDE.md rule 12, BRD "to be confirmed"):
- credit notes are taken off 3.1(a) (netting is a CA question);
- rows at a 0 rate stay in 3.1(a): the build has no nil-rated or exempt split, so they may belong in 3.1(c);
- 3.1(b), (c) and (e) are zero because exports, SEZ, nil-rated, exempt and non-GST supplies are not built from uploads yet;
- 3.2 covers buyers who are unregistered. Composition and UIN buyers are not known to the build, so they are zero.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from app.modules.filing.gstr1 import Amounts, Gstr1Sections

# Stable code -> what a business owner reads. Provisional product copy, to be reviewed with the CA.
FLAG_TEXT = {
    "note_netting": "Credit notes are taken off the outward supplies here. Your CA should confirm this.",
    "zero_rate_rows": "Some rows are at a 0% rate. They are counted as taxable supplies here; your CA should say whether they"
                      " belong under nil-rated or exempt supplies.",
    "nil_exempt_non_gst_not_built": "Nil-rated, exempt and non-GST supplies, exports and SEZ supplies are not built from"
                                    " your uploads yet, so those lines show zero. Check them on the GST portal.",
    "buyer_types_unknown": "We do not know whether a buyer is a composition dealer or a UIN holder, so only supplies to"
                           " unregistered buyers are shown by state. Your CA should confirm this.",
    "inter_state_exceeds_taxable": "The inter-state supplies are more than the taxable outward supplies. The GST offline"
                                   " utility checks this too; look at your rows before you enter them.",
}  # fmt: skip


@dataclass(frozen=True)
class InterStateRow:
    """Table 3.2, one place of supply: supplies to unregistered buyers (composition and UIN columns are not known)."""

    pos_state_code: str
    unregistered_taxable: Decimal
    unregistered_igst: Decimal
    source_refs: tuple[str, ...]


@dataclass(frozen=True)
class Outward:
    taxable: Amounts  # 3.1(a)
    taxable_refs: tuple[str, ...]  # the documents behind it, for drill-down
    inter_state: tuple[InterStateRow, ...]  # 3.2, sorted by place of supply
    zero_rate_rows: int  # rows at a 0 rate counted in 3.1(a)
    flags: tuple[str, ...]  # codes in FLAG_TEXT; the ones that touch a figure here
    inter_state_taxable: Decimal  # sum of 3.2, to compare with 3.1(a)
    inter_state_igst: Decimal


def build_outward(builds: Iterable[Gstr1Sections], supplier_state: str) -> Outward:
    """`builds` is every GSTR-1 section set that belongs to the worksheet's period: one for a month, the quarter's own build
    plus its IFF months for a quarterly filer, each document once. `supplier_state` is the business's own state code."""
    taxable = Amounts()
    refs: set[str] = set()
    zero_rate = 0
    notes = False
    tax_by_state: dict[str, Amounts] = {}
    refs_by_state: dict[str, set[str]] = {}

    def to_state(pos: str, amounts: Amounts, row_refs: tuple[str, ...]) -> None:
        if pos == supplier_state:
            return
        tax_by_state[pos] = tax_by_state.get(pos, Amounts()) + amounts
        refs_by_state.setdefault(pos, set()).update(row_refs)

    for build in builds:
        for row in (*build.b2b, *build.b2cl, *build.b2cs):
            taxable += row.amounts
            refs.update(row.source_refs)
            zero_rate += row.rate == 0
        for row in (*build.cdnr, *build.cdnur):
            taxable += row.signed
            refs.update(row.source_refs)
            zero_rate += row.rate == 0
            notes = True
        for row in (*build.b2cl, *build.b2cs):  # unregistered buyers, already net of consumer credit notes
            to_state(row.pos_state_code, row.amounts, row.source_refs)
        for row in build.cdnur:  # notes against large inter-state consumer invoices
            to_state(row.pos_state_code, row.signed, row.source_refs)

    rows = tuple(
        InterStateRow(pos, amounts.taxable_value, amounts.igst, tuple(sorted(refs_by_state[pos])))
        for pos, amounts in sorted(tax_by_state.items())
    )
    inter_taxable = sum((r.unregistered_taxable for r in rows), Decimal())
    inter_igst = sum((r.unregistered_igst for r in rows), Decimal())
    flags = []
    if notes:
        flags.append("note_netting")
    if zero_rate:
        flags.append("zero_rate_rows")
    flags.append("nil_exempt_non_gst_not_built")
    flags.append("buyer_types_unknown")
    if inter_taxable > taxable.taxable_value:
        flags.append("inter_state_exceeds_taxable")
    return Outward(taxable, tuple(sorted(refs)), rows, zero_rate, tuple(flags), inter_taxable, inter_igst)

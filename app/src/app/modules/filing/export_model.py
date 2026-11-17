"""What goes in each table of the GSTR-1 file, as one typed tree (R1-M8 slice 3).

`export_model(build)` turns a `ReturnBuild` into an `ExportModel`: the invoices grouped the way the portal files them, the
rows of each table, the HSN quantity rounded the way the portal takes it. It decides nothing about the format. The JSON
renderer (`render_json.py`) turns this tree into the file; a renderer for the offline tool's Excel template would work
from the same tree if the test upload says the JSON is not accepted. The tree holds no float and no text that a reader of
the file would not see.

Only a monthly GSTR-1 is rendered. A quarterly GSTR-1 and an IFF need a file type and period we have not seen in any sample
(research: `gstr1-offline-json-structure.md` §5.8), so they raise `NotRenderable` with a plain reason.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.modules.business.interface import gstin_state
from platform_common.money import PAISE

from .build import ReturnBuild
from .gstr1 import Amounts
from .periods import month_end

# Tables a build can hold that the file does not carry yet; the screen tells the user to enter them on the portal.
NOT_IN_FILE = ("Table 13 (documents issued)", "Table 14 (tax collected by e-commerce operators)")


class NotRenderable(ValueError):
    """The return cannot be written as a file we have seen the portal's format for. `str()` is the plain reason."""


@dataclass(frozen=True)
class Item:  # one rate of one invoice or note
    rate: Decimal
    amounts: Amounts


@dataclass(frozen=True)
class Invoice:
    number: str
    date: date
    value: Decimal
    pos: str
    items: tuple[Item, ...]


@dataclass(frozen=True)
class Note:
    number: str
    date: date
    value: Decimal
    pos: str
    kind: str  # "C" credit note
    items: tuple[Item, ...]
    ur_type: str | None = None  # CDNUR: "B2CL"


@dataclass(frozen=True)
class Party:  # B2B and CDNR group by the recipient's GSTIN
    gstin: str
    invoices: tuple[Invoice, ...] = ()
    notes: tuple[Note, ...] = ()


@dataclass(frozen=True)
class PlaceGroup:  # B2CL groups by place of supply
    pos: str
    invoices: tuple[Invoice, ...]


@dataclass(frozen=True)
class SmallRow:  # B2CS: one row per place of supply and rate
    pos: str
    rate: Decimal
    intra: bool
    amounts: Amounts


@dataclass(frozen=True)
class HsnLine:
    hsn: str
    uqc: str
    quantity: Decimal  # rounded half up (away from zero on a tie) to 2 decimals here, in the file only: provisional until CA-3
    rate: Decimal
    amounts: Amounts


@dataclass(frozen=True)
class ExportModel:
    gstin: str
    period: str  # MMYYYY
    b2b: tuple[Party, ...] = ()
    b2cl: tuple[PlaceGroup, ...] = ()
    b2cs: tuple[SmallRow, ...] = ()
    cdnr: tuple[Party, ...] = ()
    cdnur: tuple[Note, ...] = ()
    hsn_b2b: tuple[HsnLine, ...] = ()
    hsn_b2c: tuple[HsnLine, ...] = ()

    @property
    def empty(self) -> bool:
        return not any((self.b2b, self.b2cl, self.b2cs, self.cdnr, self.cdnur, self.hsn_b2b, self.hsn_b2c))


def export_model(build: ReturnBuild) -> ExportModel:
    inst = build.instance
    if inst.form != "GSTR1":
        raise NotRenderable("A file for the portal is not available for this return yet.")
    if month_end(inst.period_start) != inst.period_end:
        raise NotRenderable("A file for a quarterly return is not available yet. We will tell you when it is.")
    s = build.sections
    seller_state = gstin_state(inst.gstin)
    return ExportModel(
        gstin=inst.gstin,
        period=f"{inst.period_end:%m%Y}",
        b2b=_parties((r.recipient_gstin, r) for r in s.b2b),
        b2cl=_places(s.b2cl),
        b2cs=tuple(
            SmallRow(r.pos_state_code, r.rate, r.pos_state_code == seller_state, r.amounts)
            for r in sorted(s.b2cs, key=lambda r: (r.pos_state_code, r.rate))
        ),
        cdnr=_note_parties(s.cdnr),
        cdnur=_notes(s.cdnur, with_ur=True),
        hsn_b2b=_hsn(s.hsn_b2b),
        hsn_b2c=_hsn(s.hsn_b2c),
    )


def _items(rows) -> tuple[Item, ...]:
    return tuple(Item(r.rate, r.amounts) for r in sorted(rows, key=lambda r: r.rate))


def _invoices(rows) -> tuple[Invoice, ...]:
    """Rows are one per invoice and rate; an invoice is its number and date, ordered by date then number."""
    by: dict[tuple, list] = {}
    for r in rows:
        by.setdefault((r.invoice_date, r.invoice_number), []).append(r)
    return tuple(
        Invoice(number, day, _same(g, "invoice_value", number), _same(g, "pos_state_code", number), _items(g))
        for (day, number), g in sorted(by.items())
    )


def _same(rows, field: str, number: str):
    """One value for a document whose rows each carry it; rows that disagree are a defect, never picked between."""
    values = {getattr(r, field) for r in rows}
    if len(values) != 1:
        raise NotRenderable(
            f"The rows of {number} do not agree on one value, so no file can be made. We have been told."
        )
    return values.pop()


def _parties(pairs) -> tuple[Party, ...]:
    by: dict[str, list] = {}
    for gstin, r in pairs:
        by.setdefault(gstin, []).append(r)
    return tuple(Party(g, invoices=_invoices(rows)) for g, rows in sorted(by.items()))


def _places(rows) -> tuple[PlaceGroup, ...]:
    by: dict[str, list] = {}
    for r in rows:
        by.setdefault(r.pos_state_code, []).append(r)
    return tuple(PlaceGroup(p, _invoices(g)) for p, g in sorted(by.items()))


def _notes(rows, *, with_ur: bool = False) -> tuple[Note, ...]:
    by: dict[tuple, list] = {}
    for r in rows:
        by.setdefault((r.note_date, r.note_number), []).append(r)
    return tuple(
        Note(number, day, _same(g, "note_value", number), _same(g, "pos_state_code", number), g[0].note_type,
             _items(g), g[0].ur_type if with_ur else None)
        for (day, number), g in sorted(by.items())
    )  # fmt: skip


def _note_parties(rows) -> tuple[Party, ...]:
    by: dict[str, list] = {}
    for r in rows:
        by.setdefault(r.recipient_gstin, []).append(r)
    return tuple(Party(g, notes=_notes(rows)) for g, rows in sorted(by.items()))


def _hsn(rows) -> tuple[HsnLine, ...]:
    return tuple(
        HsnLine(r.hsn, r.uqc, r.quantity.quantize(PAISE, rounding=ROUND_HALF_UP), r.rate, r.amounts)
        for r in sorted(rows, key=lambda r: (r.hsn, r.uqc, r.rate))
    )

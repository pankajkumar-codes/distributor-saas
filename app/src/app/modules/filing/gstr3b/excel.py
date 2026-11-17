"""The GSTR-3B worksheet as an Excel file, in the order of the portal form (utility V5.8 row labels). Pure: it takes the figures
the screen shows and writes them; nothing is computed here except nothing at all (net ITC arrives already worked out).

Every cell is a number (from the stored figures) or text. Text that came from the seller's own files (document numbers) is stored
as a plain string cell and never as a formula, so a number that starts with "=" opens as text. No cell holds a formula.
The file says what it is: "Worksheet, not a filing", the build version, whether it is out of date and when it was made.
"""

from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.worksheet.worksheet import Worksheet

from .entries import net_itc
from .labels import (
    HEAD_NAMES,
    NET_ITC_LABEL,
    OFFSET_NOTE,
    PORTAL_NOTE,
    TABLE_3_1,
    TABLE_3_1_1_NOTE,
    TABLE_4_AVAILABLE,
    TABLE_4_OTHER,
    TABLE_4_REVERSED,
    TABLE_5,
    TABLE_5_1,
    WORKSHEET_LABEL,
    Row,
)
from .worksheet import FLAG_TEXT

HEADS = ("taxable_value", "igst", "cgst", "sgst", "cess")
HEAD_TITLES = {"taxable_value": "Total Taxable Value", **HEAD_NAMES}
NOT_BUILT = "Not built from your uploads yet; check on the GST portal."
MONEY = "0.00"


@dataclass(frozen=True)
class SheetModel:
    gstin: str
    period_label: str
    version: int
    built_at: str  # when the version was built (text)
    generated_at: str
    out_of_date: bool
    outward: dict  # the stored outward of the version (decimal text)
    entries: dict[str, str]  # what the seller typed
    flags: tuple[str, ...]  # codes in FLAG_TEXT


def _text(ws: Worksheet, row: int, col: int, value: str, *, bold: bool = False) -> None:
    c = ws.cell(row=row, column=col, value=value)
    c.data_type = "s"  # never a formula, whatever the text starts with
    c.alignment = Alignment(wrap_text=True, vertical="top")
    if bold:
        c.font = Font(bold=True)


def _num(ws: Worksheet, row: int, col: int, value: str | Decimal | int) -> None:
    c = ws.cell(row=row, column=col, value=Decimal(str(value)))
    c.number_format = MONEY


def _heads_header(ws: Worksheet, row: int, heads: tuple[str, ...]) -> None:
    for i, h in enumerate(heads, 2):
        _text(ws, row, i, HEAD_TITLES[h], bold=True)


def _typed_rows(ws: Worksheet, row: int, table: str, rows: tuple[Row, ...], entries: dict[str, str], heads) -> int:
    for r in rows:
        _text(ws, row, 1, r.label)
        for i, h in enumerate(heads, 2):
            if h in r.heads:
                v = entries.get(f"{table}.{r.key}.{h}")
                if v is not None:
                    _num(ws, row, i, v)
        row += 1
    return row


def render(m: SheetModel) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "GSTR-3B"
    ws.column_dimensions["A"].width = 70
    for col in "BCDEF":
        ws.column_dimensions[col].width = 20
    ws.column_dimensions["G"].width = 50
    r = 1
    _text(ws, r, 1, WORKSHEET_LABEL, bold=True)
    _text(ws, r + 1, 1, PORTAL_NOTE)
    _text(ws, r + 2, 1, f"GSTIN {m.gstin}, period {m.period_label}")
    _text(ws, r + 3, 1, f"Built from your GSTR-1 as version {m.version} on {m.built_at}. File made on {m.generated_at}.")
    r += 4
    if m.out_of_date:
        _text(ws, r, 1, "Out of date: your GSTR-1 has changed since this build. Build the worksheet again before you use it.",
              bold=True)  # fmt: skip
        r += 1
    r += 1

    _text(ws, r, 1, "3.1 Details of Outward Supplies and inward supplies liable to reverse charge", bold=True)
    _heads_header(ws, r, HEADS)
    r += 1
    taxable = m.outward["taxable"]
    for row in TABLE_3_1:
        _text(ws, r, 1, row.label)
        if row.key == "a":
            for i, h in enumerate(HEADS, 2):
                _num(ws, r, i, taxable[h])
        elif row.key == "d":
            for i, h in enumerate(HEADS, 2):
                v = m.entries.get(f"t3_1.d.{h}")
                if v is not None:
                    _num(ws, r, i, v)
        else:
            for i in range(2, 2 + len(HEADS)):
                _num(ws, r, i, 0)
            _text(ws, r, 7, NOT_BUILT)
        r += 1
    _text(ws, r, 1, TABLE_3_1_1_NOTE)
    r += 2

    _text(ws, r, 1, "3.2 Of the supplies shown in 3.1(a), details of inter-State supplies made to unregistered persons", bold=True)
    _text(ws, r, 2, "Place of Supply (State code)", bold=True)
    _text(ws, r, 3, "Total Taxable Value", bold=True)
    _text(ws, r, 4, HEAD_TITLES["igst"], bold=True)
    r += 1
    for s in m.outward["inter_state"]:
        _text(ws, r, 1, "Supplies made to Unregistered Persons")
        _text(ws, r, 2, s["pos_state_code"])
        _num(ws, r, 3, s["unregistered_taxable"])
        _num(ws, r, 4, s["unregistered_igst"])
        r += 1
    _text(ws, r, 1, "Supplies to composition dealers and UIN holders are not known to this worksheet; check on the GST portal.")
    r += 2

    tax4 = ("igst", "cgst", "sgst", "cess")
    _text(ws, r, 1, "4. Eligible ITC (typed by you; the app does not check it)", bold=True)
    _heads_header(ws, r, ("taxable_value", *tax4))
    ws.cell(row=r, column=2).value = None
    r += 1
    _text(ws, r, 1, "(A) ITC Available (whether in full or part)", bold=True)
    r += 1
    r = _typed_rows(ws, r, "t4a", TABLE_4_AVAILABLE, m.entries, ("taxable_value", *tax4))
    _text(ws, r, 1, "(B) ITC Reversed", bold=True)
    r += 1
    r = _typed_rows(ws, r, "t4b", TABLE_4_REVERSED, m.entries, ("taxable_value", *tax4))
    _text(ws, r, 1, NET_ITC_LABEL, bold=True)
    for i, h in enumerate(tax4, 3):
        _num(ws, r, i, net_itc(m.entries)[h])
    r += 1
    _text(ws, r, 1, "(D) Other Details", bold=True)
    r += 1
    r = _typed_rows(ws, r, "t4d", TABLE_4_OTHER, m.entries, ("taxable_value", *tax4))
    r += 1

    _text(ws, r, 1, "5. Values of exempt, nil-rated and non-GST inward supplies", bold=True)
    _text(ws, r, 2, "Inter-State supplies", bold=True)
    _text(ws, r, 3, "Intra-State supplies", bold=True)
    r += 1
    for row in TABLE_5:
        _text(ws, r, 1, row.label)
        for i, h in enumerate(("inter", "intra"), 2):
            v = m.entries.get(f"t5.{row.key}.{h}")
            if v is not None:
                _num(ws, r, i, v)
        r += 1
    r += 1
    _text(ws, r, 1, "5.1 Interest", bold=True)
    _heads_header(ws, r, ("taxable_value", *tax4))
    ws.cell(row=r, column=2).value = None
    r += 1
    r = _typed_rows(ws, r, "t5_1", TABLE_5_1, m.entries, ("taxable_value", *tax4))
    r += 1

    _text(ws, r, 1, OFFSET_NOTE, bold=True)
    r += 2
    if m.flags:
        _text(ws, r, 1, "To be confirmed with your CA", bold=True)
        r += 1
        for code in m.flags:
            _text(ws, r, 1, FLAG_TEXT[code])
            r += 1

    src = wb.create_sheet("Sources")
    src.column_dimensions["A"].width = 40
    src.column_dimensions["B"].width = 40
    _text(src, 1, 1, "Documents behind the figures (from your GSTR-1 build)", bold=True)
    _text(src, 2, 1, "Table")
    _text(src, 2, 2, "Document")
    row = 3
    for ref in m.outward["taxable_refs"]:
        _text(src, row, 1, "3.1(a)")
        _text(src, row, 2, ref)
        row += 1
    for s in m.outward["inter_state"]:
        for ref in s["source_refs"]:
            _text(src, row, 1, f"3.2, place of supply {s['pos_state_code']}")
            _text(src, row, 2, ref)
            row += 1
    out = BytesIO()
    wb.save(out)
    return out.getvalue()

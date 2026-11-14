"""Synthetic own-invoice files for tests (R1-M5): our template's `Invoices` sheet with a `How to fill` sheet
beside it, or the same headers as CSV. Every value is made up."""

import io

import openpyxl

from app.modules.imports.readers.own_excel import COLUMNS

OWN = "19DEMOA1234A1Z5"
OTHER = "27DEMOB5678B1ZH"
HEADERS = [c.header for c in COLUMNS]


def line(number="INV-1", *, gstin=OWN, kind="Invoice", date="03-07-2026", hsn="6109", qty="2", unit="PCS",
         taxable="200", rate="18", state="West Bengal", igst="", cgst="18", sgst="18", cess="", buyer="",
         original="", original_date="", total="236"):
    return {"Seller GSTIN": gstin, "Document type": kind, "Document number": number, "Document date": date,
            "Original invoice number": original, "Original invoice date": original_date, "Buyer GSTIN": buyer,
            "Place of supply": state, "HSN": hsn, "Quantity": qty, "Unit": unit, "Taxable value": taxable,
            "GST rate %": rate, "IGST": igst, "CGST": cgst, "SGST/UTGST": sgst, "Cess": cess,
            "Invoice total": total}


def inter(number="INV-2", **kw):
    return line(number, igst="36", cgst="", sgst="", state="Karnataka", total="236", **kw)


def rows_of(rows, headers=HEADERS):
    return [headers] + [[r.get(h, "") for h in headers] for r in rows]


def workbook(rows, *, headers=HEADERS, sheet="Invoices", help_sheet=True, extra_columns=()) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(list(headers) + [h for h, _ in extra_columns])
    for r in rows:
        ws.append([r.get(h, "") for h in headers] + [v for _, v in extra_columns])
    if help_sheet:
        wb.create_sheet("How to fill").append(["Fill one row per invoice line."])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def csv_bytes(rows, headers=HEADERS) -> bytes:
    import csv

    out = io.StringIO()
    csv.writer(out, lineterminator="\r\n").writerows(rows_of(rows, headers))
    return out.getvalue().encode()


def good() -> bytes:
    return workbook([line("INV-1"), line("INV-1", hsn="6110", taxable="100", cgst="9", sgst="9", total="236"),
                     inter("INV-2"), line("INV-3", buyer="29DEMOC9999C1Z1")])

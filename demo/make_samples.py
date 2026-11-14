"""Builds the sample files for the local demo (docs/LOCAL_DEMO.md). Everything here is made up:
invented GSTINs (the check character is real, the numbers belong to nobody), invented order
ids, invented amounts. Nothing comes from a real seller or a real marketplace report.

    python demo/make_samples.py           # rewrite demo/samples/ (CSV and zip are byte-for-byte stable)

`build()` is also what the tests use, with the test business's own GSTIN, to check each file
does what the guide says it does.
"""

import io
import sys
import zipfile
from pathlib import Path

DEMO_GSTIN = "19DEMOA1234A1Z5"  # the demo business's own (synthetic)
OTHER_GSTIN = "27DEMOB5678B1ZH"  # someone else's (synthetic)
HEAD = "Seller Gstin,Order Id,Txn Type,Qty,Hsn,Amount\n"

GOOD = ("DEMO-1001,Shipment,1,6109,499.00", "DEMO-1002,Shipment,2,6203,2598.00", "DEMO-1003,Shipment,1,3304,350.00",
        "DEMO-1004,Shipment,3,6109,1497.00", "DEMO-1005,Shipment,1,6203,1299.00", "DEMO-1006,Shipment,1,3304,175.50")
HELD = ("DEMO-2001,Shipment,1,6109,499.00", "DEMO-2002,Shipment,2,,998.00", "DEMO-2003,Shipment,,6109,250.00",
        "DEMO-2004,Cancel,1,6109,0.00", "DEMO-2005,Shipment,1,6203,1299.00")
SALES = ("DEMO-3001,Shipment,1,6109,499.00", "DEMO-3002,Shipment,2,3304,700.00", "DEMO-3003,Shipment,1,6203,1299.00")
RETURNS = ("DEMO-3101,Return,1,6109,499.00", "DEMO-3102,Return,1,3304,350.00")


def csv(rows, gstin) -> bytes:
    return (HEAD + "".join(f"{gstin},{r}\n" for r in rows)).encode()


def zipped(files: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))  # fixed, so the zip is stable
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    return out.getvalue()


# The headers of the product's own-invoices template (imports/readers/own_excel.py COLUMNS); a test keeps them equal.
TEMPLATE_HEADERS = ["Seller GSTIN", "Document type", "Document number", "Document date", "Original invoice number",
                    "Original invoice date", "Buyer GSTIN", "Place of supply", "HSN", "Quantity", "Unit",
                    "Taxable value", "GST rate %", "IGST", "CGST", "SGST/UTGST", "Cess", "Invoice total"]


def own_invoices_xlsx(gstin, other=OTHER_GSTIN) -> bytes:
    """Four made-up documents in the template's layout: a sale to a registered buyer, a sale inside West Bengal, a
    sale to Karnataka, and a credit note against the first. Every figure is invented; the rates are only what
    these made-up rows say, not advice."""
    import datetime as dt

    import openpyxl

    def row(kind, number, date, state, taxable, rate, igst, cgst, sgst, total, buyer="", original="", original_date=""):
        return [gstin, kind, number, date, original, original_date, buyer, state, "61091000", 2, "PCS", taxable, rate,
                igst, cgst, sgst, "", total]

    wb = openpyxl.Workbook()
    wb.properties.created = wb.properties.modified = dt.datetime(2026, 1, 1)
    ws = wb.active
    ws.title = "Invoices"
    ws.append(TEMPLATE_HEADERS)
    ws.append(row("Invoice", "DEMO/001", "03-10-2026", "West Bengal", 2000, 5, "", 50, 50, 2100, buyer=other))
    ws.append(row("Invoice", "DEMO/002", "09-10-2026", "West Bengal", 1000, 5, "", 25, 25, 1050))
    ws.append(row("Invoice", "DEMO/003", "12-10-2026", "Karnataka", 800, 5, 40, "", "", 840))
    ws.append(row("Credit note", "DEMO/CN1", "20-10-2026", "West Bengal", 400, 5, "", 10, 10, 420, buyer=other,
                  original="DEMO/001", original_date="03-10-2026"))
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def build(gstin: str = DEMO_GSTIN, other: str = OTHER_GSTIN) -> dict[str, bytes]:
    return {
        "demo-orders-good.csv": csv(GOOD, gstin),
        "demo-orders-held-rows.csv": csv(HELD, gstin),
        "demo-orders-wrong-gstin.csv": csv(GOOD[:3], other),
        "demo-orders-bundle.zip": zipped({"demo-sales.csv": csv(SALES, gstin), "demo-returns.csv": csv(RETURNS, gstin)}),
        "not-a-report.csv": b"Name,Note\nThis is not a report,It has no order columns\n",
        "demo-own-invoices.xlsx": own_invoices_xlsx(gstin),
    }


if __name__ == "__main__":
    target = Path(__file__).resolve().parent / "samples"
    target.mkdir(exist_ok=True)
    for name, data in build().items():
        (target / name).write_bytes(data)
        print("wrote", target / name, len(data), "bytes", file=sys.stderr)

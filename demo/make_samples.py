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


def own_invoices_xlsx(gstin) -> bytes:
    import datetime as dt

    import openpyxl

    wb = openpyxl.Workbook()
    wb.properties.created = wb.properties.modified = dt.datetime(2026, 1, 1)
    ws = wb.active
    ws.title = "Invoices"
    ws.append(["Invoice No", "Invoice Date", "Customer", "Customer GSTIN", "Item", "HSN", "Qty", "Rate", "Taxable Value"])
    ws.append(["DEMO/26/001", "2026-10-03", "Demo Customer One", OTHER_GSTIN, "Cotton shirt", "6109", 4, "499.00", "1996.00"])
    ws.append(["DEMO/26/002", "2026-10-09", "Demo Customer Two", "", "Face wash", "3304", 2, "175.00", "350.00"])
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

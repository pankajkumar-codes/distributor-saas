"""Synthetic Amazon Merchant Tax Report files for tests (platform-reader-spec section 6).

Headers and quirks come from the spec; every value is made up (invented GSTINs, order numbers and
amounts, no names or addresses). Nothing here comes from a real seller. The files carry the spec's
quirks: a UTF-8 BOM, two units of one order on one invoice number, a cancel with a blank invoice number
and no HSN, a refund repeating its sale's invoice number with a credit note number, a free replacement
at zero value, an intra-state month and an inter-state month, and a header that changed spelling."""

import io
import zipfile

OWN = "19DEMOA1234A1Z5"
OTHER = "27DEMOB5678B1ZH"

B2C_HEADERS = [
    "Seller Gstin", "Invoice Number", "Invoice Date", "Transaction Type", "Order Id", "Shipment Id",
    "Shipment Item Id", "Shipment Date", "Order Date", "Quantity", "Hsn/sac", "Ship To State",
    "Ship From State", "Invoice Amount", "Tax Exclusive Gross", "Total Tax Amount", "Cgst Rate", "Sgst Rate",
    "Utgst Rate", "Igst Rate", "Compensatory Cess Rate", "Cgst Tax", "Sgst Tax", "Utgst Tax", "Igst Tax",
    "Compensatory Cess Tax", "Shipping Amount", "Gift Wrap Amount", "Item Promo Discount",
    "Fulfillment Channel", "Payment Method Code", "Credit Note No", "Credit Note Date",
    "Buyer Name", "Ship To Address",  # personal columns the profile does not map: never stored
]
B2B_EXTRA = ["Customer Bill To Gstid", "Customer Ship To Gstid", "Irn Number", "Irn Filing Status", "Irn Date",
             "Irn Error Code"]


def row(headers, **v):
    return [str(v.get(h, "")) for h in headers]


def sale(item, *, gstin=OWN, inv="INV-1", kind="Shipment", qty="1", hsn="6109", state="WEST BENGAL", amount="118.00",
         taxable="100.00", tax="18.00", intra=True, credit="", credit_date=""):
    rates = {"Cgst Rate": "0.09", "Sgst Rate": "0.09", "Utgst Rate": "0.00", "Igst Rate": "0.00",
             "Cgst Tax": str(float(tax) / 2), "Sgst Tax": str(float(tax) / 2), "Igst Tax": "0.00"} if intra else {
             "Cgst Rate": "0.00", "Sgst Rate": "0.00", "Utgst Rate": "0.00", "Igst Rate": "0.18",
             "Cgst Tax": "0.00", "Sgst Tax": "0.00", "Igst Tax": tax}
    return {"Seller Gstin": gstin, "Invoice Number": inv, "Invoice Date": "2026-07-04 10:11:12",
            "Transaction Type": kind, "Order Id": f"ORD-{item}", "Shipment Id": f"SHP-{item}",
            "Shipment Item Id": f"ITEM-{item}", "Shipment Date": "2026-07-04 09:00:00",
            "Order Date": "2026-07-03 08:00:00", "Quantity": qty, "Hsn/sac": hsn, "Ship To State": state,
            "Ship From State": "WEST BENGAL", "Invoice Amount": amount, "Tax Exclusive Gross": taxable,
            "Total Tax Amount": tax, "Compensatory Cess Rate": "0.00", "Compensatory Cess Tax": "0.00",
            "Shipping Amount": "0.00", "Gift Wrap Amount": "0.00", "Item Promo Discount": "0.00",
            "Fulfillment Channel": "AFN", "Payment Method Code": "COD", "Credit Note No": credit,
            "Credit Note Date": credit_date, "Buyer Name": "Made Up Buyer", "Ship To Address": "1 Made Up Lane",
            **rates}


def csv_bytes(headers, rows, *, bom=True) -> bytes:
    import csv

    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow(headers)
    for r in rows:
        w.writerow(row(headers, **r))
    return (("﻿" if bom else "") + out.getvalue()).encode("utf-8")


def b2c_good(gstin=OWN) -> bytes:
    """Two units of one order on one invoice, an inter-state sale, a refund repeating the sale's
    invoice number, a cancel with no invoice number or HSN, and a free replacement at zero value."""
    rows = [
        sale("1", gstin=gstin, inv="INV-1"),
        sale("2", gstin=gstin, inv="INV-1"),  # the second unit of the same order: same invoice number
        sale("3", gstin=gstin, inv="INV-2", intra=False, state="MAHARASHTRA", amount="236.00", taxable="200.00",
             tax="36.00"),
        sale("1", gstin=gstin, inv="INV-1", kind="Refund", amount="-118.00", taxable="-100.00", tax="-18.00",
             credit="CN-1", credit_date="2026-07-20 00:00:00"),
        sale("4", gstin=gstin, inv="", kind="Cancel", hsn="", qty="1", amount="0.00", taxable="0.00", tax="0.00"),
        sale("5", gstin=gstin, inv="INV-3", kind="FreeReplacement", amount="0.00", taxable="0.00", tax="0.00"),
    ]
    return csv_bytes(B2C_HEADERS, rows)


def b2c_held(gstin=OWN) -> bytes:
    rows = [
        sale("10", gstin=gstin, hsn=""),                     # blank_hsn
        sale("11", gstin=gstin, qty=""),                     # blank_qty
        sale("12", gstin=gstin, state=""),                   # unknown_state
        sale("13", gstin=gstin, kind="Exchange"),            # unknown_txn_type
        sale("14", gstin=gstin, kind="Refund"),              # refund with no credit note number: sanity
        {**sale("15", gstin=gstin), "Igst Rate": "0.18", "Igst Tax": "18.00"},  # IGST and CGST on one row: sanity
        sale("16", gstin=gstin, kind="Cancel", amount="50.00"),  # a cancel carrying value: sanity
        sale("17", gstin=gstin),                             # fine
    ]
    return csv_bytes(B2C_HEADERS, rows)


def b2b_good(gstin=OWN) -> bytes:
    headers = B2C_HEADERS + B2B_EXTRA
    rows = [{**sale("20", gstin=gstin), "Customer Bill To Gstid": OTHER, "Customer Ship To Gstid": OTHER,
             "Irn Number": "IRN-MADE-UP", "Irn Filing Status": "FILED", "Irn Date": "2026-07-05 00:00:00"}]
    return csv_bytes(headers, rows)


def renamed_header(content: bytes) -> bytes:
    """The spec's drift: a header that changed spelling must not break a reader that lists both."""
    return content.replace(b"Compensatory Cess Tax", b"Compensatory Cess Tax Amount")


def zipped(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()

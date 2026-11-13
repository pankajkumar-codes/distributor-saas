"""Synthetic Flipkart workbooks for tests (platform-reader-spec section 3): a Help sheet, a Sales Report
sheet and a Cash Back Report sheet, every number written as text, every sheet claiming a one-row size
(the declared-size bug). Headers and quirks come from the spec; every value is made up."""

import io
import re
import zipfile

import openpyxl

OWN = "19DEMOA1234A1Z5"
OTHER = "27DEMOB5678B1ZH"

SALES_HEADERS = [
    "Seller GSTIN", "Order ID", "Order Item ID", "FSN", "SKU", "HSN Code", "Event Type", "Event Sub Type",
    "Order Type", "Fulfilment Type", "Order Date", "Order Approval Date", "Item Quantity",
    "Order Shipped From (State)", "Shipping Charges", "Type of tax",
    "Taxable Value (Final Invoice Amount -Taxes)", "IGST Rate", "IGST Amount", "CGST Rate", "CGST Amount",
    "SGST (or UTGST) Rate", "SGST (or UTGST) Amount", "Total TCS Deducted", "Buyer Invoice ID",
    "Buyer Invoice Date", "Buyer Invoice Amount", "Customer's Delivery State",
    "Customer Name", "Customer's Delivery Address",  # personal: never stored
]
CASHBACK_HEADERS = [
    "Seller GSTIN", "Document Type", "Document Sub Type", "Credit Note ID/ Debit Note ID", "Order Item ID",
    "Invoice Amount", "Invoice Date", "Taxable Value", "IGST Rate", "IGST Amount", "CGST Rate", "CGST Amount",
    "SGST (or UTGST) Rate", "SGST (or UTGST) Amount",
]


def sale(item, *, gstin=OWN, event="Sale", sub="Sale", qty="1.0", hsn="6109", state="West Bengal", intra=True,
         taxable="100.0", invoice="118.0", rate="18.0"):
    half = str(float(rate) / 2)
    tax = str(round(float(taxable) * float(rate) / 100, 2))
    halftax = str(round(float(tax) / 2, 2))
    tax_cols = ({"IGST Rate": "0.0", "IGST Amount": "0.0", "CGST Rate": half, "CGST Amount": halftax,
                 "SGST (or UTGST) Rate": half, "SGST (or UTGST) Amount": halftax} if intra else
                {"IGST Rate": rate, "IGST Amount": tax, "CGST Rate": "0.0", "CGST Amount": "0.0",
                 "SGST (or UTGST) Rate": "0.0", "SGST (or UTGST) Amount": "0.0"})
    return {"Seller GSTIN": gstin, "Order ID": f"OD-{item}", "Order Item ID": f"OI-{item}", "FSN": "FSN1",
            "SKU": "SKU-1", "HSN Code": hsn, "Event Type": event, "Event Sub Type": sub,
            "Order Type": "PREPAID", "Fulfilment Type": "NON_FBF", "Order Date": "2026-07-03 08:00:00",
            "Order Approval Date": "2026-07-03 09:00:00", "Item Quantity": qty,
            "Order Shipped From (State)": "IN-WB", "Shipping Charges": "0.0", "Type of tax": "0",
            "Taxable Value (Final Invoice Amount -Taxes)": taxable, "Total TCS Deducted": "1.0",
            "Buyer Invoice ID": f"BI-{item}", "Buyer Invoice Date": "2026-07-04 10:00:00",
            "Buyer Invoice Amount": invoice, "Customer's Delivery State": state,
            "Customer Name": "Made Up Buyer", "Customer's Delivery Address": "1 Made Up Lane", **tax_cols}


def note(no, *, gstin=OWN, doc="Credit Note", sub="Sale", item="1", date="2026-07-10 00:00:00"):
    return {"Seller GSTIN": gstin, "Document Type": doc, "Document Sub Type": sub,
            "Credit Note ID/ Debit Note ID": no, "Order Item ID": f"OI-{item}", "Invoice Amount": "10.0",
            "Invoice Date": date, "Taxable Value": "8.47", "IGST Rate": "0.0", "IGST Amount": "0.0",
            "CGST Rate": "9.0", "CGST Amount": "0.76", "SGST (or UTGST) Rate": "9.0", "SGST (or UTGST) Amount": "0.76"}


def workbook(sales=(), notes=(), *, sales_headers=SALES_HEADERS, cashback=True, help_sheet=True) -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    if help_sheet:
        wb.create_sheet("Help").append(["How to read this report", "Made-up text"])
    ws = wb.create_sheet("Sales Report")
    ws.append(sales_headers)
    for r in sales:
        ws.append([r.get(h, "") for h in sales_headers])
    if cashback:
        cs = wb.create_sheet("Cash Back Report")
        cs.append(CASHBACK_HEADERS)
        for r in notes:
            cs.append([r.get(h, "") for h in CASHBACK_HEADERS])
    out = io.BytesIO()
    wb.save(out)
    return claim_one_row(out.getvalue())


def claim_one_row(content: bytes) -> bytes:
    """Every sheet declares itself one cell big, as Flipkart's exports do."""
    src, out = zipfile.ZipFile(io.BytesIO(content)), io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            data = src.read(info)
            if info.filename.startswith("xl/worksheets/sheet"):
                data = re.sub(rb'<dimension ref="[^"]*" ?/>', b'<dimension ref="A1"/>', data)
            dst.writestr(info, data)
    return out.getvalue()


def good() -> bytes:
    sales = [
        sale("1"), sale("2", intra=False, state="Maharashtra", taxable="200.0", invoice="236.0"),
        sale("1", event="Return", sub="Return", taxable="-100.0", invoice="-118.0"),
        sale("3", sub="Cancellation", taxable="0.0", invoice="0.0", hsn=""),
    ]
    return workbook(sales, [note("CN-1"), note("DN-1", doc="Debit Note", sub="Return", item="2")])


def held() -> bytes:
    sales = [
        sale("10", hsn=""), sale("11", qty=""), sale("12", state=""), sale("13", sub="Reversal"),
        sale("14", rate="180.0", intra=False), sale("15", sub="Cancellation"),
        {**sale("16"), "IGST Rate": "18.0", "IGST Amount": "18.0"}, sale("17"),
    ]
    return workbook(sales)

"""Synthetic Meesho TCS workbooks for tests (platform-reader-spec section 4): one sheet named after the
supplier id, every value text, missing dates the text `null`, long fractional values, an adjustment row
with quantity 0 and a negative value, and no row id. Every value is made up."""

import io

import openpyxl

from .flipkart import claim_one_row

OWN = "19DEMOA1234A1Z5"
OTHER = "27DEMOB5678B1ZH"

SALES_HEADERS = [
    "identifier", "sup_name", "gstin", "sub_order_num", "order_date", "hsn_code", "quantity", "gst_rate",
    "total_taxable_sale_value", "tax_amount", "total_invoice_value", "taxable_shipping",
    "end_customer_state_new", "enrollment_no", "manifest_date", "transaction_type", "eco_tcs_gstin",
    "financial_year", "month_number", "supplier_id",
]
RETURN_HEADERS = SALES_HEADERS + ["cancel_return_date"]


def sale(order, *, gstin=OWN, qty="1", hsn="6109", state="WEST BENGAL", taxable="170.33898305084747",
         tax="30.66101694915254", invoice="201.0", rate="18.00", manifest="2026-07-04 00:00:00",
         order_date="2026-07-03 00:00:00", **extra):
    return {"identifier": "ID-1", "sup_name": "Made Up Supplier", "gstin": gstin, "sub_order_num": f"SO-{order}_1",
            "order_date": order_date, "hsn_code": hsn, "quantity": qty, "gst_rate": rate,
            "total_taxable_sale_value": taxable, "tax_amount": tax, "total_invoice_value": invoice,
            "taxable_shipping": "10.0", "end_customer_state_new": state, "enrollment_no": "ENR-1",
            "manifest_date": manifest, "transaction_type": "", "eco_tcs_gstin": "29DEMOC9999C1Z1",
            "financial_year": "2026-27", "month_number": "7", "supplier_id": "9999", **extra}


def adjustment(order, **kw):
    """A price adjustment: quantity 0, a negative taxable value, and the text `null` for the manifest date."""
    return sale(order, qty="0", taxable="-8.47", tax="-1.53", invoice="-10.0", manifest="null", **kw)


def workbook(rows, *, headers=SALES_HEADERS, sheet="9999") -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(headers)
    for r in rows:
        ws.append([r.get(h, "") for h in headers])
    out = io.BytesIO()
    wb.save(out)
    return claim_one_row(out.getvalue())


def sales_good() -> bytes:
    return workbook([sale("1"), sale("2", rate="5.00", taxable="190.47619047619048", tax="9.523809523809524",
                                     invoice="200.0"), adjustment("2")])


def returns_good() -> bytes:
    return workbook([sale("1", **{"cancel_return_date": "2026-07-20 00:00:00"})], headers=RETURN_HEADERS)

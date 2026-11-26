"""The finalized-invoice template (render input v1, template "invoice-document").

Written by app.modules.sales.document_pdf from the stored, insert-only document, never from
live profile, customer or product data. The fields follow team/gst/document-fields.md §1
(CGST Rule 46) so far as the document has them. Until live numbering is approved (the CA
confirms the scope, D-010), every document is a practice document, and the page says so at
the top and in a box: "PRACTICE INVOICE, NOT A TAX INVOICE". A document that is not a
practice one is refused here, so a live "Tax Invoice" page cannot be made before its
template has been approved.

    {"v": 1, "template": "invoice-document", "practice": true,
     "number": str, "doc_date": str, "due_date"?: str,
     "seller": {"name", "trade_name"?, "gstin"?, "address": [str], "state"},
     "buyer": {"name"?, "gstin"?, "address": [str], "state"?},
     "ship_to": {"address": [str], "state"?} | null,
     "place_of_supply": str, "reverse_charge": str,
     "lines": [{"no", "description", "hsn"?, "quantity", "uqc", "unit_price", "gross", "discount"?,
                "taxable", "taxes": [{"component", "rate", "amount"}], "total"}],
     "charges": [{"label", "amount"}], "invoice_discount"?,
     "totals": {"taxable", "taxes": [{"component", "amount"}], "round_off"?, "total", "in_words"}}

Every value is a string, goes through `_t` (escaped, nothing placed in an attribute or style),
and the template does no arithmetic.
"""

from .template import MAX_LINES, _bill_to, _list, _obj, _party, _t

PRACTICE_TITLE = "PRACTICE INVOICE, NOT A TAX INVOICE"
PRACTICE_NOTICE = (
    "This is a practice document. It is not a tax invoice and its number is not a legal invoice number. "
    "Do not give it to a customer as an invoice."
)

STYLE = """
@page { size: A4; margin: 12mm }
body { font-family: "Noto Sans", "Noto Sans Devanagari", "Noto Sans Bengali"; font-size: 8.5pt; color: #000 }
h1 { font-size: 14pt; margin: 0 0 2mm }
.practice { border: 1.5pt solid #000; padding: 2mm; font-weight: bold; text-align: center; margin-bottom: 3mm }
.parties { width: 100%; border-collapse: collapse; margin-bottom: 3mm }
.parties td { vertical-align: top; width: 50%; padding: 1mm }
.shipto { margin: 2mm 0 0 }
table.lines { width: 100%; border-collapse: collapse }
table.lines th, table.lines td { border: 0.5pt solid #555; padding: 1mm }
td.n { text-align: right; white-space: nowrap }
.totals { margin-top: 3mm; width: 60%; margin-left: 40%; border-collapse: collapse }
.totals td { padding: 0.8mm }
"""

HEAD = ["#", "Description", "HSN", "Qty", "Rate", "Value", "Discount", "Taxable value", "Tax", "Total"]


def _row(ln) -> str:
    ln = _obj(ln) or {}
    taxes = "<br>".join(
        f"{_t(x.get('component'), optional=False)} {_t(x.get('rate'), optional=False)}%: "
        f"{_t(x.get('amount'), optional=False)}"
        for x in map(_obj, _list(ln.get("taxes"), 4)) if x is not None
    )
    return (
        "<tr>"
        f'<td class="n">{_t(ln.get("no"), optional=False)}</td>'
        f"<td>{_t(ln.get('description'), optional=False)}</td>"
        f"<td>{_t(ln.get('hsn'))}</td>"
        f'<td class="n">{_t(ln.get("quantity"), optional=False)} {_t(ln.get("uqc"))}</td>'
        f'<td class="n">{_t(ln.get("unit_price"), optional=False)}</td>'
        f'<td class="n">{_t(ln.get("gross"), optional=False)}</td>'
        f'<td class="n">{_t(ln.get("discount"))}</td>'
        f'<td class="n">{_t(ln.get("taxable"), optional=False)}</td>'
        f'<td class="n">{taxes}</td>'
        f'<td class="n">{_t(ln.get("total"), optional=False)}</td>'
        "</tr>"
    )


def render_html(doc: dict) -> str:
    """The whole page for one render input. Raises ValueError on a malformed input."""
    if _obj(doc) is None or doc.get("v") != 1 or doc.get("template") != "invoice-document":
        raise ValueError("not an invoice-document render input v1")
    if doc.get("practice") is not True:
        raise ValueError("only practice invoices can be rendered until live numbering is approved")
    totals = _obj(doc.get("totals"))
    if totals is None:
        raise ValueError("an invoice needs its totals")
    out = [
        '<!doctype html><html lang="en"><meta charset="utf-8">',
        f"<style>{STYLE}</style><body>",
        f"<h1>{PRACTICE_TITLE}</h1>",
        f'<div class="practice">{PRACTICE_NOTICE}</div>',
        '<table class="parties"><tr>',
        _party("Seller", _obj(doc.get("seller"))),
        _bill_to(_obj(doc.get("buyer")), _obj(doc.get("ship_to"))),
        "</tr></table>",
        "<p>",
        f"Practice number: {_t(doc.get('number'), optional=False)}<br>",
        f"Date: {_t(doc.get('doc_date'), optional=False)}<br>",
    ]
    if doc.get("due_date"):
        out.append(f"Due date: {_t(doc.get('due_date'))}<br>")
    out += [
        f"Place of supply: {_t(doc.get('place_of_supply'), optional=False)}<br>",
        f"Reverse charge: {_t(doc.get('reverse_charge'), optional=False)}",
        "</p>",
    ]
    out.append('<table class="lines"><tr>' + "".join(f"<th>{h}</th>" for h in HEAD) + "</tr>")
    out += [_row(ln) for ln in _list(doc.get("lines"), MAX_LINES)]
    out.append("</table>")
    rows = [(_t(c.get("label"), optional=False), _t(c.get("amount"), optional=False))
            for c in map(_obj, _list(doc.get("charges"), 20)) if c is not None]
    if doc.get("invoice_discount") not in (None, "0", "0.00"):
        rows.append(("Invoice discount", _t(doc.get("invoice_discount"))))
    rows.append(("Taxable value", _t(totals.get("taxable"), optional=False)))
    rows += [(_t(x.get("component"), optional=False), _t(x.get("amount"), optional=False))
             for x in map(_obj, _list(totals.get("taxes"), 4)) if x is not None]
    if totals.get("round_off"):
        rows.append(("Round off", _t(totals.get("round_off"))))
    rows.append(("<b>Total</b>", f"<b>{_t(totals.get('total'), optional=False)}</b>"))
    out.append('<table class="totals">' + "".join(
        f'<tr><td>{label}</td><td class="n">{amount}</td></tr>' for label, amount in rows) + "</table>")
    if totals.get("in_words"):
        out.append(f"<p>Amount in words: {_t(totals.get('in_words'))}</p>")
    out.append("</body></html>")
    return "".join(out)

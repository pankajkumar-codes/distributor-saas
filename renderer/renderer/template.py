"""The invoice-draft template (render input v1). A plain placeholder: the Junior styles it
later. The fields follow team/gst/document-fields.md §1 so far as a draft has them.

Every value printed comes from the render input, and every one goes through `_t`, which
HTML-escapes it and refuses anything that is not a string. Nothing from the input is
ever placed in an attribute, a URL, a style or a tag name, so a field holding
`<img src=...>` or `url(...)` prints as text. The renderer also fetches nothing
(handler.DenyAllFetcher), so this is the second of two locks, not the only one.

Render input v1, template "invoice-draft" (written by app.modules.sales.preview):

    {"v": 1, "template": "invoice-draft",
     "seller": {"name", "trade_name"?, "gstin"?, "address": [str], "state"},
     "buyer": {"name"?, "gstin"?, "address": [str], "state"?} | null,
     "ship_to": {"address": [str], "state"?} | null,
     "doc_date"?, "place_of_supply"?, "reverse_charge",
     "lines": [{"no", "description", "hsn"?, "quantity", "uqc", "unit_price", "discount"?,
                "taxable"?, "rate"?, "taxes"?: [{"component", "rate", "amount"}], "total"?}],
     "charges": [{"label", "amount"}], "invoice_discount"?,
     "totals": {"taxable", "taxes": [{"component", "amount"}], "round_off"?, "total",
                "in_words"} | null,
     "blocks"?: [str],  # what still stops a finalize, printed under "Before you can finalize"
     "note"?}

Amounts arrive as decimal strings already formatted; the template never does arithmetic.
"""

import html

MAX_TEXT = 500
MAX_LINES = 200
MAX_LIST = 50

STYLE = """
@page { size: A4; margin: 12mm }
body { font-family: "Noto Sans", "Noto Sans Devanagari", "Noto Sans Bengali"; font-size: 9pt; color: #000 }
h1 { font-size: 14pt; margin: 0 0 2mm }
.draft { border: 1pt solid #000; padding: 1.5mm; font-size: 7pt; text-align: center; margin-bottom: 3mm }
.parties { width: 100%; border-collapse: collapse; margin-bottom: 3mm }
.parties td { vertical-align: top; width: 50%; padding: 1mm }
table.lines { width: 100%; border-collapse: collapse }
table.lines th, table.lines td { border: 0.5pt solid #555; padding: 1mm }
td.n { text-align: right; white-space: nowrap }
.totals { margin-top: 3mm; width: 60%; margin-left: 40%; border-collapse: collapse }
.totals td { padding: 0.8mm }
.note { margin-top: 4mm; font-style: italic }
.blocks { margin-top: 4mm; border: 0.5pt solid #000; padding: 1.5mm }
"""


def _t(value, *, optional: bool = True) -> str:
    """One field, escaped. None prints as nothing; anything but a string is refused."""
    if value is None and optional:
        return ""
    if not isinstance(value, str):
        raise ValueError("render input fields must be strings")
    if len(value) > MAX_TEXT:
        raise ValueError("render input field too long")
    return html.escape(value, quote=True)


def _list(value, limit: int = MAX_LIST) -> list:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError("render input list invalid or too long")
    return value


def _obj(value) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("render input object expected")
    return value


def _party(title: str, p: dict | None) -> str:
    if p is None:
        return f"<td><b>{_t(title)}</b><br>Not chosen yet</td>"
    rows = [f"<b>{_t(title)}</b>"]
    if p.get("name"):
        rows.append(f"<b>{_t(p.get('name'))}</b>")
    if p.get("trade_name"):
        rows.append(_t(p.get("trade_name")))
    rows += [_t(line) for line in _list(p.get("address"), 6)]
    if p.get("state"):
        rows.append(f"State: {_t(p.get('state'))}")
    rows.append(f"GSTIN: {_t(p.get('gstin')) or 'Unregistered'}")
    return "<td>" + "<br>".join(rows) + "</td>"


def _line(ln: dict, with_tax: bool) -> str:
    ln = _obj(ln) or {}
    cells = [
        f'<td class="n">{_t(ln.get("no"), optional=False)}</td>',
        f"<td>{_t(ln.get('description'), optional=False)}</td>",
        f"<td>{_t(ln.get('hsn'))}</td>",
        f'<td class="n">{_t(ln.get("quantity"), optional=False)} {_t(ln.get("uqc"))}</td>',
        f'<td class="n">{_t(ln.get("unit_price"), optional=False)}</td>',
        f'<td class="n">{_t(ln.get("discount"))}</td>',
    ]
    if with_tax:
        taxes = "<br>".join(
            f"{_t(x.get('component'), optional=False)} {_t(x.get('rate'), optional=False)}%: "
            f"{_t(x.get('amount'), optional=False)}"
            for x in map(_obj, _list(ln.get("taxes"), 4)) if x is not None
        )
        cells += [f'<td class="n">{_t(ln.get("taxable"))}</td>', f'<td class="n">{taxes}</td>',
                  f'<td class="n">{_t(ln.get("total"))}</td>']
    return "<tr>" + "".join(cells) + "</tr>"


def render_html(doc: dict) -> str:
    """The whole page for one render input. Raises ValueError on a malformed input."""
    if _obj(doc) is None or doc.get("v") != 1 or doc.get("template") != "invoice-draft":
        raise ValueError("not an invoice-draft render input v1")
    totals = _obj(doc.get("totals"))
    lines = _list(doc.get("lines"), MAX_LINES)
    head = ["#", "Description", "HSN", "Qty", "Rate", "Discount"]
    if totals is not None:
        head += ["Taxable value", "Tax", "Total"]
    out = [
        '<!doctype html><html lang="en"><meta charset="utf-8">',
        f"<style>{STYLE}</style><body>",
        "<h1>Draft, not a tax invoice</h1>",
        '<div class="draft">No invoice number until you finalize. Do not give this to a customer as an invoice.</div>',
        '<table class="parties"><tr>',
        _party("Seller", _obj(doc.get("seller"))),
        _party("Bill to", _obj(doc.get("buyer"))),
        "</tr></table>",
        "<p>",
        f"Date: {_t(doc.get('doc_date')) or 'not set'}<br>",
        f"Place of supply: {_t(doc.get('place_of_supply')) or 'not known yet'}<br>",
        f"Reverse charge: {_t(doc.get('reverse_charge')) or 'No'}",
        "</p>",
    ]
    ship = _obj(doc.get("ship_to"))
    if ship is not None:
        address = "<br>".join(_t(line) for line in _list(ship.get("address"), 6))
        state = f"<br>State: {_t(ship.get('state'))}" if ship.get("state") else ""
        out.append(f"<p><b>Ship to</b><br>{address}{state}</p>")
    out.append('<table class="lines"><tr>' + "".join(f"<th>{h}</th>" for h in head) + "</tr>")
    out += [_line(ln, totals is not None) for ln in lines]
    out.append("</table>")
    rows = [(_t(c.get("label"), optional=False), _t(c.get("amount"), optional=False))
            for c in map(_obj, _list(doc.get("charges"), 20)) if c is not None]
    if doc.get("invoice_discount") not in (None, "0", "0.00"):
        rows.append(("Invoice discount", _t(doc.get("invoice_discount"))))
    if totals is not None:
        rows.append(("Taxable value", _t(totals.get("taxable"), optional=False)))
        rows += [(_t(x.get("component"), optional=False), _t(x.get("amount"), optional=False))
                 for x in map(_obj, _list(totals.get("taxes"), 4)) if x is not None]
        if totals.get("round_off"):
            rows.append(("Round off", _t(totals.get("round_off"))))
        rows.append(("<b>Total</b>", f"<b>{_t(totals.get('total'), optional=False)}</b>"))
    if rows:
        out.append('<table class="totals">' + "".join(
            f'<tr><td>{label}</td><td class="n">{amount}</td></tr>' for label, amount in rows) + "</table>")
    if totals is not None and totals.get("in_words"):
        out.append(f"<p>Amount in words: {_t(totals.get('in_words'))}</p>")
    blocks = [_t(b, optional=False) for b in _list(doc.get("blocks"))]
    if blocks:
        out.append('<div class="blocks"><b>Before you can finalize</b><ul>'
                   + "".join(f"<li>{b}</li>" for b in blocks) + "</ul></div>")
    if doc.get("note"):
        out.append(f'<p class="note">{_t(doc.get("note"))}</p>')
    out.append("</body></html>")
    return "".join(out)

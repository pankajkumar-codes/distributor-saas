"""The finalized-invoice template (render input v1, template "invoice-document").

Written by app.modules.sales.document_pdf from the stored, insert-only document, never from
live profile, customer or product data. The fields follow team/gst/document-fields.md §1
(CGST Rule 46) so far as the document has them. Until live numbering is approved (the CA
confirms the scope, D-010), every document is a practice document, and the page says so at
the top, in a box and in a PRACTICE watermark on every page: "PRACTICE INVOICE, NOT A TAX
INVOICE". A document that is not a practice one is refused here, so a live "Tax Invoice" page
cannot be made before its template has been approved.

Layout (#450, LLM council 2026-11-26, D-112): title and copy label; Seller | Bill to (Ship to
under it); the invoice details; the line table (template.LINE_HEAD: # Description HSN Qty MRP
Rate Value Discount Taxable value Tax Total, headings repeated on every page); then, kept
together on the last page, the tax summary by HSN and rate, the totals, "Amount payable" in
the largest type, the amount in words and the signatory block. "Page x of y" and the copy label
sit in every page's footer. With `copies` (#454, Rule 48(1)) the same page set is made once per copy label, each
numbered on its own, and the handler joins them into one PDF.

A credit note (#456, CGST Rule 53(1A)) is the same layout with `note`: the title says credit note, the details name
the original invoice's number and date and the reason, the last line reads "Credit amount", and its copies are
NOTE_COPY_LABELS (original and duplicate; the triplicate for the transporter is an invoice rule, Rule 48(1)).

    {"v": 1, "template": "invoice-document", "practice": true,
     "note"?: {"kind": "credit_note", "original_number": str, "original_date": str, "reason": str},
     "number": str, "doc_date": str, "due_date"?: str, "copy_label"?: str, "copies"?: [str],
     "seller": {"name", "trade_name"?, "gstin"?, "pan"?, "address": [str], "state"},
     "buyer": {"name"?, "gstin"?, "address": [str], "state"?},
     "ship_to": {"name"?, "address": [str], "state"?} | null,
     "place_of_supply": str, "reverse_charge": str,
     "lines": [{"no", "description", "hsn"?, "quantity", "uqc", "mrp"?, "unit_price", "gross", "discount"?,
                "discount_percent"?, "taxable", "taxes": [{"component", "rate", "amount"}], "total"}],
     "hsn_summary"?: [{"hsn", "rate", "taxable", "taxes": [{"component", "amount"}]}],
     "charges": [{"label", "amount"}], "invoice_discount"?,
     "totals": {"taxable", "taxes": [{"component", "amount"}], "round_off"?, "total", "in_words"}}

Every value is a string, goes through `_t` (escaped, nothing placed in an attribute or style),
and the template does no arithmetic.
"""

from .template import LINE_STYLE, MAX_LINES, _bill_to, _lines_table, _list, _obj, _party, _t

PRACTICE_TITLE = "PRACTICE INVOICE, NOT A TAX INVOICE"
PRACTICE_NOTICE = (
    "This is a practice document. It is not a tax invoice and its number is not a legal invoice number. "
    "Do not give it to a customer as an invoice."
)
PRACTICE_NOTE_TITLE = "PRACTICE CREDIT NOTE, NOT A TAX DOCUMENT"
PRACTICE_NOTE_NOTICE = (
    "This is a practice document. It is not a credit note under GST and its number is not a legal number. "
    "Do not give it to a customer as a credit note."
)
COPY_LABEL = "Original for Recipient"
# CGST Rule 48(1): a goods invoice is prepared in triplicate, each copy marked (#454). A document's PDF carries
# every copy in `copies`, in this order; each copy is its own page set with its own "Page x of y" (handler.render_pdfs).
COPY_LABELS = ("Original for Recipient", "Duplicate for Transporter", "Triplicate for Supplier")
NOTE_COPY_LABELS = ("Original for Recipient", "Duplicate for Supplier")

# The @page footer strings are fixed text here, never input: CSS content is not escaped by `_t`.
STYLE = """
@page { size: A4; margin: 10mm 10mm 14mm;
  @bottom-left { content: string(copylabel); font: 7pt "Noto Sans"; color: #444 }
  @bottom-right { content: "Page " counter(page) " of " counter(pages); font: 7pt "Noto Sans"; color: #444 } }
body { font-family: "Noto Sans", "Noto Sans Devanagari", "Noto Sans Bengali"; font-size: 8pt; color: #000 }
.wm { position: fixed; top: 110mm; left: 15mm; width: 160mm; text-align: center; font-size: 80pt; font-weight: bold;
  color: #000; opacity: 0.06; transform: rotate(-35deg) }
.top { width: 100%; border-collapse: collapse; margin-bottom: 2mm }
.top td { padding: 0; vertical-align: bottom }
h1 { font-size: 13pt; margin: 0 }
.copy { text-align: right; font-size: 8pt; color: #444; string-set: copylabel content() }
.practice { border: 1.5pt solid #000; padding: 1.5mm; font-weight: bold; text-align: center; margin-bottom: 3mm }
.parties { width: 100%; border-collapse: collapse; margin-bottom: 2mm }
.parties td { vertical-align: top; width: 50%; padding: 1.5mm; border: 0.5pt solid #555 }
.shipto { margin: 2mm 0 0 }
.details { width: 100%; border-collapse: collapse; margin-bottom: 3mm }
.details td { vertical-align: top; width: 50%; padding: 0 1.5mm }
.end { page-break-inside: avoid; margin-top: 3mm }
.end > table { width: 100%; border-collapse: collapse }
.end > table > tbody > tr > td { vertical-align: top; padding: 0 }
.hsn { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; font-size: 7.5pt }
.hsn th, .hsn td { border: 0.5pt solid #555; padding: 0.8mm }
.hsn th { background: #eee; text-align: left }
.hsn caption { text-align: left; font-weight: bold; padding-bottom: 1mm }
.totals { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums }
.totals td { padding: 0.8mm 1.5mm }
td.n, th.n { text-align: right; white-space: nowrap }
.payable { margin-top: 2mm; border-top: 1pt solid #000; padding-top: 1.5mm; font-size: 13pt; font-weight: bold;
  text-align: right }
.words { margin: 2mm 0 }
.sign { margin-top: 3mm; text-align: right }
.sign .space { height: 12mm }
"""


def _note(doc: dict) -> dict | None:
    """The credit-note part of the input, or None for an invoice. Only credit notes are known kinds."""
    if doc.get("note") is None:
        return None
    note = _obj(doc.get("note"))
    if note is None or note.get("kind") != "credit_note":
        raise ValueError("unknown note kind")
    return note


def _labels(doc: dict) -> tuple[str, ...]:
    return NOTE_COPY_LABELS if _note(doc) is not None else COPY_LABELS


def _copy_label(doc: dict) -> str:
    """The copy this page set is: one of the labels for its kind, never free text (it is also the page footer)."""
    label = doc.get("copy_label") or COPY_LABEL
    if label not in _labels(doc):
        raise ValueError("unknown copy label")
    return label


def render_copies(doc: dict) -> list[str]:
    """One page per copy the input asks for (`copies`, a list of COPY_LABELS), else the single copy in `copy_label`."""
    copies = _list(doc.get("copies"), len(COPY_LABELS)) if isinstance(doc, dict) else []
    if not copies:
        return [render_html(doc)]
    if len(set(copies)) != len(copies) or any(c not in _labels(doc) for c in copies):
        raise ValueError("copies must be distinct copy labels")
    return [render_html({**doc, "copy_label": c, "copies": None}) for c in copies]


def _seller(p: dict | None) -> str:
    """The seller cell with its PAN under the GSTIN, when the input has one."""
    cell = _party("Seller", p)
    if p is None or not p.get("pan"):
        return cell
    return cell[: -len("</td>")] + f"<br>PAN: {_t(p.get('pan'))}</td>"


def _hsn_summary(rows: list) -> str:
    """The tax summary by HSN and rate, as the document builder summed it from the stored lines."""
    rows = [r for r in map(_obj, rows) if r is not None]
    if not rows:
        return ""
    heads = []
    for r in rows:
        for x in map(_obj, _list(r.get("taxes"), 4)):
            if x is not None and x.get("component") not in heads:
                heads.append(_t(x.get("component"), optional=False))
    out = ['<table class="hsn"><caption>Tax summary by HSN</caption><tr><th>HSN</th><th class="n">GST rate</th>'
           '<th class="n">Taxable value</th>' + "".join(f'<th class="n">{h}</th>' for h in heads) + "</tr>"]
    for r in rows:
        amounts = {_t(x.get("component"), optional=False): _t(x.get("amount"), optional=False)
                   for x in map(_obj, _list(r.get("taxes"), 4)) if x is not None}
        out.append(f"<tr><td>{_t(r.get('hsn')) or '–'}</td><td class=\"n\">{_t(r.get('rate'), optional=False)}%</td>"
                   f"<td class=\"n\">{_t(r.get('taxable'), optional=False)}</td>"
                   + "".join(f'<td class="n">{amounts.get(h, "–")}</td>' for h in heads) + "</tr>")
    out.append("</table>")
    return "".join(out)


def render_html(doc: dict) -> str:
    """The whole page for one render input. Raises ValueError on a malformed input."""
    if _obj(doc) is None or doc.get("v") != 1 or doc.get("template") != "invoice-document":
        raise ValueError("not an invoice-document render input v1")
    if doc.get("practice") is not True:
        raise ValueError("only practice invoices can be rendered until live numbering is approved")
    totals = _obj(doc.get("totals"))
    if totals is None:
        raise ValueError("an invoice needs its totals")
    seller = _obj(doc.get("seller"))
    note = _note(doc)
    details_left = [f"Practice number: {_t(doc.get('number'), optional=False)}",
                    f"Date: {_t(doc.get('doc_date'), optional=False)}"]
    if doc.get("due_date") and note is None:
        details_left.append(f"Due date: {_t(doc.get('due_date'))}")
    details_right = [f"Place of supply: {_t(doc.get('place_of_supply'), optional=False)}",
                     f"Reverse charge: {_t(doc.get('reverse_charge'), optional=False)}"]
    if note is not None:
        details_left.append(f"Against invoice: {_t(note.get('original_number'), optional=False)}"
                            f" dated {_t(note.get('original_date'), optional=False)}")
        details_right.append(f"Reason: {_t(note.get('reason'), optional=False)}")
    out = [
        '<!doctype html><html lang="en"><meta charset="utf-8">',
        f"<style>{STYLE}{LINE_STYLE}</style><body>",
        '<div class="wm">PRACTICE</div>',
        f'<table class="top"><tr><td><h1>{PRACTICE_NOTE_TITLE if note else PRACTICE_TITLE}</h1></td>'
        f'<td class="copy">{_t(_copy_label(doc))}</td></tr></table>',
        f'<div class="practice">{PRACTICE_NOTE_NOTICE if note else PRACTICE_NOTICE}</div>',
        '<table class="parties"><tr>',
        _seller(seller),
        _bill_to(_obj(doc.get("buyer")), _obj(doc.get("ship_to"))),
        "</tr></table>",
        '<table class="details"><tr><td>' + "<br>".join(details_left) + "</td><td>"
        + "<br>".join(details_right) + "</td></tr></table>",
        _lines_table(_list(doc.get("lines"), MAX_LINES), True),
    ]
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
    totals_html = '<table class="totals">' + "".join(
        f'<tr><td>{label}</td><td class="n">{amount}</td></tr>' for label, amount in rows) + "</table>"
    summary = _hsn_summary(_list(doc.get("hsn_summary"), MAX_LINES))
    out.append('<div class="end"><table><tr>'
               f'<td style="width: 58%">{summary}</td><td style="width: 4%"></td>'
               f'<td style="width: 38%">{totals_html}'
               f'<div class="payable">{"Credit amount" if note else "Amount payable"} ₹ {_t(totals.get("total"), optional=False)}</div></td>'
               "</tr></table>")
    if totals.get("in_words"):
        out.append(f'<p class="words">Amount in words: {_t(totals.get("in_words"))}</p>')
    name = _t((seller or {}).get("name"))
    out.append(f'<div class="sign">For {name}<div class="space"></div>Authorised Signatory</div></div>')
    out.append("</body></html>")
    return "".join(out)

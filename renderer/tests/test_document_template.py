"""The invoice-document template: a practice invoice from the stored document, plainly marked, every
value escaped, bounded input, no live invoice until its template is approved."""

import pytest

from renderer import document_template, template


def doc(**over):
    base = {
        "v": 1, "template": "invoice-document", "practice": True, "number": "PR-0001", "doc_date": "2026-11-18",
        "seller": {"name": "Test Traders LLP", "gstin": "19AAPFU0939F1ZS", "address": ["1 Test Road"], "state": "West Bengal (19)"},
        "buyer": {"name": "Sharma Stores", "gstin": "27AAPFU0939F1ZV", "address": ["12 MG Road"], "state": "Maharashtra (27)"},
        "ship_to": None, "place_of_supply": "Maharashtra (27)", "reverse_charge": "No",
        "lines": [{"no": "1", "description": "Neem soap", "hsn": "340111", "quantity": "2.5", "uqc": "PCS",
                   "unit_price": "45.50", "gross": "113.75", "discount": None, "taxable": "113.75",
                   "taxes": [{"component": "IGST", "rate": "18", "amount": "20.48"}], "total": "134.23"}],
        "charges": [], "invoice_discount": None,
        "totals": {"taxable": "113.75", "taxes": [{"component": "IGST", "amount": "20.48"}], "round_off": None,
                   "total": "134.23", "in_words": "One hundred thirty-four rupees and twenty-three paise only"},
    }  # fmt: skip
    return {**base, **over}


def test_the_page_says_practice_not_a_tax_invoice_and_prints_the_rule_46_fields():
    html = template.render_html(doc())  # dispatched by the template name
    assert html == document_template.render_html(doc())
    assert "PRACTICE INVOICE, NOT A TAX INVOICE" in html and "not a tax invoice" in html
    assert "Do not give it to a customer as an invoice." in html
    assert html.index("PRACTICE INVOICE") < html.index("Test Traders LLP")  # said before anything else
    for text in ("Practice number: PR-0001", "Date: 2026-11-18", "Place of supply: Maharashtra (27)", "Reverse charge: No",
                 "19AAPFU0939F1ZS", "27AAPFU0939F1ZV", "340111", "2.5 PCS", "45.50", "113.75", "IGST 18%: 20.48", "134.23",
                 "Amount in words: One hundred thirty-four rupees"):  # fmt: skip
        assert text in html
    assert "Tax Invoice" not in html.replace("not a tax invoice", "").replace("NOT A TAX INVOICE", "")


@pytest.mark.parametrize("practice", [False, None, "yes", 1])
def test_a_document_that_is_not_a_practice_one_is_refused(practice):
    with pytest.raises(ValueError, match="practice"):
        template.render_html(doc(practice=practice))


@pytest.mark.parametrize("field", ["number", "place_of_supply", "reverse_charge", "seller", "buyer", "lines", "charges"])
def test_every_value_is_escaped_and_nothing_becomes_markup(field):
    evil = '<img src="http://x/y"> url(http://x) "quoted"'
    d = doc()
    if field == "seller":
        d[field] = {"name": evil, "gstin": evil, "address": [evil], "state": evil}
    elif field == "buyer":
        d[field] = {"name": evil, "address": [evil], "state": evil}
    elif field == "lines":
        d[field] = [{**d["lines"][0], "description": evil, "hsn": evil, "uqc": evil}]
    elif field == "charges":
        d[field] = [{"label": evil, "amount": evil}]
    else:
        d[field] = evil
    html = template.render_html(d)
    assert "<img" not in html and "&lt;img" in html


@pytest.mark.parametrize(
    "bad",
    [
        {"template": "other"},
        {"v": 2},
        {"number": 5},
        {"totals": None},
        {"lines": "x"},
        {"lines": [{}] * 201},
        {"lines": [{**doc()["lines"][0], "quantity": 2}]},  # a number, not text
        {"number": "x" * 501},
    ],
)
def test_a_malformed_input_is_refused(bad):
    with pytest.raises(ValueError):
        template.render_html(doc(**bad))


def test_ship_to_sits_under_bill_to_in_the_right_column():  # #444
    html = document_template.render_html(doc(ship_to={"name": "Ghosh Godown", "address": ["3 Godown Road", "Siliguri 734001"],
                                                      "state": "West Bengal (19)"}))
    start = html.index('<table class="parties">')
    parties = html[start:html.index("</table>", start)]
    cells = parties.split("<td>")[1:]
    assert len(cells) == 2 and "Seller" in cells[0] and "Ship to" not in cells[0]
    right = cells[1]
    assert right.index("Bill to") < right.index("Ship to") < right.index("<b>Ghosh Godown</b>") < right.index("3 Godown Road")
    assert "State: West Bengal (19)" in right and html.count("Ship to") == 1
    assert "Ship to" not in document_template.render_html(doc())  # none when the goods go to the buyer


def full_doc(**over):
    """An intra-state invoice with MRP, a percent discount and the HSN summary the builder writes (#450)."""
    line = {"no": "1", "description": "Face cream 50 g", "hsn": "33049910", "quantity": "12", "uqc": "NOS",
            "mrp": "413.00", "unit_price": "350.00", "gross": "4200.00", "discount": "2100.00",
            "discount_percent": "50", "taxable": "2100.00",
            "taxes": [{"component": "CGST", "rate": "9", "amount": "189.00"},
                      {"component": "SGST", "rate": "9", "amount": "189.00"}], "total": "2478.00"}
    return doc(**{
        "seller": {"name": "Test Traders LLP", "gstin": "19AAPFU0939F1ZS", "pan": "AAPFU0939F", "address": ["1 Test Road"],
                   "state": "West Bengal (19)"},
        "buyer": {"name": "Walk-in", "gstin": None, "address": ["Kolkata"], "state": "West Bengal (19)"},
        "place_of_supply": "West Bengal (19)", "copy_label": "Original for Recipient", "lines": [line],
        "hsn_summary": [{"hsn": "33049910", "rate": "18", "taxable": "2100.00",
                         "taxes": [{"component": "CGST", "amount": "189.00"}, {"component": "SGST", "amount": "189.00"}]}],
        "totals": {"taxable": "2100.00", "taxes": [{"component": "CGST", "amount": "189.00"},
                                                  {"component": "SGST", "amount": "189.00"}],
                   "round_off": None, "total": "2478.00", "in_words": "Rupees Two Thousand Four Hundred Seventy-eight Only"},
        **over,
    })  # fmt: skip


def test_the_line_columns_follow_the_council_order_and_say_which_side_of_gst_they_are_on():  # #450
    html = document_template.render_html(full_doc())
    head = html[html.index("<thead>"):html.index("</thead>")]
    order = ["#", "Description", "HSN", "Qty", "MRP", "incl. GST", "Rate", "excl. GST", "Value", "Rate × Qty",
             "Discount", "Taxable value", "Tax", "Total"]
    at = [head.index(f">{h}<") if h in ("#", "Tax", "Total") else head.index(h) for h in order]
    assert at == sorted(at)
    row = html[html.index("<tbody>"):html.index("</tbody>")]
    for text in ("12 NOS", "413.00", "350.00", "4200.00", "50% / 2100.00", "2100.00", "CGST 9%: 189.00",
                 "SGST 9%: 189.00", "2478.00"):
        assert text in row
    assert row.index("413.00") < row.index("350.00") < row.index("4200.00") < row.index("50% / 2100.00")


def test_an_old_document_without_mrp_prints_a_dash_and_an_amount_discount_prints_the_amount():  # #450
    line = {**full_doc()["lines"][0], "mrp": None, "discount_percent": None, "discount": "75.00"}
    row = document_template.render_html(full_doc(lines=[line]))
    row = row[row.index("<tbody>"):row.index("</tbody>")]
    assert '<td class="n mrp">–</td>' in row and ">75.00<" in row and "%" not in row.replace("9%", "")


def test_igst_prints_one_tax_row_and_the_summary_has_an_igst_column():  # #450
    html = document_template.render_html(doc(hsn_summary=[
        {"hsn": "340111", "rate": "18", "taxable": "113.75", "taxes": [{"component": "IGST", "amount": "20.48"}]}]))
    assert "IGST 18%: 20.48" in html and "CGST" not in html and "SGST" not in html
    summary = html[html.index('<table class="hsn">'):]
    summary = summary[:summary.index("</table>")]
    assert "Tax summary by HSN" in summary and ">IGST<" in summary and ">18%<" in summary and ">20.48<" in summary


def test_the_page_carries_the_copy_label_pan_watermark_payable_signatory_and_page_numbers():  # #450
    html = document_template.render_html(full_doc())
    assert html.count("Original for Recipient") == 1  # the top right; the footer repeats it by string-set (#454)
    assert "string-set: copylabel content()" in html and "content: string(copylabel)" in html
    assert 'counter(page) " of " counter(pages)' in html
    assert '<div class="wm">PRACTICE</div>' in html
    assert "PAN: AAPFU0939F" in html and "GSTIN: Unregistered" in html
    assert "Amount payable ₹ 2478.00" in html
    assert html.index("Amount payable") < html.index("Amount in words") < html.index("Authorised Signatory")
    assert "For Test Traders LLP" in html
    assert "page-break-inside: avoid" in html and "table-header-group" in html


@pytest.mark.parametrize("field", ["mrp", "discount_percent", "pan", "hsn_summary"])
def test_the_new_fields_are_escaped_too(field):  # #450
    evil = '<img src="http://x/y">'
    d = full_doc()
    if field in ("mrp", "discount_percent"):
        d["lines"] = [{**d["lines"][0], field: evil}]
    elif field == "pan":
        d["seller"] = {**d["seller"], "pan": evil}
    elif field == "hsn_summary":
        d["hsn_summary"] = [{"hsn": evil, "rate": evil, "taxable": evil, "taxes": [{"component": evil, "amount": evil}]}]
    html = template.render_html(d)
    assert "<img" not in html and "&lt;img" in html


def test_a_200_line_invoice_renders():  # #450: headings repeat by CSS, totals kept together at the end
    lines = [{**full_doc()["lines"][0], "no": str(i)} for i in range(1, 201)]
    html = document_template.render_html(full_doc(lines=lines))
    assert html.count("<tr><td class=\"n\">") >= 200 and html.count("<thead>") == 1


@pytest.mark.parametrize("label", ['<img src="http://x/y">', "Copy for Bank", "original for recipient"])
def test_a_copy_label_is_one_of_the_rule_48_labels(label):  # #454: it is also the page footer
    with pytest.raises(ValueError):
        template.render_html(full_doc(copy_label=label))


def test_copies_make_one_page_set_per_rule_48_label():  # #454, Rule 48(1)
    labels = list(document_template.COPY_LABELS)
    htmls = template.render_htmls(full_doc(copies=labels))
    assert len(htmls) == 3
    for html, label in zip(htmls, labels, strict=True):
        assert f'<td class="copy">{label}</td>' in html
    assert template.render_htmls(full_doc()) == [template.render_html(full_doc())]


@pytest.mark.parametrize("copies", [["Original for Recipient", "Original for Recipient"], ["Copy for Bank"], ["x"] * 4])
def test_copies_must_be_distinct_rule_48_labels(copies):
    with pytest.raises(ValueError):
        template.render_htmls(full_doc(copies=copies))


NOTE = {"kind": "credit_note", "original_number": "PR-0042", "original_date": "2026-11-18", "reason": "Goods returned"}


def test_a_credit_note_names_its_invoice_and_reason_and_says_credit_amount():  # #456, Rule 53(1A)
    html = template.render_html(full_doc(note=NOTE, number="PR-CN-0001", due_date="2026-12-18"))
    assert document_template.PRACTICE_NOTE_TITLE in html and document_template.PRACTICE_TITLE not in html
    assert "Against invoice: PR-0042 dated 2026-11-18" in html
    assert "Reason: Goods returned" in html
    assert "Credit amount ₹" in html and "Amount payable" not in html
    assert "Due date" not in html


def test_a_credit_note_has_an_original_and_a_duplicate_only():  # #456: the triplicate is an invoice rule
    htmls = template.render_htmls(full_doc(note=NOTE, copies=list(document_template.NOTE_COPY_LABELS)))
    assert len(htmls) == 2
    assert '<td class="copy">Duplicate for Supplier</td>' in htmls[1]
    with pytest.raises(ValueError):
        template.render_htmls(full_doc(note=NOTE, copies=list(document_template.COPY_LABELS)))
    with pytest.raises(ValueError):
        template.render_htmls(full_doc(copies=["Original for Recipient", "Duplicate for Supplier"]))


def test_a_debit_note_says_debit_note_and_amount_payable():  # #456 part 3
    html = template.render_html(full_doc(note={**NOTE, "kind": "debit_note", "reason": "Taxable value charged too low"},
                                         number="PR-DN-0001"))
    assert document_template.PRACTICE_DEBIT_TITLE in html and document_template.PRACTICE_NOTE_TITLE not in html
    assert "Against invoice: PR-0042 dated 2026-11-18" in html and "Reason: Taxable value charged too low" in html
    assert "Amount payable ₹" in html and "Credit amount" not in html


@pytest.mark.parametrize("note", [{"kind": "invoice"}, "credit_note", {"kind": "<b>"}])
def test_an_unknown_note_kind_is_refused(note):
    with pytest.raises(ValueError):
        template.render_html(full_doc(note=note))


@pytest.mark.parametrize("field", ["original_number", "original_date", "reason"])
def test_the_note_fields_are_escaped(field):
    html = template.render_html(full_doc(note={**NOTE, field: "<script>x</script>"}))
    assert "<script>x</script>" not in html and "&lt;script&gt;" in html


CANCELLED = {"date": "2026-11-26", "reason": "Raised by mistake"}


def test_a_cancelled_invoice_says_cancelled_on_every_copy():  # #468, #456 part 2
    htmls = template.render_htmls(full_doc(cancelled=CANCELLED, copies=list(document_template.COPY_LABELS)))
    assert len(htmls) == 3
    for html in htmls:
        assert '<div class="cancelled">CANCELLED on 2026-11-26: Raised by mistake</div>' in html
        assert '<div class="wm2">CANCELLED</div>' in html
    assert "CANCELLED" not in template.render_html(full_doc())


@pytest.mark.parametrize("bad", [{"date": "2026-11-26"}, {"reason": "x"}, "yes", True])
def test_a_malformed_cancel_mark_is_refused(bad):
    with pytest.raises(ValueError):
        template.render_html(full_doc(cancelled=bad))


def test_only_an_invoice_can_be_marked_cancelled():
    with pytest.raises(ValueError):
        template.render_html(full_doc(note=NOTE, cancelled=CANCELLED))


@pytest.mark.parametrize("field", ["date", "reason"])
def test_the_cancel_fields_are_escaped(field):
    html = template.render_html(full_doc(cancelled={**CANCELLED, field: "<script>x</script>"}))
    assert "<script>x</script>" not in html and "&lt;script&gt;" in html

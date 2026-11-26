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
    html = document_template.render_html(doc(ship_to={"address": ["3 Godown Road", "Siliguri 734001"], "state": "West Bengal (19)"}))
    parties = html[html.index('<table class="parties">'):html.index("</table>")]
    cells = parties.split("<td>")[1:]
    assert len(cells) == 2 and "Seller" in cells[0] and "Ship to" not in cells[0]
    right = cells[1]
    assert right.index("Bill to") < right.index("Ship to") < right.index("3 Godown Road")
    assert "State: West Bengal (19)" in right and html.count("Ship to") == 1
    assert "Ship to" not in document_template.render_html(doc())  # none when the goods go to the buyer

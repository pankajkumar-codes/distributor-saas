"""#470: a name as long as the app allows (200 characters) prints in full and wraps inside the page. The CGST Rules
ask for the buyer's name and address (Rule 46(d), 53(1A)) and set no length, so a name is never cut short and
never runs off the page, even one long word with no spaces."""

import weasyprint

from renderer import template
from test_document_template import full_doc
from test_render import _doc

LONG_NAME = "Shree" + "Ganesh" * 32 + "Traders"  # 202 letters, no spaces: the hardest case to wrap
assert len(LONG_NAME) >= 200


def _boxes(box):
    """Every piece of laid-out text under `box`, in reading order."""
    if getattr(box, "text", None):
        yield box
    for child in getattr(box, "children", None) or []:
        yield from _boxes(child)


def _check(html):
    document = weasyprint.HTML(string=html).render()
    for page in document.pages:
        assert max(b.position_x + b.width for b in _boxes(page._page_box)) <= page.width, "text runs off the page"
    return "".join(b.text for p in document.pages for b in _boxes(p._page_box))


def test_a_200_character_buyer_and_product_name_wrap_on_the_invoice():
    d = full_doc()
    d["buyer"] = {**d["buyer"], "name": LONG_NAME}
    d["lines"] = [{**d["lines"][0], "description": LONG_NAME}]
    text = _check(template.render_html(d))
    assert text.count(LONG_NAME) >= 2  # printed in full, never cut short


def test_a_200_character_seller_and_ship_to_name_wrap_on_the_invoice():
    d = full_doc()
    d["seller"] = {**d["seller"], "name": LONG_NAME}
    d["ship_to"] = {"name": LONG_NAME, "address": ["1 Dock Road"], "state": "West Bengal (19)"}
    text = _check(template.render_html(d))
    assert text.count(LONG_NAME) >= 2


def test_a_200_character_name_wraps_on_the_draft_preview():
    text = _check(template.render_html(_doc(
        buyer={"name": LONG_NAME, "gstin": None, "address": ["2 Other Road"], "state": "West Bengal (19)"},
        lines=[{"no": "1", "description": LONG_NAME, "hsn": "4820", "quantity": "2", "uqc": "NOS",
                "unit_price": "100.00", "discount": None}],
    )))
    assert text.count(LONG_NAME) >= 2

"""The gstr3b-worksheet template: text tables printed as given, every value escaped, bounded input. Pure HTML; the PDF itself is
WeasyPrint's job (tests in test_render.py)."""

import pytest

from renderer import template, worksheet_template


def doc(**over):
    base = {
        "v": 1, "template": "gstr3b-worksheet", "label": "Worksheet, not a filing", "subtitle": ["Numbers to check"],
        "banner": None,
        "sections": [{"title": "3.1", "columns": ["Total Taxable Value", "Integrated Tax"],
                      "rows": [{"label": "(a) Outward", "cells": ["1100.00", "10.00"]}, {"label": "(b) Zero", "cells": ["0.00", None]}]}],
        "notes": ["Offset and payment are done on the GST portal."],
    }  # fmt: skip
    return {**base, **over}


def test_the_page_prints_the_label_the_tables_and_the_notes():
    html = template.render_html(doc())  # dispatched by the template name
    assert html == worksheet_template.render_html(doc())
    for text in ("Worksheet, not a filing", "Numbers to check", "Total Taxable Value", "(a) Outward", "1100.00", "10.00",
                 "Offset and payment are done on the GST portal."):  # fmt: skip
        assert text in html
    assert "class=\"banner\"" not in html


def test_a_banner_prints_when_given():
    assert "Out of date" in template.render_html(doc(banner="Out of date: build again"))


@pytest.mark.parametrize("field", ["label", "subtitle", "banner", "notes", "sections"])
def test_every_value_is_escaped_and_nothing_becomes_markup(field):
    evil = '<img src="http://x/y"> url(http://x) "quoted"'
    d = doc()
    d[field] = [evil] if field in ("subtitle", "notes") else (evil if field != "sections" else
        [{"title": evil, "columns": [evil], "rows": [{"label": evil, "cells": [evil]}]}])  # fmt: skip
    html = template.render_html(d)
    assert "<img" not in html and "&lt;img" in html


@pytest.mark.parametrize(
    "bad",
    [
        {"template": "other"},
        {"v": 2},
        {"label": 5},
        {"sections": "x"},
        {"sections": [{"title": "t", "columns": ["a"] * 7, "rows": []}]},  # too many columns
        {"sections": [{"title": "t", "columns": [], "rows": [{"label": "l", "cells": [5]}]}]},  # a number, not text
        {"sections": [{"title": "t", "columns": [], "rows": [{"label": "l", "cells": []}] * 61}]},  # too many rows
        {"sections": [{"title": "t", "columns": [], "rows": []}] * 13},  # too many sections
        {"notes": ["n"] * 51},
        {"notes": [3]},
    ],
)
def test_a_malformed_input_is_refused(bad):
    with pytest.raises(ValueError):
        template.render_html(doc(**bad))

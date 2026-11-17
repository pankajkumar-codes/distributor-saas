"""Comparing two sets of output rows by document number (R1-M8 S5). Pure."""

from decimal import Decimal

from app.modules.filing import lock

D = Decimal


def row(section, number, taxable="100.00", **kw):
    return {"section": section, "doc_number": number, "taxable_value": D(taxable), "igst": D("0"), "cgst": D("9"),
            "sgst": D("9"), "cess": D("0"), **kw}  # fmt: skip


def summary(section, taxable="100.00", **kw):
    return {"section": section, "doc_number": None, "taxable_value": D(taxable), **kw}


def test_the_same_rows_give_no_difference_whatever_their_order_or_decimal_places():
    a = [row("b2b", "INV-1"), row("b2b", "INV-2", "50.00"), summary("b2cs")]
    b = [summary("b2cs", "100.0"), row("b2b", "INV-2", "50"), row("b2b", "INV-1", "100.000")]
    assert lock.is_same(lock.diff_rows(a, b))


def test_documents_added_removed_and_changed_are_listed_by_section_and_number():
    old = [row("b2b", "INV-1"), row("b2b", "INV-2"), row("cdnr", "CN-1")]
    new = [row("b2b", "INV-1"), row("b2b", "INV-2", "999.00"), row("b2b", "INV-3"), row("b2cl", "INV-9")]
    d = lock.diff_rows(old, new)
    assert d["added"] == [{"section": "b2b", "number": "INV-3"}, {"section": "b2cl", "number": "INV-9"}]
    assert d["removed"] == [{"section": "cdnr", "number": "CN-1"}]
    assert d["changed"] == [{"section": "b2b", "number": "INV-2"}]
    assert d["summaries"] == [] and not lock.is_same(d)


def test_a_changed_summary_table_is_named_without_a_document_number():
    d = lock.diff_rows([summary("b2cs", "100.00")], [summary("b2cs", "120.00"), summary("hsn_b2b", "5.00")])
    assert d["summaries"] == ["b2cs", "hsn_b2b"] and d["added"] == d["removed"] == d["changed"] == []


def test_a_document_on_two_rates_is_one_document_and_a_changed_rate_split_is_a_change():
    two = [row("b2b", "INV-1", rate=D("5")), row("b2b", "INV-1", rate=D("12"))]
    one = [row("b2b", "INV-1", rate=D("5"))]
    d = lock.diff_rows(two, one)
    assert d["changed"] == [{"section": "b2b", "number": "INV-1"}] and d["added"] == [] and d["removed"] == []


def test_nothing_exported_means_every_document_is_added():
    d = lock.diff_rows([], [row("b2b", "INV-1"), summary("b2cs")])
    assert d["added"] == [{"section": "b2b", "number": "INV-1"}] and d["summaries"] == ["b2cs"]

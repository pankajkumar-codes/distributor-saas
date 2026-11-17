"""The confirm check's pure parts (R1-M7 slice 1): which rows are included, when two cells agree, and which
documents disagree. No database."""

import uuid

from app.modules.imports.confirm import _Row, _included, _same, disagreeing_rows

KEY = ("seller_gstin", "doc_type", "doc_number")
AGREE = ("doc_date", "original_number", "original_date", "buyer_gstin", "invoice_total")
PERIOD = ("doc_date",)


def row(n, *, status="new", resolution=None, **values):
    base = {"seller_gstin": "G", "doc_type": "Invoice", "doc_number": "INV-1", "doc_date": "2026-07-03",
            "invoice_total": "236.00", **values}
    return _Row(uuid.uuid4(), n, status, None, base, "h", resolution, None, None)


def test_included_rows_are_new_changed_and_held_rows_the_user_accepted_or_fixed_never_set_aside():
    assert _included(row(1)) and _included(row(1, status="changed"))
    assert not any(_included(row(1, status=s)) for s in ("already_imported", "duplicate", "skipped_zero", "invalid", "conflict"))
    assert not _included(row(1, status="held")) and not _included(row(1, status="held", resolution="set_aside"))
    assert _included(row(1, status="held", resolution="accepted")) and _included(row(1, status="held", resolution="fixed"))
    assert not _included(row(1, resolution="set_aside"))


def test_cells_agree_as_numbers_or_as_trimmed_case_folded_text_and_blank_equals_missing():
    assert _same("236", "236.00") and _same(" abc ", "ABC") and _same(None, "") and not _same("236", "237")
    assert not _same("", "0")


def test_lines_of_one_document_must_agree_on_each_checked_field():
    for field, other in (("doc_date", "2026-07-04"), ("original_number", "X"), ("buyer_gstin", "B"), ("invoice_total", "1")):
        rows = [row(1), row(2, **{field: other})]
        assert disagreeing_rows(rows, KEY, AGREE, PERIOD) == ([1, 2] if field != "doc_date" else [1, 2]), field
    assert disagreeing_rows([row(1), row(2, invoice_total="236")], KEY, AGREE, PERIOD) == []


def test_a_number_reused_in_another_financial_year_is_another_document():
    rows = [row(1), row(2, doc_date="2027-04-02", invoice_total="999")]
    assert disagreeing_rows(rows, KEY, AGREE, PERIOD) == []
    assert disagreeing_rows([row(1), row(2, doc_date="2027-03-30")], KEY, AGREE, PERIOD) == [1, 2]  # same year 2026-27


def test_rows_left_out_do_not_count_toward_agreement_and_the_number_is_folded():
    rows = [row(1), row(2, resolution="set_aside", invoice_total="1"), row(3, doc_number=" inv-1 ")]
    assert disagreeing_rows(rows, KEY, AGREE, PERIOD) == []

"""Checks that need no database: they read only the build's lines. The rest are tested through confirm on PostgreSQL
(imports/tests/test_checks_postgres.py)."""

import uuid
from dataclasses import replace
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.modules.filing import checks
from app.modules.filing.gstr1 import Amounts, B2BRow, B2CLRow, B2CSRow, CDNRRow, Gstr1Sections, SupplyLine

GSTIN = "19AAPFU0939F1ZS"


def ln(n=1, *, number=None, d=date(2026, 10, 5), **kw):
    base = SupplyLine("own_invoice", uuid.UUID(int=n), f"f.xlsx row {n}", GSTIN, d, number or f"INV-{n}", "invoice",
                      "B2CS", "19", Decimal("18"), "6109", "PCS", Decimal("1"), Decimal("100"), Decimal(),
                      Decimal("9"), Decimal("9"), Decimal(), Decimal("118"))
    return replace(base, **kw)


def build(*lines):
    return SimpleNamespace(lines=lines)


def test_unequal_cgst_and_sgst_are_reported_with_both_figures():
    (f,) = checks.a3_cgst_sgst_differ(None, build(ln(cgst=Decimal("10"), sgst=Decimal("8"))))
    assert f.code == "A-03" and "CGST is 10" in f.message and "SGST is 8" in f.message and f.needs_ca_check
    assert checks.a3_cgst_sgst_differ(None, build(ln())) == []


def test_the_same_number_twice_in_one_year_is_a_block_and_a_note_when_the_years_differ():
    same_fy = build(ln(1, number="inv-9"), ln(2, number="INV-9"))
    (f,) = checks.c04_duplicate_number(None, same_fy)
    assert f.code == "C-04" and f.level == "block" and f.source_refs == ("f.xlsx row 1", "f.xlsx row 2")
    two_fy = build(ln(1, number="INV-9"), ln(2, number="INV-9", d=date(2027, 4, 2)))
    assert checks.c04_duplicate_number(None, two_fy) == []
    (note,) = checks.a4_number_in_two_years(None, two_fy)
    assert note.code == "A-04" and note.level == "info" and "2026-27" in note.message and "2027-28" in note.message


def test_a_credit_note_and_an_invoice_may_share_a_number():
    b = build(ln(1, number="9"), ln(2, number="9", doc_kind="credit_note", source_kind="own_credit_note"))
    assert checks.c04_duplicate_number(None, b) == []


def test_two_lines_of_one_document_are_not_a_duplicate():
    one_doc = build(ln(1), replace(ln(1), source_ref="f.xlsx row 2"))
    assert checks.c04_duplicate_number(None, one_doc) == []


def test_a_missing_hsn_is_a_block():
    (f,) = checks.c01_missing_hsn(None, build(ln(hsn=""), ln(2)))
    assert f.code == "C-01" and f.level == "block"


def test_the_finding_fingerprint_moves_with_the_row():
    a = checks.a3_cgst_sgst_differ(None, build(ln(1, cgst=Decimal("1"))))[0]
    b = checks.a3_cgst_sgst_differ(None, build(ln(2, cgst=Decimal("1"))))[0]
    assert a.subject_fp != b.subject_fp


def test_every_value_a_build_relies_on_has_plain_words():
    assert set(checks.RELIED_ON) <= set(checks._RELIED_ON_PLAIN)


def test_a_corrected_line_under_the_same_file_and_row_is_a_new_subject():
    old = ln(1, cgst=Decimal("1"))
    new = replace(old, sgst=Decimal("5"))  # same document id and source_ref, different figures
    assert old.source_id == new.source_id and old.source_ref == new.source_ref
    a = checks.a3_cgst_sgst_differ(None, build(old))[0]
    b = checks.a3_cgst_sgst_differ(None, build(new))[0]
    assert a.subject_fp != b.subject_fp
    for field, value in (("taxable_value", Decimal("101")), ("igst", Decimal("1")), ("cess", Decimal("1")),
                         ("hsn", "6110"), ("uqc", "KGS"), ("rate", Decimal("12"))):  # fmt: skip
        assert checks.a3_cgst_sgst_differ(None, build(replace(old, **{field: value})))[0].subject_fp != a.subject_fp


# -- C-17: the offline tool works tax out again for each row ---------------------------------------------------


def sections(**kw):
    return SimpleNamespace(sections=Gstr1Sections(kind="GSTR1", **kw))


def b2b(taxable, cgst, sgst, igst="0", rate="18", ref="f.xlsx row 1"):
    return B2BRow("29AAAAA0000A1Z5", None, "INV-1", date(2026, 10, 5), Decimal("0"), "29", Decimal(rate),
                  Amounts(Decimal(taxable), Decimal(igst), Decimal(cgst), Decimal(sgst), Decimal()), (ref,))  # fmt: skip


def test_three_lines_at_one_rate_that_round_apart_are_shown_with_both_figures():
    """Golden AC5-32: lines of 1,339.39 at 18% are 120.55 per head in the tool; our sum of line-rounded tax is 120.54."""
    (f,) = checks.c17_tool_recompute(None, sections(b2b=(b2b("1339.39", "120.54", "120.54"),)))
    assert f.code == "C-17" and f.level == "warn" and f.needs_ca_check and f.source_refs == ("f.xlsx row 1",)
    assert "CGST: your invoice has 120.54, the tool will work out 120.55" in f.message
    assert "SGST: your invoice has 120.54, the tool will work out 120.55" in f.message
    assert "GSTIN" not in f.message and "29AAAAA" not in f.message


def test_a_row_the_tool_agrees_with_is_not_reported_and_the_half_paisa_rounds_up():
    assert checks.c17_tool_recompute(None, sections(b2b=(b2b("1339.39", "120.55", "120.55"),))) == []
    assert checks.c17_tool_recompute(None, sections(b2b=(b2b("100.00", "9.00", "9.00"),))) == []
    # 0.50 x 9% = 0.045 which is half a paisa: the tool's figure is 0.05, not 0.04
    (f,) = checks.c17_tool_recompute(None, sections(b2b=(b2b("0.50", "0.04", "0.04", rate="18"),)))
    assert "the tool will work out 0.05" in f.message


def test_an_interstate_row_is_compared_on_igst_alone():
    assert checks.c17_tool_recompute(None, sections(b2b=(b2b("100.00", "0", "0", igst="18.00"),))) == []
    (f,) = checks.c17_tool_recompute(None, sections(b2b=(b2b("1339.39", "0", "0", igst="241.08"),)))
    assert "IGST: your invoice has 241.08, the tool will work out 241.09" in f.message and "CGST" not in f.message


def test_every_invoice_and_note_table_is_covered_and_cess_is_not_compared():
    amounts = Amounts(Decimal("1339.39"), Decimal(), Decimal("120.54"), Decimal("120.54"), Decimal("99"))
    d = date(2026, 10, 5)
    rows = dict(
        b2b=(b2b("1339.39", "120.54", "120.54"),),
        b2cl=(B2CLRow("N", d, Decimal(), "29", Decimal("18"), amounts, ("r2",)),),
        b2cs=(B2CSRow("19", Decimal("18"), amounts, ("r3",)),),
        cdnr=(CDNRRow("29AAAAA0000A1Z5", None, "CN", d, Decimal(), "29", Decimal("18"), amounts, None, None, ("r4",)),),
    )
    found = checks.c17_tool_recompute(None, sections(**rows))
    assert [f.source_refs for f in found] == [("f.xlsx row 1",), ("r2",), ("r3",), ("r4",)]
    assert [f.message.split(",")[0] for f in found][1:3] == ["Table 5 (B2CL)", "Table 7 (B2CS)"]
    cess_only = Amounts(Decimal("100"), Decimal(), Decimal("9"), Decimal("9"), Decimal("5"))
    assert checks.c17_tool_recompute(None, sections(b2cs=(B2CSRow("19", Decimal("18"), cess_only, ("r",)),))) == []


def test_the_c17_acceptance_fingerprint_moves_with_the_row_figures():
    a = checks.c17_tool_recompute(None, sections(b2b=(b2b("1339.39", "120.54", "120.54"),)))[0]
    b = checks.c17_tool_recompute(None, sections(b2b=(b2b("1339.39", "120.53", "120.53"),)))[0]
    assert a.subject_fp != b.subject_fp

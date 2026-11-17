"""Checks that need no database: they read only the build's lines. The rest are tested through confirm on PostgreSQL
(imports/tests/test_checks_postgres.py)."""

import uuid
from dataclasses import replace
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.modules.filing import checks
from app.modules.filing.gstr1 import SupplyLine

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

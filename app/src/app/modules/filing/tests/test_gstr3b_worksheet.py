"""GSTR-3B worksheet outward supplies (plan R1-M8b, W1): built from the same section rows as the GSTR-1.

Uses the gstr1-examples Part A supply lines, so the golden figures are the GSTR-1 ones, to the paisa.
"""

from decimal import Decimal

from app.modules.filing.gstr1 import build_sections, liability
from app.modules.filing.gstr3b import FLAG_TEXT, build_outward
from app.modules.filing.gstr3b.labels import OFFSET_NOTE, WORKSHEET_LABEL
from app.modules.filing.tests.test_gstr1_sections import CN, GJ, INV, KA, PART_A, SOAP, TEA, WB, A, D, line

SECTIONS = build_sections(PART_A)


def test_taxable_equals_gstr1_liability_to_the_paisa():
    out = build_outward([SECTIONS], WB)
    assert out.taxable == liability(SECTIONS)
    # 23,000 b2b + 100,000 b2cl + 289,945.76 b2cs - 500 cdnr - 10,000 cdnur
    assert out.taxable.taxable_value == D("402445.76")
    assert out.taxable.igst == D("1800.00") + D("18000.00") + D("15254.24") + D("100.00") - D("1800.00")
    assert out.taxable.cgst == out.taxable.sgst


def test_all_figures_are_decimal():
    out = build_outward([SECTIONS], WB)
    for v in (out.taxable.taxable_value, out.taxable.igst, out.taxable.cgst, out.taxable.sgst, out.taxable.cess, out.inter_state_taxable, out.inter_state_igst):
        assert isinstance(v, Decimal)
    for r in out.inter_state:
        assert isinstance(r.unregistered_taxable, Decimal) and isinstance(r.unregistered_igst, Decimal)


def test_inter_state_by_state_for_unregistered_buyers():
    out = build_outward([SECTIONS], WB)
    by = {r.pos_state_code: r for r in out.inter_state}
    assert sorted(by) == [GJ, KA]  # the supplier's own state and registered buyers are not in 3.2
    # GJ: b2cl 100,000 + b2cs 84,745.76 - cdnur note 10,000 at its place of supply
    assert by[GJ].unregistered_taxable == D("174745.76")
    assert by[GJ].unregistered_igst == D("18000.00") + D("15254.24") - D("1800.00")
    assert by[KA].unregistered_taxable == D("2000.00")
    assert by[KA].unregistered_igst == D("100.00")
    assert out.inter_state_taxable == D("176745.76")
    assert "INV/26-27/0003" in by[GJ].source_refs and "CN/26-27/0002" in by[GJ].source_refs


def test_credit_notes_netted_and_flagged():
    out = build_outward([SECTIONS], WB)
    assert "note_netting" in out.flags
    without_notes = build_sections([ln for ln in PART_A if ln.doc_kind == INV])
    out2 = build_outward([without_notes], WB)
    assert "note_netting" not in out2.flags
    assert out2.taxable.taxable_value == D("413745.76")


def test_always_flags_what_is_not_built():
    out = build_outward([SECTIONS], WB)
    assert {"nil_exempt_non_gst_not_built", "buyer_types_unknown"} <= set(out.flags)
    assert set(out.flags) <= set(FLAG_TEXT)


def test_zero_rate_rows_stay_in_3_1_a_with_a_flag():
    zero = ("0713", "KGS", D("0"))
    lines = [line("INV/26-27/0101", 2, INV, "B2CS", WB, zero, "10", "1000.00", value="1000.00")]
    out = build_outward([build_sections(lines)], WB)
    assert out.taxable.taxable_value == D("1000.00")
    assert out.zero_rate_rows == 1 and "zero_rate_rows" in out.flags


def test_inter_state_exceeding_taxable_is_a_warning_flag():
    # A credit note larger than the sales leaves a negative 3.1(a) while 3.2 stays positive.
    lines = [
        line("INV/26-27/0201", 2, INV, "B2CS", KA, TEA, "1", "100.00", igst="5.00", value="105.00"),
        line("CN/26-27/0201", 3, CN, "CDNR", WB, SOAP, "1", "500.00", cgst="45.00", sgst="45.00", value="590.00", buyer=A,
             original=("INV/26-27/0001", PART_A[0].doc_date)),
    ]  # fmt: skip
    out = build_outward([build_sections(lines)], WB)
    assert out.taxable.taxable_value == D("-400.00")
    assert "inter_state_exceeds_taxable" in out.flags


def test_quarter_counts_each_build_once_and_adds_iff_months():
    # A quarter is the quarter's own build plus every IFF month's; the caller passes each set once.
    m1 = build_sections([PART_A[0]])
    m2 = build_sections([PART_A[3]])
    both = build_outward([m1, m2], WB)
    assert both.taxable.taxable_value == D("5000.00") + D("100000.00")
    assert both.taxable == liability(m1, m2)


def test_empty_period_is_zero():
    out = build_outward([], WB)
    assert out.taxable.taxable_value == D("0") and out.inter_state == ()


def test_wording_never_says_filed():
    texts = [WORKSHEET_LABEL, OFFSET_NOTE, *FLAG_TEXT.values()]
    for t in texts:
        assert "filed" not in t.lower() and "ready to file" not in t.lower()

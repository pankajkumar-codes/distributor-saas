"""GSTR-1 sections from supply lines: gstr1-examples Part A (golden), Part B (IFF and
quarter), edge cases E3/E4, and the routing decision tables (LLD-5 §5).

Supply lines here are what sales.v_filing_lines would publish for the examples'
documents: amounts as stored at finalize. Test data only (synthetic GSTINs from the
examples' parties table). #7 is the examples' cancelled invoice: R1 has no
cancellation and a cancelled document has no supply lines, so it is not an input.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.modules.filing.gstr1 import (
    HSN_TAB,
    PENDING,
    QUARTER_PENDING,
    ROUTE,
    Amounts,
    BadSupplyLine,
    SupplyLine,
    build_sections,
    hsn_total,
    liability,
    reconciliation_gap,
)

D = Decimal
T = "19AAACX1111A1Z2"
A = "19AAACX2222B1ZU"
B = "29AAACX3333C1ZL"
SOAP = ("3401", "NOS", D("18"))
TEA = ("0902", "KGS", D("5"))
WB, KA, GJ = "19", "29", "24"


def line(number, day, kind, cls, pos, product, qty, taxable, *, igst="0", cgst="0", sgst="0", value,
         buyer=None, original=None, month=10, year=2026, doc_id=None):  # fmt: skip
    hsn, uqc, rate = product
    return SupplyLine(
        source_kind="own_credit_note" if kind == "credit_note" else "own_invoice",
        source_id=doc_id or uuid.uuid5(uuid.NAMESPACE_URL, number),
        source_ref=number,
        gstin=T,
        doc_date=date(year, month, day),
        doc_number=number,
        doc_kind=kind,
        supply_class=cls,
        pos_state_code=pos,
        rate=rate,
        hsn=hsn,
        uqc=uqc,
        quantity=D(qty),
        taxable_value=D(taxable),
        igst=D(igst),
        cgst=D(cgst),
        sgst=D(sgst),
        cess=D("0.00"),
        doc_value=D(value),
        counterparty_gstin=buyer,
        original_doc_number=original[0] if original else None,
        original_doc_date=original[1] if original else None,
    )


INV, CN = "invoice", "credit_note"
I1 = date(2026, 10, 1)
I3 = date(2026, 10, 5)
I6 = date(2026, 10, 8)

# gstr1-examples A1 (#7 cancelled: no supply lines). #4's amounts are as stored; how its
# taxable value was derived is compute's concern (tax-inclusive is CA-5, not built).
PART_A = [
    line("INV/26-27/0001", 1, INV, "B2B", WB, SOAP, "100", "5000.00", cgst="450.00", sgst="450.00", value="14300.00", buyer=A),
    line("INV/26-27/0001", 1, INV, "B2B", WB, TEA, "20", "8000.00", cgst="200.00", sgst="200.00", value="14300.00", buyer=A),
    line("INV/26-27/0002", 3, INV, "B2B", KA, SOAP, "200", "10000.00", igst="1800.00", value="11800.00", buyer=B),
    line("INV/26-27/0003", 5, INV, "B2CL", GJ, SOAP, "2000", "100000.00", igst="18000.00", value="118000.00"),
    line("INV/26-27/0004", 6, INV, "B2CS", GJ, SOAP, "2000", "84745.76", igst="15254.24", value="100000.00"),
    line("INV/26-27/0005", 7, INV, "B2CS", WB, SOAP, "4000", "200000.00", cgst="18000.00", sgst="18000.00", value="236000.00"),
    line("INV/26-27/0006", 8, INV, "B2CS", WB, TEA, "10", "4000.00", cgst="100.00", sgst="100.00", value="4200.00"),
    line("INV/26-27/0008", 10, INV, "B2CS", KA, TEA, "5", "2000.00", igst="100.00", value="2100.00"),
    line("CN/26-27/0001", 15, CN, "CDNR", WB, SOAP, "10", "500.00", cgst="45.00", sgst="45.00", value="590.00", buyer=A, original=("INV/26-27/0001", I1)),
    line("CN/26-27/0002", 16, CN, "CDNUR", GJ, SOAP, "200", "10000.00", igst="1800.00", value="11800.00", original=("INV/26-27/0003", I3)),
    line("CN/26-27/0003", 17, CN, "B2CS", WB, TEA, "2", "800.00", cgst="20.00", sgst="20.00", value="840.00", original=("INV/26-27/0006", I6)),
]  # fmt: skip


def amt(taxable, igst="0", cgst="0", sgst="0"):
    return Amounts(D(taxable), D(igst), D(cgst), D(sgst), D("0"))


def test_part_a_b2b_one_row_per_invoice_and_rate():  # A2
    s = build_sections(PART_A)
    assert [(r.recipient_gstin, r.invoice_number, r.invoice_value, r.pos_state_code, r.rate, r.amounts) for r in s.b2b] == [
        (A, "INV/26-27/0001", D("14300.00"), WB, D("5"), amt("8000.00", cgst="200.00", sgst="200.00")),
        (A, "INV/26-27/0001", D("14300.00"), WB, D("18"), amt("5000.00", cgst="450.00", sgst="450.00")),
        (B, "INV/26-27/0002", D("11800.00"), KA, D("18"), amt("10000.00", igst="1800.00")),
    ]  # fmt: skip
    # Invoice value is per invoice, never summed per row (A2: 26,100.00, not 40,400.00).
    assert sum({r.invoice_number: r.invoice_value for r in s.b2b}.values()) == D("26100.00")


def test_part_a_b2cl_and_cdnur():  # A3, A5
    s = build_sections(PART_A)
    assert [(r.invoice_number, r.invoice_value, r.pos_state_code, r.rate, r.amounts) for r in s.b2cl] == [
        ("INV/26-27/0003", D("118000.00"), GJ, D("18"), amt("100000.00", igst="18000.00"))
    ]
    (cdnur,) = s.cdnur
    assert (cdnur.ur_type, cdnur.note_type, cdnur.note_number, cdnur.note_value, cdnur.pos_state_code) == (
        "B2CL", "C", "CN/26-27/0002", D("11800.00"), GJ,
    )  # fmt: skip
    assert cdnur.amounts == amt("10000.00", igst="1800.00")  # positive; the tool subtracts
    assert (cdnur.original_doc_number, cdnur.original_doc_date) == ("INV/26-27/0003", I3)


def test_part_a_b2cs_nets_b2cs_credit_notes():  # A4
    s = build_sections(PART_A)
    assert [(r.pos_state_code, r.rate, r.amounts) for r in s.b2cs] == [
        (WB, D("5"), amt("3200.00", cgst="80.00", sgst="80.00")),  # #6 4,000 − CN #11 800
        (WB, D("18"), amt("200000.00", cgst="18000.00", sgst="18000.00")),
        (GJ, D("18"), amt("84745.76", igst="15254.24")),
        (KA, D("5"), amt("2000.00", igst="100.00")),
    ]
    assert s.b2cs[0].source_refs == ("CN/26-27/0003", "INV/26-27/0006")


def test_part_a_cdnr():  # A5
    (r,) = build_sections(PART_A).cdnr
    assert (r.recipient_gstin, r.note_number, r.note_type, r.pos_state_code, r.note_value, r.rate, r.amounts) == (
        A, "CN/26-27/0001", "C", WB, D("590.00"), D("18"), amt("500.00", cgst="45.00", sgst="45.00"),
    )  # fmt: skip


def test_part_a_hsn_split_by_tab_with_notes_netted():  # A6
    s = build_sections(PART_A)
    assert [(r.hsn, r.uqc, r.rate, r.quantity, r.amounts) for r in s.hsn_b2b] == [
        ("0902", "KGS", D("5"), D("20"), amt("8000.00", cgst="200.00", sgst="200.00")),
        ("3401", "NOS", D("18"), D("290"), amt("14500.00", igst="1800.00", cgst="405.00", sgst="405.00")),
    ]
    assert [(r.hsn, r.uqc, r.rate, r.quantity, r.amounts) for r in s.hsn_b2c] == [
        ("0902", "KGS", D("5"), D("13"), amt("5200.00", igst="100.00", cgst="80.00", sgst="80.00")),
        ("3401", "NOS", D("18"), D("7800"), amt("374745.76", igst="31454.24", cgst="18000.00", sgst="18000.00")),
    ]


def test_part_a_reconciliation_golden_assertion():  # A8
    s = build_sections(PART_A)
    expected = amt("402445.76", igst="33354.24", cgst="18685.00", sgst="18685.00")
    assert liability(s) == expected
    assert hsn_total(s) == expected
    assert reconciliation_gap(s).is_zero()
    assert s.line_items == 3 + 1 + 4 + 1 + 1 + 2 + 2
    assert s.pending == PENDING


def test_a8_un_cancelling_7_adds_exactly_its_amounts():  # A8 "Test also"
    seven = line("INV/26-27/0007", 9, INV, "B2CS", WB, SOAP, "20", "1000.00", cgst="90.00", sgst="90.00", value="1180.00")  # fmt: skip
    before, after = build_sections(PART_A), build_sections([*PART_A, seven])
    row = {(r.pos_state_code, r.rate): r.amounts for r in after.b2cs}
    was = {(r.pos_state_code, r.rate): r.amounts for r in before.b2cs}
    assert row[(WB, D("18"))] - was[(WB, D("18"))] == amt("1000.00", cgst="90.00", sgst="90.00")
    assert hsn_total(after) - hsn_total(before) == amt("1000.00", cgst="90.00", sgst="90.00")
    assert reconciliation_gap(after).is_zero()


def test_line_order_does_not_change_the_build():
    assert build_sections(PART_A) == build_sections(reversed(PART_A))


# -- Part B: QRMP with IFF ---------------------------------------------------------------

Q = "19AAACX4444D1ZE"


def q(number, month, day, cls, product, qty, taxable, tax, value, buyer=A):
    return line(
        number, day, INV, cls, WB, product, qty, taxable, cgst=tax, sgst=tax, value=value, buyer=buyer, month=month
    )


Q1 = q("INV/Q/001", 10, 5, "B2B", SOAP, "1000", "50000.00", "4500.00", "59000.00")
Q2 = q("INV/Q/002", 10, 28, "B2B", SOAP, "200", "10000.00", "900.00", "11800.00")
Q3 = q("INV/Q/003", 11, 10, "B2B", SOAP, "400", "20000.00", "1800.00", "23600.00")
Q4 = q("INV/Q/004", 12, 5, "B2B", SOAP, "600", "30000.00", "2700.00", "35400.00")
Q5 = q("INV/Q/005", 11, 20, "B2CS", TEA, "10", "4000.00", "100.00", "4200.00", buyer=None)


def test_part_b_iffs_and_the_quarter():
    iff_oct = build_sections([Q1], kind="IFF")
    iff_nov = build_sections([Q3], kind="IFF")
    assert [r.invoice_number for r in iff_oct.b2b] == ["INV/Q/001"]
    assert (iff_oct.b2cs, iff_oct.hsn_b2b, iff_oct.hsn_b2c) == ((), (), ())  # IFFQ FAQ 10
    # Liability: Q2 and Q4 (locked IFF members excluded by assignment) and Q5; Table 12:
    # the whole quarter, IFF months included.
    quarter = build_sections([Q2, Q4, Q5], hsn_lines=[Q1, Q2, Q3, Q4, Q5])
    assert [r.invoice_number for r in quarter.b2b] == ["INV/Q/002", "INV/Q/004"]
    assert [(r.pos_state_code, r.rate, r.amounts) for r in quarter.b2cs] == [
        (WB, D("5"), amt("4000.00", cgst="100.00", sgst="100.00"))
    ]
    assert [(r.hsn, r.quantity, r.amounts) for r in quarter.hsn_b2b] == [
        ("3401", D("2200"), amt("110000.00", cgst="9900.00", sgst="9900.00"))
    ]
    assert [(r.hsn, r.quantity, r.amounts) for r in quarter.hsn_b2c] == [
        ("0902", D("10"), amt("4000.00", cgst="100.00", sgst="100.00"))
    ]
    assert liability(quarter, iff_oct, iff_nov) == amt("114000.00", cgst="10000.00", sgst="10000.00")
    assert QUARTER_PENDING in quarter.pending
    # The quarter's Table 12 covers its IFF months, so it reconciles only with them.
    assert not reconciliation_gap(quarter).is_zero()
    assert reconciliation_gap(quarter, iff_builds=[iff_oct, iff_nov]).is_zero()


def test_an_iff_refuses_b2c_lines():
    with pytest.raises(BadSupplyLine, match="IFF"):
        build_sections([Q1, Q5], kind="IFF")


# -- Edge cases (A9) ---------------------------------------------------------------------


def test_e3_a_b2cs_row_netting_negative_is_kept():
    note = line("CN/26-27/0010", 15, CN, "B2CS", WB, TEA, "2", "800.00", cgst="20.00", sgst="20.00", value="840.00",
                original=("INV/26-27/0006", I6), month=1, year=2027)  # fmt: skip
    s = build_sections([note])
    assert [(r.pos_state_code, r.rate, r.amounts) for r in s.b2cs] == [
        (WB, D("5"), amt("-800.00", cgst="-20.00", sgst="-20.00"))
    ]
    assert [(r.quantity, r.amounts) for r in s.hsn_b2c] == [(D("-2"), amt("-800.00", cgst="-20.00", sgst="-20.00"))]
    assert reconciliation_gap(s).is_zero()


def test_e4_a_later_note_against_b2cl_is_a_cdnur_row_in_its_own_return():
    note = line("CN/26-27/0011", 10, CN, "CDNUR", GJ, SOAP, "10", "500.00", igst="90.00", value="590.00",
                original=("INV/26-27/0003", I3), month=1, year=2027)  # fmt: skip
    s = build_sections([note])
    assert [(r.ur_type, r.pos_state_code, r.amounts) for r in s.cdnur] == [("B2CL", GJ, amt("500.00", igst="90.00"))]
    assert (s.b2b, s.b2cl, s.b2cs) == ((), (), ())


def test_a_row_that_nets_to_zero_is_dropped():
    note = line("CN/26-27/0004", 18, CN, "B2CS", KA, TEA, "5", "2000.00", igst="100.00", value="2100.00",
                original=("INV/26-27/0008", date(2026, 10, 10)))  # fmt: skip
    s = build_sections([*PART_A, note])
    assert (KA, D("5")) not in {(r.pos_state_code, r.rate) for r in s.b2cs}
    assert reconciliation_gap(s).is_zero()


# -- Decision tables ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind, cls, section",
    [
        (INV, "B2B", "b2b"),
        (INV, "B2CL", "b2cl"),
        (INV, "B2CS", "b2cs"),
        (CN, "CDNR", "cdnr"),
        (CN, "CDNUR", "cdnur"),
        (CN, "B2CS", "b2cs"),  # nets into Table 7, signed negative
    ],
)
def test_routing_table(kind, cls, section):
    assert ROUTE[(kind, cls)] == section
    ln = line("X/1", 1, kind, cls, WB, SOAP, "1", "100.00", cgst="9.00", sgst="9.00", value="118.00",
              buyer=A if cls in ("B2B", "CDNR") else None)  # fmt: skip
    built = getattr(build_sections([ln]), section)
    assert len(built) == 1
    sign = -1 if (kind, cls) == (CN, "B2CS") else 1
    assert built[0].amounts.taxable_value == sign * D("100.00")


@pytest.mark.parametrize(
    "cls, tab",
    [("B2B", "b2b"), ("CDNR", "b2b"), ("B2CL", "b2c"), ("B2CS", "b2c"), ("CDNUR", "b2c")],
)
def test_hsn_tab_table(cls, tab):  # A6: the tab follows the class (a note's follows its original)
    assert HSN_TAB[cls] == tab


@pytest.mark.parametrize(
    "kind, cls, buyer, message",
    [
        (INV, "CDNR", A, "can't be CDNR"),
        (INV, "CDNUR", None, "can't be CDNUR"),
        (CN, "B2B", A, "can't be B2B"),
        (CN, "B2CL", None, "can't be B2CL"),
        (INV, "B2B", None, "needs the buyer's GSTIN"),
        (CN, "CDNR", None, "needs the buyer's GSTIN"),
    ],
)
def test_lines_the_builder_will_not_guess_about(kind, cls, buyer, message):
    ln = line("X/1", 1, kind, cls, WB, SOAP, "1", "100.00", value="100.00", buyer=buyer)
    with pytest.raises(BadSupplyLine, match=message):
        build_sections([ln])


def test_marketplace_rows_are_r1b():
    ln = line("X/1", 1, INV, "B2CS", WB, SOAP, "1", "100.00", value="100.00")
    mp = SupplyLine(**{**ln.__dict__, "source_kind": "marketplace_row"})
    with pytest.raises(BadSupplyLine, match="R1b"):
        build_sections([mp])


def test_lines_of_one_document_must_agree_on_the_header():
    a, b = PART_A[0], PART_A[1]
    bad = SupplyLine(**{**b.__dict__, "rate": a.rate, "doc_value": D("1.00")})
    with pytest.raises(BadSupplyLine, match="disagree"):
        build_sections([a, bad])


def test_sums_are_exact_decimals_never_rounded():
    lines = [
        line(f"INV/X/{n}", 1, INV, "B2CS", WB, SOAP, "0.333", "0.01", cgst="0.00", sgst="0.00", value="0.01")
        for n in range(3)
    ]  # fmt: skip
    s = build_sections(lines)
    assert s.b2cs[0].amounts.taxable_value == D("0.03")
    assert s.hsn_b2c[0].quantity == D("0.999")  # 3 decimals kept (CA-3)


def test_an_iff_takes_no_hsn_lines():  # an IFF has no Table 12 (IFFQ FAQ 10)
    with pytest.raises(BadSupplyLine, match="hsn_lines"):
        build_sections([Q1], kind="IFF", hsn_lines=[Q1])

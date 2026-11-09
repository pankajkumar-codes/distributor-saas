"""compute → supply lines → GSTR-1 sections, end to end without a database (LLD-4 §10,
LLD-5 §5; gstr1-examples A2, A3, E1, E2).

The B2CL threshold is read from refdata/values/gstr1.yaml for the invoice date, the
same dated row load_inputs passes to compute, so E1/E2 test the cited rows rather than a
number written here. Test data only.
"""

import dataclasses
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from app.modules.filing.interface import build_sections, reconciliation_gap
from app.modules.sales.compute import FilingHeader, filing_lines
from platform_common.errors import Invalid

from .test_compute import GJ, RULES, WB, line, registered, run, unregistered

D = Decimal
T = "19AAACX1111A1Z2"
CH = "04"
REFDATA = Path(__file__).resolve().parents[6] / "refdata" / "values" / "gstr1.yaml"


def b2cl_threshold(on: date) -> Decimal:
    rows = [
        r
        for r in yaml.safe_load(REFDATA.read_text())
        if r["key"] == "gstr1.b2cl_threshold"
        and r["valid_from"] <= on
        and (r["valid_to"] is None or on < r["valid_to"])
    ]
    assert len(rows) == 1, rows
    return D(rows[0]["value"])


def rules_on(on: date):
    return dataclasses.replace(RULES, b2cl_threshold=b2cl_threshold(on))


def header(number, on, buyer=None, **kw):
    return FilingHeader(
        source_id=uuid.uuid5(uuid.NAMESPACE_URL, number),
        doc_number=number,
        doc_date=on,
        doc_kind=kw.pop("doc_kind", "invoice"),
        gstin=T,
        counterparty_gstin=buyer.gstin if buyer else None,
        **kw,
    )


def invoice(number, on, lines, buyer, *, seller_state=WB):
    comp = run(lines, buyer, seller_state=seller_state, doc_date=on, rules=rules_on(on))
    assert comp.blocks == (), comp.blocks
    return comp, filing_lines(header(number, on, buyer if buyer.gstin else None), comp)


def test_a2_invoice_1_from_compute_to_b2b_rows():
    on = date(2026, 10, 1)
    buyer = registered(WB)
    comp, lines = invoice("INV/26-27/0001", on, [line(100, "50.00", 18), line(20, "400.00", 5, hsn="0902")], buyer)
    assert comp.doc_total == D("14300.00")
    assert [(ln.supply_class, ln.rate, ln.taxable_value, ln.cgst, ln.sgst, ln.igst) for ln in lines] == [
        ("B2B", D("18"), D("5000.00"), D("450.00"), D("450.00"), D("0")),
        ("B2B", D("5"), D("8000.00"), D("200.00"), D("200.00"), D("0")),
    ]
    s = build_sections(lines)
    assert [(r.recipient_gstin, r.invoice_value, r.rate, r.amounts.taxable_value) for r in s.b2b] == [
        (buyer.gstin, D("14300.00"), D("5"), D("8000.00")),
        (buyer.gstin, D("14300.00"), D("18"), D("5000.00")),
    ]
    assert reconciliation_gap(s).is_zero()


def test_a3_inter_state_unregistered_over_the_threshold_is_b2cl():
    on = date(2026, 10, 5)
    comp, lines = invoice("INV/26-27/0003", on, [line(2000, "50.00", 18)], unregistered(GJ, GJ))
    (row,) = build_sections(lines).b2cl
    assert (row.invoice_value, row.pos_state_code, row.amounts.igst) == (D("118000.00"), GJ, D("18000.00"))


@pytest.mark.parametrize(
    "on, qty, price, rate, value, section",
    [
        # E1: before 01-08-2024 the threshold row is ₹2,50,000, so ₹1,47,500 is B2CS.
        (date(2024, 7, 15), 2500, "50.00", 18, D("147500.00"), "b2cs"),
        # The same invoice from 01-08-2024 is over the ₹1,00,000 row: B2CL.
        (date(2024, 8, 1), 2500, "50.00", 18, D("147500.00"), "b2cl"),
        # E2: ₹1,00,000.01 is more than the threshold (95,238.10 + 4,761.91).
        (date(2026, 10, 5), 1, "95238.10", 5, D("100000.01"), "b2cl"),
    ],
)
def test_e1_e2_the_dated_threshold_decides_b2cl(on, qty, price, rate, value, section):
    comp, lines = invoice("INV/X/1", on, [line(qty, price, rate)], unregistered(GJ, GJ))
    assert comp.doc_total == value
    s = build_sections(lines)
    assert [len(s.b2cl), len(s.b2cs)] == ([1, 0] if section == "b2cl" else [0, 1])


def test_a_registered_credit_note_maps_to_cdnr_with_positive_amounts():
    on = date(2026, 10, 15)
    buyer = registered(WB)
    comp = run([line(10, "50.00", 18)], buyer, seller_state=WB, doc_date=on, rules=rules_on(on))
    h = header(
        "CN/26-27/0001", on, buyer, doc_kind="credit_note", note_supply_class="CDNR",
        original_doc_number="INV/26-27/0001", original_doc_date=date(2026, 10, 1),
    )  # fmt: skip
    lines = filing_lines(h, comp)
    assert [(ln.source_kind, ln.doc_kind, ln.supply_class, ln.taxable_value) for ln in lines] == [
        ("own_credit_note", "credit_note", "CDNR", D("500.00"))
    ]
    (row,) = build_sections(lines).cdnr
    assert (row.note_value, row.amounts.cgst, row.original_doc_number) == (D("590.00"), D("45.00"), "INV/26-27/0001")


def test_utgst_goes_in_the_sgst_column():
    on = date(2026, 10, 5)
    comp, lines = invoice("INV/UT/1", on, [line(1, "100.00", 18)], registered(CH), seller_state=CH)
    assert comp.utgst
    assert [(ln.cgst, ln.sgst, ln.igst) for ln in lines] == [(D("9.00"), D("9.00"), D("0"))]


def test_only_a_finalizable_document_has_supply_lines():
    on = date(2026, 10, 5)
    blocked = run([line(1, "100.00", 18, hsn=None)], registered(WB), seller_state=WB, doc_date=on)
    with pytest.raises(Invalid) as e:
        filing_lines(header("X/1", on), blocked)
    assert e.value.code == "not_finalizable"
    ok = run([line(1, "100.00", 18)], registered(WB), seller_state=WB, doc_date=on)
    with pytest.raises(Invalid) as e:
        filing_lines(header("X/1", on, doc_kind="credit_note"), ok)
    assert e.value.code == "note_class_missing"
    with pytest.raises(Invalid) as e:
        filing_lines(header("X/1", on, note_supply_class="CDNR"), ok)
    assert e.value.code == "note_class_on_invoice"

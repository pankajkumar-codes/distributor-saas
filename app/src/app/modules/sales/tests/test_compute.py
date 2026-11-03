"""Golden tests for the invoice computation (LLD-4 §3, AC4-1, AC4-10, AC4-19, AC4-24).

Expected figures are copied from team/product/r3-invoice-examples.md (Examples 1, 2, 3,
5, 6, 7) and team/gst/tax-computation.md §8 (G1-G13, G16). G14 and G15 (tax-inclusive
prices) are left out: R1 computes tax-exclusive only, inclusive pricing is CA-pending
(LLD-4 §15, EM 2026-11-03). Rates and thresholds below are test fixtures standing in for
product data and refdata, not statements of GST law.
"""

import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import pytest

from app.modules.catalog.interface import ProductForLine
from app.modules.sales.compute import Buyer, ComputeInput, LineIn, Rules, Seller, compute, inr
from platform_common.errors import Invalid

D = Decimal
TODAY = date(2026, 10, 20)
MH, KA, GJ, WB, CH, LA = "27", "29", "24", "19", "04", "38"
RULES = Rules(
    rounding_mode="ROUND_HALF_UP",
    round_off_line=False,
    utgst_state_codes=frozenset({"04", "25", "26", "31", "35", "38"}),
    b2cl_threshold=D("100000.00"),
    unregistered_address_threshold=D("50000.00"),
    eway_threshold=D("50000.00"),
)


def product(rate, *, code="SYN", hsn="3401", **kw):
    fields = dict(
        product_id=uuid.uuid4(),
        code=code,
        name=code,
        hsn=hsn,
        uqc="NOS",
        sale_rate=D("1.00"),
        tax_category="taxable",
        has_cess=False,
        status="active",
        rate=None if rate is None else D(rate),
        rate_id=uuid.uuid4(),
        rate_valid_from=date(2025, 9, 22),
        rate_confirmed=True,
        rate_changed_within_warning_window=False,
    )
    return ProductForLine(**{**fields, **kw})


def line(qty, price, rate, *, pct=None, amount=None, n=None, **kw):
    kind, value = (
        ("percent", D(pct)) if pct is not None else ("amount", D(amount)) if amount is not None else (None, None)
    )
    return LineIn(n or 0, product(rate, **kw), D(qty), D(price), kind, value)


def numbered(lines):
    return tuple(
        LineIn(
            i + 1, *(getattr(ln, f) for f in ("product", "quantity", "unit_price", "discount_kind", "discount_value"))
        )
        for i, ln in enumerate(lines)
    )


def registered(state, *, ship=None, **kw):
    return Buyer(
        gstin=f"{state}AAACX2222B1ZU",
        gstin_state_code=state,
        name="Synthetic Buyer",
        bill_to_state=state,
        ship_to_state=ship or state,
        has_delivery_address=True,
        **kw,
    )


def unregistered(bill=None, ship=None, *, name="Cash buyer", address=True):
    return Buyer(
        gstin=None,
        gstin_state_code=None,
        name=name,
        bill_to_state=bill,
        ship_to_state=ship,
        has_delivery_address=address,
    )


def run(lines, buyer, *, seller_state=MH, rules=RULES, **kw):
    seller = Seller(state_code=seller_state, hsn_min_digits=4, einvoice_status="no")
    kw.setdefault("doc_date", TODAY)
    return compute(ComputeInput(today=TODAY, seller=seller, buyer=buyer, lines=numbered(lines), rules=rules, **kw))


def amounts(c, *names):
    return [tuple(getattr(ln, n) for n in names) for ln in c.lines]


def taxes(c):
    return [tuple((t.component, t.amount) for t in ln.taxes) for ln in c.lines]


EX1 = [line(3, "333.33", 18, pct=5, code="SYN-001"), line(7, "49.99", 5, code="SYN-002")]
EX5 = [*EX1, line(4, "87.50", 18, code="SYN-004")]


# -- r3 examples -------------------------------------------------------------------------
def test_example_1_same_state():
    c = run(EX1, registered(MH))
    assert amounts(c, "taxable") == [(D("949.99"),), (D("349.93"),)]
    assert taxes(c) == [(("CGST", D("85.50")), ("SGST", D("85.50"))), (("CGST", D("8.75")), ("SGST", D("8.75")))]
    assert [ln.total for ln in c.lines] == [D("1120.99"), D("367.43")]
    assert (c.taxable_total, c.cgst_total, c.sgst_total, c.igst_total, c.doc_total) == (
        D("1299.92"),
        D("94.25"),
        D("94.25"),
        D("0"),
        D("1488.42"),
    )
    assert (c.pos_state_code, c.is_inter_state, c.utgst, c.supply_class) == (MH, False, False, "B2B")
    assert (c.gross_total, c.line_discount_total) == (D("1349.92"), D("50.00"))  # 999.99 - 949.99 shown as discount
    assert (c.rounding_mode, c.method_version, c.blocks) == ("ROUND_HALF_UP", "apportion-v2", ())
    assert c.amount_in_words == "Rupees One Thousand Four Hundred Eighty Eight and Forty Two Paise Only"


def test_example_2_other_state():
    c = run(EX1, registered(KA))
    assert taxes(c) == [(("IGST", D("171.00")),), (("IGST", D("17.50")),)]
    assert (c.taxable_total, c.igst_total, c.cgst_total, c.doc_total) == (
        D("1299.92"),
        D("188.50"),
        D("0"),
        D("1488.42"),
    )
    assert [t.rate for t in c.lines[0].taxes] == [D("18")]


def test_example_3_each_half_rounded_on_its_own():  # 1.80, not 1.81 (R3)
    c = run([line(1, "10.05", 18)], registered(MH))
    assert taxes(c) == [(("CGST", D("0.90")), ("SGST", D("0.90")))]
    assert c.lines[0].taxes[0].rate == D("9")


def test_example_5_discount_then_freight_same_state():
    c = run(EX5, registered(MH), invoice_discount=D("100.00"), charges=(("Freight", D("150.00")),))
    assert amounts(c, "base", "discount_share", "charge_share", "taxable") == [
        (D("949.99"), D("57.58"), D("86.37"), D("978.78")),
        (D("349.93"), D("21.21"), D("31.81"), D("360.53")),
        (D("350.00"), D("21.21"), D("31.82"), D("360.61")),
    ]
    assert [ln.taxes[0].amount for ln in c.lines] == [D("88.09"), D("9.01"), D("32.45")]
    assert [ln.total for ln in c.lines] == [D("1154.96"), D("378.55"), D("425.51")]
    assert (c.invoice_discount, c.charges_total, c.taxable_total, c.cgst_total, c.sgst_total, c.doc_total) == (
        D("100.00"),
        D("150.00"),
        D("1699.92"),
        D("129.55"),
        D("129.55"),
        D("1959.02"),
    )


def test_example_6_discount_then_packing_other_state():
    c = run(EX5, registered(KA), invoice_discount=D("49.99"), charges=(("Packing", D("75.50")),))
    assert amounts(c, "discount_share", "charge_share", "taxable") == [
        (D("28.78"), D("43.47"), D("964.68")),
        (D("10.60"), D("16.01"), D("355.34")),
        (D("10.61"), D("16.02"), D("355.41")),
    ]
    assert taxes(c) == [(("IGST", D("173.64")),), (("IGST", D("17.77")),), (("IGST", D("63.97")),)]
    assert (c.taxable_total, c.igst_total, c.doc_total) == (D("1675.43"), D("255.38"), D("1930.81"))


def test_example_7_the_last_line_takes_the_remainder():
    c = run([line(1, 100, 18), line(1, 100, 5), line(1, 100, 18)], registered(MH), invoice_discount=D("1.00"))
    assert amounts(c, "discount_share", "taxable") == [
        (D("0.33"), D("99.67")),
        (D("0.33"), D("99.67")),
        (D("0.34"), D("99.66")),
    ]


def test_no_share_is_ever_negative():  # Staff 2 (4), #80: rounding each share half-up gave -0.01
    c = run([line(1, 1, 18)] * 4, registered(MH), invoice_discount=D("0.02"))
    assert [ln.discount_share for ln in c.lines] == [D("0.00"), D("0.00"), D("0.01"), D("0.01")]
    c = run([line(1, 1, 18)] * 4 + [line(1, "0.01", 18)], registered(MH), invoice_discount=D("2.42"))
    assert [ln.discount_share for ln in c.lines] == [
        D("0.60"),
        D("0.60"),
        D("0.60"),
        D("0.61"),
        D("0.01"),
    ]  # 0.6035 x4, 0.0060
    assert c.method_version == "apportion-v2"


def test_apportion_sweep_shares_sum_to_the_total_and_stay_within_a_paisa():
    from app.modules.sales.compute.core import _apportion

    weight_sets = [
        [D(w) for w in ws]
        for ws in (
            ["1.00"] * 4,
            ["1.00"] * 7,
            ["0.01", "0.01", "0.01"],
            ["0.03", "0.03", "0.01"],
            ["100.00", "0.01"],
            ["0.01", "100.00"],
            ["949.99", "349.93", "350.00"],
            ["0.00", "5.00", "0.00"],
            ["2.50", "2.50", "2.50", "2.49"],
        )
    ]
    for weights in weight_sets:
        whole = sum(weights)
        for paise in range(1, int(whole * 100) + 1, max(1, int(whole * 100) // 400)):
            total = D(paise) / 100
            shares = _apportion(total, weights, "invoice_discount")
            assert sum(shares) == total, (weights, total, shares)
            for s, w in zip(shares, weights, strict=True):
                exact = total * w / whole
                assert D(0) <= s <= w and abs(s - exact) < D("0.01"), (weights, total, shares)


# -- One rounding for the line base (RM44-1, AC4-19) -----------------------------------
def three_roundings(qty, price, pct):
    r = lambda x: x.quantize(D("0.01"), rounding=ROUND_HALF_UP)  # noqa: E731
    gross = r(qty * price)
    return gross - r(gross * pct / 100)


@pytest.mark.parametrize(
    "qty, price, pct, base, discount",
    [
        ("1", "0.10", "5", "0.10", "0.00"),  # LLD-4's tie case
        ("1.250", "49.99", "5", "59.36", "3.13"),  # a 3-decimal quantity: 59.363125 once, 59.37 three times
    ],
)
def test_the_line_base_is_rounded_once(qty, price, pct, base, discount):
    c = run([line(qty, price, 18, pct=pct)], registered(MH))
    assert (c.lines[0].base, c.lines[0].line_discount) == (D(base), D(discount))
    assert c.lines[0].gross == c.lines[0].base + c.lines[0].line_discount
    # The planted alternative: rounding gross, discount and base separately gives
    # another figure, so this test would catch that implementation.
    assert three_roundings(D(qty), D(price), D(pct)) != D(base)


def test_an_amount_discount_comes_off_the_rounded_gross():
    c = run([line(3, "333.33", 18, amount="49.99")], registered(MH))
    assert (c.lines[0].gross, c.lines[0].line_discount, c.lines[0].base) == (D("999.99"), D("49.99"), D("950.00"))


# -- tax-computation §8 ------------------------------------------------------------------
def test_g1_registered_other_state_delivery():
    c = run([line(1, 100, 18)], registered(KA))
    assert (c.pos_state_code, c.is_inter_state, c.supply_class) == (KA, True, "B2B")
    assert [t.component for t in c.lines[0].taxes] == ["IGST"]


def test_g2_bill_to_ship_to_uses_the_buyer_s_gstin_state():
    c = run([line(1, 100, 18)], registered(KA, ship=MH, ship_to_third_party=True))
    assert (c.pos_state_code, c.is_inter_state) == (KA, True)


def test_g3_unregistered_delivery_state_wins_over_billing():
    c = run([line(1, 100, 18)], unregistered(bill=GJ, ship=MH))
    assert (c.pos_state_code, c.is_inter_state, c.supply_class) == (MH, False, "B2CS")


def test_g4_unregistered_with_only_a_state():
    c = run([line(1, 100, 18)], unregistered(bill=MH, address=False))
    assert (c.pos_state_code, c.is_inter_state, c.blocks) == (MH, False, ())


def test_g5_utgst_only_inside_the_ut():
    c = run([line(1, 100, 18)], unregistered(ship=LA))
    assert (c.is_inter_state, c.utgst, [t.component for t in c.lines[0].taxes]) == (True, False, ["IGST"])


def test_g6_cgst_and_utgst_in_chandigarh():
    c = run([line(1, 100, 18)], registered(CH), seller_state=CH)
    assert (c.utgst, [t.component for t in c.lines[0].taxes]) == (True, ["CGST", "UTGST"])
    assert c.sgst_total == D("9.00")  # sgst_total carries UTGST


@pytest.mark.parametrize("taxable, total, cls", [("84745.76", "100000.00", "B2CS"), ("84745.77", "100000.01", "B2CL")])
def test_g7_g8_b2cl_is_more_than_the_threshold(taxable, total, cls):  # AC4-10
    c = run([line(1, taxable, 18)], unregistered(ship=GJ))
    assert (c.doc_total, c.supply_class) == (D(total), cls)


def test_b2cl_threshold_is_the_rule_in_force():  # GSTR-1 A9 E1: the dated row decides
    old = Rules(**{**RULES.__dict__, "b2cl_threshold": D("250000.00")})
    assert run([line(1, "127118.64", 18)], unregistered(ship=GJ), rules=old).supply_class == "B2CS"


def test_g9_unregistered_at_50000_needs_name_and_delivery_address():
    lines = [line(1, "42372.88", 18)]  # 42,372.88 + 2 × 3,813.56 = 50,000.00
    c = run(lines, unregistered(bill=MH, address=False))
    assert c.doc_total == D("50000.00")
    assert [b.code for b in c.blocks] == ["buyer_address_required"]
    assert run(lines, unregistered(bill=MH, ship=MH, name="  ")).blocks[0].code == "buyer_address_required"
    assert run(lines, unregistered(bill=MH, ship=MH)).blocks == ()
    assert run([line(1, "42372.87", 18)], unregistered(bill=MH, address=False)).blocks == ()  # 49,999.99


def test_g10_invoice_discount_by_line_value():
    c = run([line(1, 600, 18), line(1, 400, 5)], registered(MH), invoice_discount=D("100"))
    assert [ln.discount_share for ln in c.lines] == [D("60.00"), D("40.00")]
    assert [ln.taxable for ln in c.lines] == [D("540.00"), D("360.00")]


def test_g11_freight_takes_the_goods_rates():
    c = run([line(1, 600, 18), line(1, 400, 5)], registered(MH), charges=(("Freight", D("200")),))
    assert [(ln.charge_share, ln.rate) for ln in c.lines] == [(D("120.00"), D("18")), (D("80.00"), D("5"))]


def test_g12_exempt_lines_are_blocked():
    c = run([line(1, 100, 0), line(1, 100, 5, tax_category="exempt"), line(1, 100, 5, has_cess=True)], registered(MH))
    assert [(b.code, b.line_no) for b in c.blocks] == [("rate_zero", 1), ("product_exempt", 2), ("product_has_cess", 3)]
    assert c.blocks[0].fix == c.blocks[1].fix == "Exempt items need a bill of supply; not supported yet."


def test_g13_a_recent_rate_change_warns():
    c = run([line(1, 100, 5, rate_changed_within_warning_window=True, rate_confirmed=False)], registered(MH))
    assert c.blocks == () and [w.code for w in c.warnings] == ["rate_unconfirmed", "rate_changed_recently"]


def test_g16_place_of_supply_override_needs_a_reason():
    c = run([line(1, 100, 18)], registered(MH), pos_override=KA, pos_override_reason="Goods delivered in Bengaluru")
    assert (c.computed_pos, c.pos_state_code, c.is_inter_state, c.blocks) == (MH, KA, True, ())
    c = run([line(1, 100, 18)], registered(MH), pos_override=KA, pos_override_reason=" ")
    assert [b.code for b in c.blocks] == ["pos_override_reason_missing"]


# -- Place of supply edges (LLD-4 §15, EM 2026-11-03) ----------------------------------
def test_a_registered_buyer_without_a_ship_to_state_is_blocked_not_defaulted():
    c = run([line(1, 100, 18)], Buyer("27AAACX2222B1ZU", MH, "B", MH, None, True))
    assert (c.pos_state_code, c.supply_class, c.lines[0].taxes) == (None, "B2B", ())
    assert [b.code for b in c.blocks] == ["buyer_state_missing"]


def test_case_d_registered_buyer_collects():
    c = run([line(1, 100, 18)], registered(KA, ship=MH, customer_collects=True))
    assert (c.pos_state_code, [w.code for w in c.warnings]) == (KA, ["pos_customer_collects"])
    c = run([line(1, 100, 18)], unregistered(ship=MH))  # unregistered: case C, no warning
    assert c.warnings == ()


def test_unregistered_buyer_with_no_state_is_blocked():
    c = run([line(1, 100, 18)], unregistered())
    assert ([b.code for b in c.blocks], c.supply_class) == (["buyer_state_missing"], None)


# -- Refusals (422) -----------------------------------------------------------------------
def test_a_charge_with_no_value_left_is_refused():  # AC4-24
    with pytest.raises(Invalid) as e:
        run([line(1, 100, 18)], registered(MH), invoice_discount=D("100"), charges=(("Freight", D("10")),))
    assert e.value.code == "charge_without_value"
    assert run([line(1, 100, 18)], registered(MH), invoice_discount=D("100")).taxable_total == D("0.00")


def test_a_draft_without_lines_keeps_its_charge_and_discount():  # Staff, #80
    c = run([], registered(MH), invoice_discount=D("10"), charges=(("Freight", D("150")),))
    assert [b.code for b in c.blocks] == ["no_lines"]
    assert (c.invoice_discount, c.charges_total, c.taxable_total, c.doc_total) == (D("10"), D("150"), D("0"), D("0"))


@pytest.mark.parametrize(
    "lines, kw, code",
    [
        ([line(1, 100, 18)], {"invoice_discount": D("100.01")}, "invoice_discount_above_value"),
        ([line(1, 0, 18)], {"invoice_discount": D("1")}, "invoice_discount_without_value"),
        ([line(1, 100, 18)], {"invoice_discount": D("0.005")}, "invoice_discount_not_paise"),
        ([line(1, 100, 18, amount="100.01")], {}, "discount_above_value"),
        ([line(1, 100, 18, pct="100.5")], {}, "discount_percent_range"),
        ([line(0, 100, 18)], {}, "quantity_not_positive"),
        ([line(1, -1, 18)], {}, "price_negative"),
        ([line(1, 100, 18)], {"charges": (("Freight", D("-1")),)}, "charge_negative"),
    ],
)
def test_amounts_that_cannot_be_computed_are_refused(lines, kw, code):
    with pytest.raises(Invalid) as e:
        run(lines, registered(MH), **kw)
    assert e.value.code == code


# -- Other checks --------------------------------------------------------------------------
def test_line_and_product_blocks():
    lines = [
        LineIn(0, None, D(1), D(1)),
        line(1, 100, 18, status="archived"),
        line(1, 100, 18, hsn=None),
        line(1, 100, 18, hsn="340"),
        line(1, 100, None),
        LineIn(0, product(18), None, None),
    ]
    c = run(lines, registered(MH))
    assert [(b.code, b.line_no, b.field) for b in c.blocks] == [
        ("product_unknown", 1, "lines.0.product_id"),
        ("product_archived", 2, "lines.1.product_id"),
        ("hsn_missing", 3, "lines.2.product_id"),
        ("hsn_too_short", 4, "lines.3.product_id"),
        ("rate_missing", 5, "lines.4.product_id"),
        ("quantity_missing", 6, "lines.5.quantity"),
        ("price_missing", 6, "lines.5.unit_price"),
    ]


def test_a_short_hsn_without_last_year_s_band_says_which_band_to_set():  # EM decision (b), #85
    seller = Seller(
        state_code=MH,
        hsn_min_digits=6,
        einvoice_status="no",
        hsn_band_missing_fy="2025-26",
        hsn_min_digits_if_band_set=4,
    )
    inp = ComputeInput(
        doc_date=TODAY,
        today=TODAY,
        seller=seller,
        buyer=registered(MH),
        lines=numbered([line(1, 100, 18, hsn="3401"), line(1, 100, 18, hsn="340111"), line(1, 100, 18, hsn="34")]),
        rules=RULES,
    )
    blocks = compute(inp).blocks
    # A code the band would allow says which band to set; one too short either way does not.
    assert [(b.code, b.field, b.line_no) for b in blocks] == [
        ("hsn_needs_turnover_band", "business.turnover_band", 1),
        ("hsn_too_short", "lines.2.product_id", 3),
    ]
    assert blocks[0].fix.startswith("Tell us last year's turnover band (FY 2025-26) to use 4-digit HSN codes.")


def test_document_blocks_and_warnings():
    seller = Seller(state_code=MH, hsn_min_digits=4, einvoice_status="applies", ready_missing=("address",))
    inp = ComputeInput(
        doc_date=date(2026, 10, 21),
        today=TODAY,
        seller=seller,
        buyer=registered(MH),
        lines=numbered([line(1, 50000, 18)]),
        rules=RULES,
    )
    c = compute(inp)
    assert [b.code for b in c.blocks] == ["business_not_ready", "einvoice_applies", "doc_date_future"]
    assert [w.code for w in c.warnings] == ["eway_bill_needed"]
    c = compute(
        ComputeInput(
            **{
                **inp.__dict__,
                "seller": Seller(MH, 4, "unsure"),
                "doc_date": TODAY,
                "buyer": unregistered(ship=MH),
                "has_eway_details": True,
            }
        )
    )
    assert (c.blocks, c.warnings) == ((), ())  # e-invoicing concerns B2B only
    assert (
        compute(
            ComputeInput(
                **{**inp.__dict__, "seller": Seller(MH, 4, "unsure"), "doc_date": TODAY, "has_eway_details": True}
            )
        )
        .warnings[0]
        .code
        == "einvoice_unsure"
    )
    assert [b.code for b in run([], registered(MH)).blocks] == ["no_lines"]


def test_the_round_off_line_only_when_refdata_says_so():
    on = Rules(**{**RULES.__dict__, "round_off_line": True})
    c = run(EX1, registered(MH), rules=on)
    assert (c.round_off, c.doc_total) == (D("-0.42"), D("1488.00"))
    assert run(EX1, registered(MH)).round_off == D("0")


def test_rounding_mode_comes_from_refdata():
    even = Rules(**{**RULES.__dict__, "rounding_mode": "ROUND_HALF_EVEN"})
    # 7 × 49.99 × 2.5% = 8.74825: half-up and half-even agree; 10.05 × 9% = 0.9045 likewise.
    # 1 × 0.25 at 18% intra: 0.0225 → 0.02 either way; use a true tie: 0.50 × 5% = 0.025.
    c_up, c_even = run([line(1, "0.50", 10)], registered(MH)), run([line(1, "0.50", 10)], registered(MH), rules=even)
    assert (c_up.cgst_total, c_even.cgst_total, c_even.rounding_mode) == (D("0.03"), D("0.02"), "ROUND_HALF_EVEN")


@pytest.mark.parametrize(
    "amount, words",
    [
        ("1488.42", "Rupees One Thousand Four Hundred Eighty Eight and Forty Two Paise Only"),
        ("1959.02", "Rupees One Thousand Nine Hundred Fifty Nine and Two Paise Only"),
        ("118000.00", "Rupees One Lakh Eighteen Thousand Only"),
        (
            "12345678.90",
            "Rupees One Crore Twenty Three Lakh Forty Five Thousand Six Hundred Seventy Eight and Ninety Paise Only",
        ),
        ("1000000000.00", "Rupees One Hundred Crore Only"),
        ("0.00", "Rupees Zero Only"),
    ],
)
def test_amount_in_words(amount, words):
    assert inr(D(amount)) == words


def test_amount_in_words_refuses_floats_and_sub_paisa():
    for bad in (1.5, D("1.005"), D("-1.00")):
        with pytest.raises(ValueError):
            inr(bad)

"""The invoice computation (LLD-4 §3, L4-1): place of supply, line amounts, the invoice
discount and charges apportioned to lines, tax per line and component, totals,
classification, and the block and warn checks of §3.4.

Pure: it reads only its input. load_inputs (inputs.py) does the database reads, so the
golden tests drive this function directly. Every amount is Decimal and is rounded once,
where LLD-4 says, with the rounding mode from refdata.
"""

from decimal import Decimal

from platform_common.errors import Invalid
from platform_common.money import round_to_paise

from .model import ComputeInput, Computation, Issue, LineIn, LineOut, Tax
from .words import inr

ZERO = Decimal()
RUPEE = Decimal(1)
HALVES = 2  # CGST and SGST/UTGST each take half the rate (LLD-4 §3.2 step 5, tax-computation §3)

_EXEMPT_FIX = "Exempt items need a bill of supply; not supported yet."  # BH-2


class _Checks:
    def __init__(self):
        self.blocks: list[Issue] = []
        self.warnings: list[Issue] = []

    def block(self, code, fix, field=None, line_no=None):
        self.blocks.append(Issue(code, fix, field, line_no))

    def warn(self, code, fix, field=None, line_no=None):
        self.warnings.append(Issue(code, fix, field, line_no))


def compute(inp: ComputeInput) -> Computation:
    mode = inp.rules.rounding_mode

    def r(x: Decimal) -> Decimal:
        return round_to_paise(x, rounding=mode)

    checks = _Checks()
    computed_pos, pos = _place_of_supply(inp, checks)
    inter = None if pos is None else pos != inp.seller.state_code
    utgst = inter is False and pos in inp.rules.utgst_state_codes

    # Line base, gross and line discount: one rounding for the base (R1, RM44-1).
    bases = [_base(i, line, r) for i, line in enumerate(inp.lines)]
    discount_shares = _apportion(inp.invoice_discount, [b for _, b in bases], r, "invoice_discount")
    after = [b - s for (_, b), s in zip(bases, discount_shares, strict=True)]
    if any(a < ZERO for a in after):
        raise Invalid(
            "discount_makes_line_negative",
            "The invoice discount would take a line below zero.",
            field="invoice_discount",
        )
    charges_total = _charges_total(inp)
    if charges_total > ZERO and sum(after, ZERO) == ZERO:  # AC4-24: never divides by zero
        raise Invalid("charge_without_value", "A charge needs lines with value after the discount.", field="charges")
    charge_shares = _apportion(charges_total, after, r, "charges")

    lines = []
    for i, line in enumerate(inp.lines):
        gross, base = bases[i]
        taxable = after[i] + charge_shares[i]
        rate = _line_checks(i, line, inp, checks)
        taxes = () if rate is None or inter is None else _taxes(taxable, rate, inter, utgst, r)
        lines.append(
            LineOut(
                line_no=line.line_no,
                product=line.product,
                quantity=line.quantity,
                unit_price=line.unit_price,
                gross=gross,
                line_discount=gross - base,
                base=base,
                discount_share=discount_shares[i],
                charge_share=charge_shares[i],
                taxable=taxable,
                rate=rate,
                taxes=taxes,
                total=taxable + sum((t.amount for t in taxes), ZERO),
            )
        )

    def total_of(*components):
        return sum((t.amount for ln in lines for t in ln.taxes if t.component in components), ZERO)

    taxable_total = sum((ln.taxable for ln in lines), ZERO)
    cgst, sgst, igst = total_of("CGST"), total_of("SGST", "UTGST"), total_of("IGST")
    total = taxable_total + cgst + sgst + igst
    round_off = total.quantize(RUPEE, rounding=mode) - total if inp.rules.round_off_line else ZERO
    doc_total = total + round_off

    supply_class = _classify(inp, inter, doc_total)
    _document_checks(inp, checks, doc_total, supply_class)
    if not inp.lines:
        checks.block("no_lines", "Add at least one line.", field="lines")

    return Computation(
        computed_pos=computed_pos,
        pos_state_code=pos,
        is_inter_state=inter,
        utgst=utgst,
        supply_class=supply_class,
        lines=tuple(lines),
        gross_total=sum((ln.gross for ln in lines), ZERO),
        line_discount_total=sum((ln.line_discount for ln in lines), ZERO),
        invoice_discount=inp.invoice_discount,
        charges_total=charges_total,
        taxable_total=taxable_total,
        cgst_total=cgst,
        sgst_total=sgst,
        igst_total=igst,
        round_off=round_off,
        doc_total=doc_total,
        amount_in_words=inr(doc_total),
        rounding_mode=mode,
        blocks=tuple(checks.blocks),
        warnings=tuple(checks.warnings),
    )


# -- Place of supply (§3.1, tax-computation §2) ------------------------------------------
def _place_of_supply(inp: ComputeInput, checks: _Checks) -> tuple[str | None, str | None]:
    b = inp.buyer
    if b.gstin:
        if b.ship_to_third_party:  # case B: the buyer's principal place of business
            computed = b.gstin_state_code
        elif b.customer_collects:  # case D, registered (LLD-4 §15, EM 2026-11-03)
            computed = b.gstin_state_code
            checks.warn(
                "pos_customer_collects",
                "Place of supply for goods the buyer collects is set to the buyer's GSTIN state. CA to confirm.",
                field="customer_collects",
            )
        else:  # case A: where the goods are delivered; never the GSTIN state as a fallback
            computed = b.ship_to_state
    else:  # case C: unregistered or cash sale (and case D unregistered)
        computed = b.ship_to_state or b.bill_to_state
    if computed is None:
        checks.block("buyer_state_missing", "Add the buyer's state.", field="ship_to.state_code")

    if inp.pos_override is None:
        return computed, computed
    if not (inp.pos_override_reason or "").strip():
        checks.block(
            "pos_override_reason_missing",
            "Say why you changed the place of supply.",
            field="pos_override_reason",
        )
    return computed, inp.pos_override


# -- Line amounts (§3.2 steps 1-4) -------------------------------------------------------
def _base(i: int, line: LineIn, r) -> tuple[Decimal, Decimal]:
    """(gross, base) for one line. A line still missing its quantity or price counts as
    zero here and is blocked in _line_checks."""
    q, p = line.quantity, line.unit_price
    if q is not None and q <= ZERO:
        raise Invalid("quantity_not_positive", "Quantity must be more than zero.", field=f"lines.{i}.quantity")
    if p is not None and p < ZERO:
        raise Invalid("price_negative", "Price can't be below zero.", field=f"lines.{i}.unit_price")
    value = ZERO if q is None or p is None else q * p
    gross = r(value)
    kind, d = line.discount_kind, line.discount_value
    if kind is None or d is None:
        return gross, gross
    if kind == "percent":
        if not ZERO <= d <= 100:
            raise Invalid("discount_percent_range", "A discount is 0 to 100%.", field=f"lines.{i}.discount_value")
        return gross, r(value * (100 - d) / 100)
    if not ZERO <= d <= gross:
        raise Invalid(
            "discount_above_value", "The discount is more than the line's value.", field=f"lines.{i}.discount_value"
        )
    return gross, gross - d


def _apportion(total: Decimal, weights: list[Decimal], r, field: str) -> list[Decimal]:
    """`total` shared in proportion to `weights`, each share rounded, the last line taking
    the remainder (A2, A3; Example 7)."""
    if total == ZERO or not weights:
        return [ZERO] * len(weights)
    whole = sum(weights, ZERO)
    if total < ZERO:
        raise Invalid(f"{field}_negative", "The amount can't be below zero.", field=field)
    if whole <= ZERO:
        raise Invalid(f"{field}_without_value", "The lines have no value to share it over.", field=field)
    if field == "invoice_discount" and total > whole:
        raise Invalid("invoice_discount_above_value", "The discount is more than the lines' value.", field=field)
    shares = [r(total * w / whole) for w in weights[:-1]]
    return [*shares, total - sum(shares, ZERO)]


def _charges_total(inp: ComputeInput) -> Decimal:
    for i, (_, amount) in enumerate(inp.charges):
        if amount < ZERO:
            raise Invalid("charge_negative", "A charge can't be below zero.", field=f"charges.{i}.amount")
    return sum((a for _, a in inp.charges), ZERO)


def _taxes(taxable: Decimal, rate: Decimal, inter: bool, utgst: bool, r) -> tuple[Tax, ...]:
    """§3.2 step 5: inter-state IGST at the full rate; intra-state two halves, each rounded
    on its own (R3, Example 3)."""
    if inter:
        return (Tax("IGST", rate, r(taxable * rate / 100)),)
    half = rate / HALVES
    amount = r(taxable * half / 100)
    return (Tax("CGST", half, amount), Tax("UTGST" if utgst else "SGST", half, amount))


# -- Checks (§3.4) -----------------------------------------------------------------------
def _line_checks(i: int, line: LineIn, inp: ComputeInput, checks: _Checks) -> Decimal | None:
    """Blocks and warnings for one line; returns the rate to tax it at, or None."""
    n, at = line.line_no, f"lines.{i}"
    if line.quantity is None:
        checks.block("quantity_missing", "Add a quantity.", f"{at}.quantity", n)
    if line.unit_price is None:
        checks.block("price_missing", "Add a price.", f"{at}.unit_price", n)
    p = line.product
    if p is None:
        checks.block("product_unknown", "Choose a product.", f"{at}.product_id", n)
        return None
    if p.status != "active":
        checks.block(
            "product_archived", "This product is archived. Restore it or choose another.", f"{at}.product_id", n
        )
    if p.tax_category != "taxable":
        checks.block("product_exempt", _EXEMPT_FIX, f"{at}.product_id", n)
    if p.has_cess:
        checks.block("product_has_cess", "Products with compensation cess aren't supported yet.", f"{at}.product_id", n)
    hsn = p.hsn or ""
    if not hsn:
        checks.block("hsn_missing", "Add the product's HSN code.", f"{at}.product_id", n)
    elif len(hsn) < inp.seller.hsn_min_digits:
        checks.block(
            "hsn_too_short",
            f"Your business needs HSN codes of at least {inp.seller.hsn_min_digits} digits.",
            f"{at}.product_id",
            n,
        )
    if p.rate is None:
        checks.block("rate_missing", "The product has no GST rate on the invoice date.", f"{at}.product_id", n)
        return None
    if p.rate == ZERO:  # tax-computation §5, G12; LLD-4 §15 (EM 2026-11-03)
        checks.block("rate_zero", _EXEMPT_FIX, f"{at}.product_id", n)
    if not p.rate_confirmed:
        checks.warn(
            "rate_unconfirmed", "This product's GST rate isn't confirmed with your CA yet.", f"{at}.product_id", n
        )
    if p.rate_changed_within_warning_window:
        checks.warn(
            "rate_changed_recently",
            "This product's GST rate changed shortly before the invoice date. Check the rate applies.",
            f"{at}.product_id",
            n,
        )
    return p.rate


def _classify(inp: ComputeInput, inter: bool | None, doc_total: Decimal):
    """§3.3, tax-computation §7: B2CL is strictly more than the threshold (G7, G8)."""
    if inp.buyer.gstin:
        return "B2B"
    if inter is None:
        return None
    return "B2CL" if inter and doc_total > inp.rules.b2cl_threshold else "B2CS"


def _document_checks(inp: ComputeInput, checks: _Checks, doc_total: Decimal, supply_class) -> None:
    b, rules = inp.buyer, inp.rules
    if not b.gstin and doc_total >= rules.unregistered_address_threshold:  # Rule 46(e), G9
        if not (b.name or "").strip() or not b.has_delivery_address:
            checks.block(
                "buyer_address_required",
                "For this amount an unregistered buyer's name and delivery address are required.",
                field="ship_to",
            )
    if inp.seller.ready_missing:
        checks.block("business_not_ready", "Add your address first.", field="business")
    if supply_class == "B2B" and inp.seller.einvoice_status == "applies":  # L4-4
        checks.block(
            "einvoice_applies",
            "E-invoicing applies to your business; the app can't issue e-invoices yet.",
        )
    if supply_class == "B2B" and inp.seller.einvoice_status == "unsure":
        checks.warn("einvoice_unsure", "Check whether e-invoicing applies to your business.")
    if inp.doc_date > inp.today:
        checks.block("doc_date_future", "The invoice date can't be after today.", field="doc_date")
    if doc_total > rules.eway_threshold and not inp.has_eway_details:
        checks.warn("eway_bill_needed", "An e-way bill is needed for this value. Add its details.", field="eway")

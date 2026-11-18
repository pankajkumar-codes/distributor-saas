"""The GST-filing plan and the invoicing plan, and the one place that says they are free for now (R1-M9, R2-M7).

Pankaj's decision (D-074): payments are a placeholder in R1. The plans and their prices are shown, nothing is charged
and no payment provider is connected. `FREE_FOR_NOW` is the single switch. While it is true, `entitlement.allowed` says yes
to every business and the screen says "free for now". When the payment provider is ready, set it to false and install a real
check with `entitlement.set_check`; nothing else changes.

Prices are release-plan-v2 section 6 and BRD v1.3 (GST-filing-only plan, in whole rupees); our fee carries GST on top.
"""

FREE_FOR_NOW = True

GST_NOTE = "plus 18% GST on our fee"

# The filing-only plan: price in whole rupees by filing frequency.
FILING_ONLY = {"monthly": 499, "quarterly": 1499}

# The invoicing plan (R2, release-plan-v2 section 6): the first FREE_INVOICES finalized invoices of a business are free,
# then the chosen plan applies; GST filing support is included. Prices in whole rupees, plus 18% GST on our fee.
INVOICING = {"monthly": 999, "quarterly": 2499}
FREE_INVOICES = 10

PLAN_PRICES = {"gst_filing": FILING_ONLY, "invoicing": INVOICING}


def prorated_change(from_plan: str, from_frequency: str, to_plan: str, to_frequency: str, *, days_left: int,
                    period_days: int) -> dict:
    """What a plan change shows before the business confirms (display only; nothing is charged while `FREE_FOR_NOW`).
    The unused part of the current paid period is credited at the current price, `days_left` of `period_days`, and the
    new plan's full price starts now. All amounts are in rupees before GST on our fee, as strings with two decimals;
    how our own fee is taxed is decision D6, so no GST amount is computed here. A change that is a downgrade shows
    `amount_due` 0.00 and the unused credit left over."""
    from decimal import ROUND_HALF_UP, Decimal

    try:
        old, new = PLAN_PRICES[from_plan][from_frequency], PLAN_PRICES[to_plan][to_frequency]
    except KeyError:
        raise ValueError("unknown plan or frequency") from None
    if not 0 < period_days <= 366 or not 0 <= days_left <= period_days:  # noqa: PLR2004 (a year is the longest period)
        raise ValueError("days_left must be within period_days")
    cent = Decimal("0.01")
    credit = (Decimal(old) * days_left / period_days).quantize(cent, ROUND_HALF_UP)
    due = max(Decimal(new) - credit, Decimal())
    left = max(credit - Decimal(new), Decimal())
    return {"current_price": str(Decimal(old).quantize(cent)), "unused_credit": str(credit),
            "new_price": str(Decimal(new).quantize(cent)), "amount_due": str(due.quantize(cent)),
            "credit_left_over": str(left.quantize(cent))}

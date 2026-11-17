"""The GST-filing plan a business sees on the last page, and the one place that says it is free for now (R1-M9).

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

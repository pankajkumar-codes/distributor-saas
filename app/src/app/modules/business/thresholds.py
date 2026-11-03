"""Turnover rules other modules ask about: the minimum HSN digits and whether
e-invoicing applies (LLD-1 §8.3 and erratum S-3, for LLD-4 §3.4).

Both read the business's turnover bands and the cited refdata on `on`. A band records
only whether turnover was up to or above business.turnover_band_threshold (the QRMP
limit the sign-up question names), so it answers a rule at another threshold only when
the band settles it: "up to" a band limit at or below the rule's threshold is under it;
"above" a band limit at or above the rule's threshold is over it. Anything else gets the
stricter answer: 6 HSN digits, or 'unsure' for e-invoicing. Every number is refdata; refdata missing on `on` raises RefdataMissing.
"""

from datetime import date
from decimal import Decimal
from typing import Literal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.refdata import value_on

from .fiscal import fy_of, previous_fy
from .frequency import BOUND
from .profile import get_profile, turnover_band

EinvoiceStatus = Literal["applies", "unsure", "no"]


def min_digits_for(band: str | None, band_threshold: Decimal, rule_threshold: Decimal, low: int, high: int) -> int:
    """The preceding FY's band against the HSN rule (refdata-rates-uqc.md §5(b)). No band,
    or a band that doesn't settle it, gives the stricter count (LLD-1 §8.3)."""
    return low if band == "up_to_threshold" and band_threshold <= rule_threshold else high


def hsn_min_digits(tx: Session, on: date) -> int:
    """Minimum HSN digits on an invoice dated `on`, from the band of the FY before `on`'s
    FY (the rule is on the preceding FY's turnover)."""
    band = turnover_band(tx, previous_fy(fy_of(on)))
    return min_digits_for(
        None if band is None else band.band,
        value_on(tx, "business.turnover_band_threshold", on),
        value_on(tx, "hsn.min_digits_aato_threshold", on),
        value_on(tx, "hsn.min_digits_up_to_threshold", on),
        value_on(tx, "hsn.min_digits_above_threshold", on),
    )


def hsn_band_missing(tx: Session, on: date) -> str | None:
    """The FY whose band hsn_min_digits needs for `on` when the business hasn't set it
    (then the stricter count applies), else None. Lets the invoice say which band to set."""
    fy = previous_fy(fy_of(on))
    return fy if turnover_band(tx, fy) is None else None


def einvoice_status_for(
    history: str | None, bands_above: bool, band_threshold: Decimal, rule_threshold: Decimal
) -> EinvoiceStatus:
    """LLD-1 erratum S-3 with refdata-lld4.md §2's rule. `bands_above`: some FY from
    einvoice.aato_first_fy up to the FY before `on`'s has the band above_threshold."""
    if history == "yes" or (bands_above and band_threshold >= rule_threshold):
        return "applies"
    if bands_above:  # above a band limit below the rule's threshold: can't tell (Lead, #85)
        return "unsure"
    if history in (None, "not_sure"):
        return "unsure"
    return "no"


_ABOVE = text(
    f"select exists (select 1 from business.turnover_bands where {BOUND}"
    " and band = 'above_threshold' and fy >= :first and fy <= :last)"
)


def einvoice_status(tx: Session, on: date) -> EinvoiceStatus:
    """Whether e-invoicing applies to the bound business on `on` (LLD-4 L4-4 blocks B2B
    finalize on 'applies' and warns on 'unsure')."""
    profile = get_profile(tx)
    first = value_on(tx, "einvoice.aato_first_fy", on)
    above = tx.execute(_ABOVE, {"first": first, "last": previous_fy(fy_of(on))}).scalar_one()
    return einvoice_status_for(
        None if profile is None else profile.einvoice_history,
        above,
        value_on(tx, "business.turnover_band_threshold", on),
        value_on(tx, "einvoice.aato_threshold", on),
    )

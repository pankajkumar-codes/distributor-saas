"""load_inputs: everything compute needs, read through other modules' interfaces in the
caller's unit of work (LLD-4 §3; interface agreed with the Lead in
team/docs/s4c-compute-interface.md). S4-b calls compute(load_inputs(...)) on every draft
save and inside finalize.

Reads, all under row-level security for the bound business: catalog products (rate on
doc_date) and the customer snapshot, the business profile, readiness, HSN digits and
e-invoicing status, and refdata in force on doc_date.
"""

from datetime import date

from sqlalchemy.orm import Session

from app.modules.business.interface import (
    einvoice_status,
    get_profile,
    hsn_band_missing,
    hsn_min_digits,
    ready_for_documents,
)
from app.modules.catalog.interface import customer_snapshot, products_for_lines
from app.modules.refdata import RefdataMissing, value_on
from platform_common.errors import Invalid

from .model import Buyer, ComputeInput, DraftIn, DraftLineIn, LineIn, Rules, Seller


def load_inputs(tx: Session, draft: DraftIn, lines: list[DraftLineIn], *, today: date) -> ComputeInput:
    """Raises Deny("not_found") for a customer that is unknown, another business's or
    deleted (catalog.customer_snapshot); Invalid for a business without a profile or a
    document date the app has no tax rules for."""
    on = draft.doc_date
    profile = get_profile(tx)
    if profile is None:
        raise Invalid("business_profile_missing", "Add your business details first.", field="business")
    try:
        rules = _rules(tx, on)
        seller = Seller(
            state_code=profile.state_code,
            hsn_min_digits=hsn_min_digits(tx, on),
            einvoice_status=einvoice_status(tx, on),
            ready_missing=tuple(ready_for_documents(tx).missing),
            hsn_band_missing_fy=hsn_band_missing(tx, on),
        )
    except RefdataMissing:
        raise Invalid(
            "doc_date_not_supported", "The app has no GST rules for this invoice date.", field="doc_date"
        ) from None
    products = products_for_lines(tx, [ln.product_id for ln in lines if ln.product_id], on)
    return ComputeInput(
        doc_date=on,
        today=today,
        seller=seller,
        buyer=_buyer(tx, draft),
        lines=tuple(
            LineIn(
                ln.line_no,
                products.get(ln.product_id) if ln.product_id else None,
                ln.quantity,
                ln.unit_price,
                ln.discount_kind,
                ln.discount_value,
            )
            for ln in lines
        ),
        rules=rules,
        invoice_discount=draft.invoice_discount,
        charges=draft.charges,
        pos_override=draft.pos_override,
        pos_override_reason=draft.pos_override_reason,
        has_eway_details=draft.has_eway_details,
    )


def _rules(tx: Session, on: date) -> Rules:
    return Rules(
        rounding_mode=value_on(tx, "invoice.rounding_mode", on),
        round_off_line=value_on(tx, "invoice.round_off_line", on),
        utgst_state_codes=frozenset(c.strip() for c in value_on(tx, "gst.utgst_state_codes", on).split(",")),
        b2cl_threshold=value_on(tx, "gstr1.b2cl_threshold", on),
        unregistered_address_threshold=value_on(tx, "invoice.unregistered_address_threshold", on),
        eway_threshold=value_on(tx, "eway.consignment_value_threshold", on),
    )


def _state(address: dict | None) -> str | None:
    return ((address or {}).get("state_code") or "").strip() or None


def _has_line(address) -> bool:
    """A delivery address with a street line, not just a state (Rule 46(e), G9)."""
    if isinstance(address, str):
        return bool(address.strip())
    return bool(((address or {}).get("line1") or "").strip())


def _buyer(tx: Session, draft: DraftIn) -> Buyer:
    if draft.customer_id is None:  # cash sale (BH-11)
        cash = draft.cash_buyer or {}
        return Buyer(
            gstin=None,
            gstin_state_code=None,
            name=cash.get("name"),
            bill_to_state=_state(draft.bill_to) or _state(cash),
            ship_to_state=_state(draft.ship_to),
            has_delivery_address=_has_line(draft.ship_to) or _has_line(cash.get("address")),
            customer_collects=draft.customer_collects,
        )
    snap = customer_snapshot(tx, draft.customer_id)
    billing = {"state_code": snap.billing.state_code, "line1": snap.billing.line1}
    delivery = {"state_code": snap.delivery.state_code, "line1": snap.delivery.line1}
    # The draft's own addresses win; without one, the customer's (case A takes the
    # delivery address's state, Staff on #80).
    return Buyer(
        gstin=snap.gstin,
        gstin_state_code=snap.gstin_state_code,
        name=snap.name,
        bill_to_state=_state(draft.bill_to) or _state(billing),
        ship_to_state=_state(draft.ship_to) or _state(delivery),
        has_delivery_address=_has_line(draft.ship_to) if draft.ship_to else _has_line(delivery),
        ship_to_third_party=draft.ship_to_third_party,
        customer_collects=draft.customer_collects,
    )

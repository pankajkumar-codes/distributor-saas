"""Cancelling an issued invoice (#456 part 2; GST CA expert answer v1, ca-cancel-credit-note-answer-v1.md).

The law has no procedure to cancel a tax invoice; the portal lets a seller delete an invoice until the GSTR-1 (or IFF)
holding it is filed, and Table 13 counts cancelled numbers. So:
- an invoice can be cancelled only while the return it was assigned to is open (a practice invoice has none);
- never once a credit note exists for it (the note treats the sale as made), and never twice;
- the reason is one of three. "Raised by mistake" and "the sale did not happen" need the seller to declare that the
  goods were not removed or delivered (s.31(1): removal makes the supply); a duplicate needs none;
- the invoice row never changes (insert-only). A cancellation row is written beside it, the number stays used
  (rule 46(b)), the invoice leaves Tables 4 to 12 and Table 13 counts it as cancelled, and the stock it took out
  comes back as reversals of its own movements.

Cancel and credit notes take the same per-invoice advisory lock, so a note and a cancel made at once can't both pass.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import text

from app.modules.catalog.interface import reverse_invoice_stock
from app.modules.filing.interface import PeriodLocked, assert_period_open
from app.modules.refdata import value_on
from platform_common import audit
from platform_common.errors import Conflict, Deny, Invalid
from platform_common.ids import uuid7
from platform_common.uow import UnitOfWork

from . import finalize

REASONS = {
    "raised_in_error": "Raised by mistake",
    "duplicate": "Duplicate of another invoice",
    "did_not_happen": "The sale did not happen",
}


@dataclass(frozen=True)
class Cancellation:
    reason: str
    reason_label: str
    duplicate_of: str | None
    cancelled_at: datetime


def _business(uow: UnitOfWork) -> uuid.UUID:
    b = uow.principal.business_id
    assert b is not None
    return b


def cancellation(tx, business_id: uuid.UUID, document_id: uuid.UUID) -> Cancellation | None:
    r = tx.execute(
        text("select reason, duplicate_of, cancelled_at from sales.document_cancellations"
             " where document_id = :d and business_id = :b"),
        {"d": document_id, "b": business_id},
    ).one_or_none()
    return None if r is None else Cancellation(r.reason, REASONS[r.reason], r.duplicate_of, r.cancelled_at)


def cancel(uow: UnitOfWork, document_id: uuid.UUID, body: dict, today: date) -> dict:
    """Cancels the invoice and returns it (as finalize.get_document does), or raises naming why it can't be."""
    tx, b = uow.tx, _business(uow)
    doc = finalize.get_document(uow, document_id)  # a 404 before the lock, for another business's id
    if doc["kind"] != "invoice":
        raise Deny("not_found")
    reason = body.get("reason")
    if reason not in REASONS:
        raise Invalid("reason_invalid", "Choose why you are cancelling this invoice", field="reason")
    declared = body.get("declared_not_delivered") is True
    if reason != "duplicate" and not declared:
        raise Invalid("declaration_required", "Confirm the goods on this invoice were not removed or delivered."
                      " If they were, the sale happened: make a credit note instead.", field="declared_not_delivered")
    duplicate_of = (body.get("duplicate_of") or "").strip() or None
    longest = value_on(tx, "invoice.number.max_length", today)
    if duplicate_of is not None and (reason != "duplicate" or len(duplicate_of) > longest):
        raise Invalid("duplicate_of_invalid", f"Give the other invoice's number (up to {longest} characters) only for"
                      " a duplicate", field="duplicate_of")
    tx.execute(text("select pg_advisory_xact_lock(hashtextextended('cn:' || :d, 0))"), {"d": str(document_id)})
    if cancellation(tx, b, document_id) is not None:
        raise Conflict("already_cancelled", "This invoice is already cancelled")
    notes = tx.execute(
        text("select doc_number from sales.documents where business_id = :b and original_document_id = :d"
             " order by doc_number limit 1"),
        {"b": b, "d": document_id},
    ).scalar_one_or_none()
    if notes is not None:
        raise Conflict("has_credit_note", f"Credit note {notes} already exists for this invoice, so it can't be"
                       " cancelled", fix="Make a credit note for what is left instead")
    row = tx.execute(
        text("select doc_number, is_practice, return_instance_id from sales.documents where id = :d and business_id = :b"),
        {"d": document_id, "b": b},
    ).one()
    if not row.is_practice and row.return_instance_id is not None:
        try:
            assert_period_open(tx, row.return_instance_id)  # FOR SHARE: a mark-filed waits for this cancel, or wins
        except PeriodLocked:
            raise Conflict("return_filed", "The return that holds this invoice is already filed, so it can't be"
                           " cancelled", fix="Make a credit note instead") from None
    tx.execute(
        text("insert into sales.document_cancellations (id, business_id, document_id, reason, declared_not_delivered,"
             " duplicate_of, cancelled_by) values (:id, :b, :d, :r, :decl, :dup, :me)"),
        {"id": uuid7(), "b": b, "d": document_id, "r": reason, "decl": declared, "dup": duplicate_of,
         "me": uow.principal.user_id},
    )
    reversed_ = reverse_invoice_stock(uow, document_id=document_id, reason=f"Invoice {row.doc_number} cancelled",
                                      today=today)
    audit.record(uow, "invoice.cancelled", "document", document_id, reason=REASONS[reason],
                 data={"number": row.doc_number, "practice": row.is_practice, "reason": reason,
                       "duplicate_of": duplicate_of, "stock_reversals": len(reversed_)})
    return finalize.get_document(uow, document_id)

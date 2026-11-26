"""Credit notes (#456; CGST s.34, Rule 53(1A); LLD-4 §5), made from an issued invoice in one request.

The invoice is never changed. A note credits part or all of what is left on each of its lines:

- by quantity, for goods returned: the credited taxable value is the line's taxable value for that share of its
  quantity, and the goods come back to stock or are recorded as returned and written off (rule 56(2));
- by amount, for a value or tax charged too high, or goods deficient: no stock moves.

Each tax component is credited in proportion to the taxable value. The note that credits the last of a line takes
exactly what is left of its taxable value and of each tax, so the notes on a line can never add up to more than the
line, and rounding never leaves a paisa behind. The remaining amounts are read and the note written under a
transaction-scoped advisory lock on the invoice, so two notes made at once can't both credit the same remainder.

A practice invoice gets a practice note (PR-CN-0001, Pankaj's choice on #456), never in GST filing. A live note follows the
live numbering (CN/YY-MM/NNNNNN, D-114) and is assigned to the return covering its date, or rolled forward when that
is filed (the filing interface target_return_instance, refdata credit_note_locked_treatment). The law's last date (s.34(2)) is checked on the note date.

A finalized document needs a draft (its draft_id is required): the note writes one as its input record and marks it
finalized in the same unit of work, exactly as finalize does.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import bindparam, text
from sqlalchemy.types import JSON

from app.modules.business.interface import SeriesSetting, default_series_setting, fy_of, series_setting
from app.modules.catalog.interface import record_credit_note_return
from app.modules.filing.interface import DocumentRef, target_return_instance
from app.modules.refdata import value_on
from platform_common import audit
from platform_common.errors import Deny, Invalid
from platform_common.ids import uuid7
from platform_common.money import round_to_paise
from platform_common.uow import UnitOfWork

from . import finalize
from .drafts import MAX_LINES
from .compute import words

# The s.34(1) grounds (GST CA expert, 2026-11-26). Discount (s.15(3)(b), Finance Act 2026) is not in force: not offered.
REASONS = {
    "goods_returned": "Goods returned",
    "value_too_high": "Taxable value or tax charged too high",
    "deficient": "Goods or services deficient",
}
STOCK_TREATMENTS = ("restock", "write_off")
_QTY = re.compile(r"^[0-9]{1,15}(\.[0-9]{1,3})?$")
_MONEY = re.compile(r"^[0-9]{1,16}(\.[0-9]{1,2})?$")
_ZERO = Decimal()
METHOD = "credit-note-1"


@dataclass(frozen=True)
class LineState:
    line_id: uuid.UUID
    line_no: int
    product_id: uuid.UUID | None
    code: str | None
    name: str
    hsn: str
    uqc: str
    rate: Decimal
    rate_confirmed: bool
    quantity: Decimal | None
    taxable: Decimal
    taxes: dict[str, Decimal]  # component -> amount on the invoice line
    tax_rates: dict[str, Decimal]  # component -> its rate on the invoice line
    credited_quantity: Decimal
    credited_taxable: Decimal
    credited_taxes: dict[str, Decimal]

    @property
    def remaining_quantity(self) -> Decimal | None:
        return None if self.quantity is None else self.quantity - self.credited_quantity

    @property
    def remaining_taxable(self) -> Decimal:
        return self.taxable - self.credited_taxable

    def remaining_tax(self, component: str) -> Decimal:
        return self.taxes[component] - self.credited_taxes.get(component, _ZERO)


@dataclass(frozen=True)
class CreditState:
    invoice: dict
    lines: tuple[LineState, ...]
    notes: tuple[dict, ...]  # notes already made against the invoice, oldest first
    last_date: date  # s.34(2): the latest note date the law allows (the annual-return limb is not checked)

    @property
    def remaining_total(self) -> Decimal:
        return sum((ln.remaining_taxable + sum((ln.remaining_tax(c) for c in ln.taxes), _ZERO) for ln in self.lines),
                   _ZERO)


def _business(uow: UnitOfWork) -> uuid.UUID:
    return uow.principal.business_id


def last_date(uow: UnitOfWork, invoice_date: date) -> date:
    """s.34(2): 30 November after the end of the invoice's FY (refdata credit_note.deadline_month_day)."""
    month, day = (int(x) for x in str(value_on(uow.tx, "credit_note.deadline_month_day", invoice_date)).split("-"))
    fy_start, _ = fy_of(invoice_date).split("-")
    fy_end_year = int(fy_start) + 1
    return date(fy_end_year, month, day)


def credit_state(uow: UnitOfWork, invoice_id: uuid.UUID) -> CreditState:
    """What is left to credit on an issued invoice of this business; anything else is a 404."""
    doc = finalize.get_document(uow, invoice_id)
    if doc["kind"] != "invoice":
        raise Deny("not_found")
    b = _business(uow)
    lines = uow.tx.execute(
        text("select id, line_no, product_id, code, name, hsn, uqc, rate, rate_confirmed, quantity, taxable"
             " from sales.document_lines where document_id = :d and business_id = :b order by line_no"),
        {"d": invoice_id, "b": b},
    ).mappings().all()
    taxes: dict[uuid.UUID, dict[str, Decimal]] = {}
    rates: dict[uuid.UUID, dict[str, Decimal]] = {}
    for r in uow.tx.execute(
        text("select t.line_id, t.component, t.amount, t.rate from sales.document_line_taxes t"
             " join sales.document_lines l on l.id = t.line_id and l.business_id = t.business_id"
             " where l.document_id = :d and t.business_id = :b"),
        {"d": invoice_id, "b": b},
    ):
        taxes.setdefault(r.line_id, {})[r.component] = r.amount
        rates.setdefault(r.line_id, {})[r.component] = r.rate
    credited_q: dict[uuid.UUID, Decimal] = {}
    credited_t: dict[uuid.UUID, Decimal] = {}
    credited_tax: dict[uuid.UUID, dict[str, Decimal]] = {}
    for r in uow.tx.execute(
        text("select l.original_line_id, coalesce(sum(l.quantity), 0) as credited_qty, sum(l.taxable) as credited_taxable"
             " from sales.document_lines l join sales.documents n on n.id = l.document_id and n.business_id = l.business_id"
             " where n.business_id = :b and n.kind = 'credit_note' and n.original_document_id = :d"
             " group by l.original_line_id"),
        {"d": invoice_id, "b": b},
    ):
        credited_q[r.original_line_id], credited_t[r.original_line_id] = r.credited_qty, r.credited_taxable
    for r in uow.tx.execute(
        text("select l.original_line_id, t.component, sum(t.amount) as a from sales.document_line_taxes t"
             " join sales.document_lines l on l.id = t.line_id and l.business_id = t.business_id"
             " join sales.documents n on n.id = l.document_id and n.business_id = l.business_id"
             " where n.business_id = :b and n.kind = 'credit_note' and n.original_document_id = :d"
             " group by l.original_line_id, t.component"),
        {"d": invoice_id, "b": b},
    ):
        credited_tax.setdefault(r.original_line_id, {})[r.component] = r.a
    notes = uow.tx.execute(
        text("select id, doc_number, doc_date, reason_code, doc_total, is_practice from sales.documents"
             " where business_id = :b and kind = 'credit_note' and original_document_id = :d"
             " order by finalized_at, id"),
        {"d": invoice_id, "b": b},
    ).mappings().all()
    states = tuple(
        LineState(
            line_id=ln["id"], line_no=ln["line_no"], product_id=ln["product_id"], code=ln["code"], name=ln["name"],
            hsn=ln["hsn"], uqc=ln["uqc"], rate=ln["rate"], rate_confirmed=ln["rate_confirmed"],
            quantity=ln["quantity"], taxable=ln["taxable"], taxes=taxes.get(ln["id"], {}),
            tax_rates=rates.get(ln["id"], {}), credited_quantity=credited_q.get(ln["id"], _ZERO),
            credited_taxable=credited_t.get(ln["id"], _ZERO), credited_taxes=credited_tax.get(ln["id"], {}),
        )
        for ln in lines
    )
    return CreditState(doc, states, tuple(dict(n) for n in notes), last_date(uow, doc["doc_date"]))


def _quantity(raw, field: str) -> Decimal:
    if not isinstance(raw, str) or not _QTY.match(raw.strip()) or Decimal(raw.strip()) <= 0:
        raise Invalid("quantity_invalid", "Enter a quantity above 0 with up to 3 decimals", field=field)
    return Decimal(raw.strip())


def _amount(raw, field: str) -> Decimal:
    if not isinstance(raw, str) or not _MONEY.match(raw.strip()) or Decimal(raw.strip()) <= 0:
        raise Invalid("amount_invalid", "Enter an amount above 0 with up to 2 decimals, like 120.50", field=field)
    return Decimal(raw.strip())


@dataclass(frozen=True)
class NoteLine:
    original: LineState
    quantity: Decimal | None
    taxable: Decimal
    taxes: dict[str, Decimal]


def plan(state: CreditState, body: dict, rounding: str) -> list[NoteLine]:
    """The note's lines from the request, or Invalid naming the first field at fault. Pure: reads only `state`."""
    reason = body.get("reason")
    by_quantity = reason == "goods_returned"
    sent = body.get("lines") or []
    if not sent:
        raise Invalid("lines_required", "Choose at least one line to credit", field="lines")
    if len(sent) > MAX_LINES:
        raise Invalid("too_many_lines", f"A credit note can have at most {MAX_LINES} lines", field="lines")
    by_id = {str(ln.line_id): ln for ln in state.lines}
    seen: set[str] = set()
    out = []
    for i, ln in enumerate(sent):
        field = f"lines.{i}"
        key = str(ln.get("original_line_id") or "")
        orig = by_id.get(key)
        if orig is None:
            raise Invalid("line_not_on_invoice", "Choose a line of this invoice", field=f"{field}.original_line_id")
        if key in seen:
            raise Invalid("line_repeated", "Each invoice line can appear once in a note", field=f"{field}.original_line_id")
        seen.add(key)
        if orig.remaining_taxable <= 0:
            raise Invalid("line_fully_credited", "This line has been credited in full already", field=field)
        if by_quantity:
            if ln.get("taxable") is not None:
                raise Invalid("quantity_or_amount", "Goods returned are credited by quantity", field=f"{field}.taxable")
            if orig.quantity is None or orig.quantity <= 0:
                raise Invalid("no_quantity", "This line has no quantity; credit it by amount", field=f"{field}.quantity")
            q = _quantity(ln.get("quantity"), f"{field}.quantity")
            if q > orig.remaining_quantity:
                raise Invalid("credit_quantity_too_high", f"At most {orig.remaining_quantity.normalize():f} can be"
                              " credited on this line", field=f"{field}.quantity")
            closing = q == orig.remaining_quantity
            taxable = orig.remaining_taxable if closing else min(
                orig.remaining_taxable, round_to_paise(orig.taxable * q / orig.quantity, rounding=rounding))
        else:
            if ln.get("quantity") is not None:
                raise Invalid("quantity_or_amount", "A price or deficiency credit is an amount, not a quantity",
                              field=f"{field}.quantity")
            q = None
            taxable = _amount(ln.get("taxable"), f"{field}.taxable")
            if taxable > orig.remaining_taxable:
                raise Invalid("credit_value_too_high", f"At most {orig.remaining_taxable:f} can be credited on this"
                              " line", field=f"{field}.taxable")
            closing = taxable == orig.remaining_taxable
        taxes = {
            c: orig.remaining_tax(c) if closing else min(
                orig.remaining_tax(c), round_to_paise(amount * taxable / orig.taxable, rounding=rounding))
            for c, amount in orig.taxes.items()
        }
        out.append(NoteLine(orig, q, taxable, taxes))
    return out


def _supply_class(invoice: dict) -> str:
    """CDNR to a registered buyer; CDNUR for a large inter-state sale to a consumer (B2CL); otherwise the note is netted
    in B2CS (LLD-4 §5)."""
    if invoice["counterparty_gstin"]:
        return "CDNR"
    return "CDNUR" if invoice["supply_class"] == "B2CL" else "B2CS"


def create(uow: UnitOfWork, invoice_id: uuid.UUID, body: dict, today: date) -> dict:
    """Issues a credit note against `invoice_id` and returns it (as finalize.get_document does)."""
    tx, b = uow.tx, _business(uow)
    finalize.get_document(uow, invoice_id)  # a 404 before taking the lock, for another business's id
    tx.execute(text("select pg_advisory_xact_lock(hashtextextended('cn:' || :d, 0))"), {"d": str(invoice_id)})
    state = credit_state(uow, invoice_id)
    inv = tx.execute(
        text("select id, doc_number, doc_date, is_practice, gstin, customer_id, counterparty_gstin, counterparty_name,"
             " pos_state_code, is_inter_state, supply_class, utgst, rounding_mode, print, supplier_state_code"
             " from sales.documents where id = :d and business_id = :b"),
        {"d": invoice_id, "b": b},
    ).mappings().one()
    reason = body.get("reason")
    if reason not in REASONS:
        raise Invalid("reason_invalid", "Choose why you are making this credit note", field="reason")
    stock = body.get("stock_treatment")
    if reason == "goods_returned":
        if stock not in STOCK_TREATMENTS:
            raise Invalid("stock_treatment_required", "Say whether the returned goods go back to stock or are written"
                          " off", field="stock_treatment")
    elif stock is not None:
        raise Invalid("stock_treatment_not_allowed", "Only returned goods move stock", field="stock_treatment")
    note_date = body.get("doc_date") or today
    if isinstance(note_date, str):
        try:
            note_date = date.fromisoformat(note_date)
        except ValueError:
            raise Invalid("date_invalid", "Enter the note date as YYYY-MM-DD", field="doc_date") from None
    if note_date > today:
        raise Invalid("date_in_future", "A credit note can't be dated after today", field="doc_date")
    if note_date < inv["doc_date"]:
        raise Invalid("date_before_invoice", "A credit note can't be dated before its invoice", field="doc_date")
    if note_date > state.last_date:
        raise Invalid("credit_note_too_late", f"The last date for a credit note on this invoice was"
                      f" {state.last_date:%d-%m-%Y} (30 November after the financial year ends)", field="doc_date")
    lines = plan(state, body, inv["rounding_mode"])
    practice = inv["is_practice"]
    supply_class = _supply_class(inv)
    assigned = None
    setting: SeriesSetting | None = None
    if not practice:
        if not finalize.live_enabled(uow, today):
            raise Invalid("live_numbering_unavailable", "Live credit notes aren't available yet.", field="numbering")
        setting = series_setting(tx, "credit_note") or default_series_setting("credit_note")
        assigned = target_return_instance(
            tx, inv["gstin"], "credit_note", note_date, supply_class,
            DocumentRef(inv["id"], inv["doc_number"], inv["doc_date"]), today=today)
    fy = fy_of(note_date)
    series_id, number = finalize.allocate(uow, gstin=inv["gstin"], kind="credit_note", fy=fy, practice=practice,
                                          setting=setting, on=note_date)
    taxable_total = sum((ln.taxable for ln in lines), _ZERO)

    def tax(component: str) -> Decimal:
        return sum((ln.taxes.get(component, _ZERO) for ln in lines), _ZERO)

    cgst, sgst, igst = tax("CGST"), tax("SGST") + tax("UTGST"), tax("IGST")
    total = taxable_total + cgst + sgst + igst
    print_ = {**(inv["print"] or {}), "original": {"number": inv["doc_number"], "date": inv["doc_date"].isoformat()},
              "reason": REASONS[reason], "stock_treatment": stock}
    bill_to = print_.get("bill_to")
    draft_id, document_id, me = uuid7(), uuid7(), uow.principal.user_id
    tx.execute(
        text("insert into sales.drafts (id, business_id, kind, customer_id, bill_to, ship_to, doc_date,"
             " original_document_id, reason_code, stock_treatment, created_by, updated_by) values (:id, :b,"
             " 'credit_note', :customer, :bill_to, :ship_to, :doc_date, :orig, :reason, :stock, :me, :me)"
             ).bindparams(bindparam("bill_to", type_=JSON(none_as_null=True)),
                          bindparam("ship_to", type_=JSON(none_as_null=True))),
        {"id": draft_id, "b": b, "customer": inv["customer_id"], "bill_to": bill_to, "ship_to": print_.get("ship_to"),
         "doc_date": note_date, "orig": invoice_id, "reason": reason, "stock": stock, "me": me},
    )
    for n, ln in enumerate(lines, start=1):
        tx.execute(
            text("insert into sales.draft_lines (id, business_id, draft_id, line_no, original_line_id, quantity,"
                 " credit_taxable) values (:id, :b, :d, :n, :orig, :q, :t)"),
            {"id": uuid7(), "b": b, "d": draft_id, "n": n, "orig": ln.original.line_id, "q": ln.quantity,
             "t": None if ln.quantity is not None else ln.taxable},
        )
    tx.execute(
        text(
            "insert into sales.documents (id, business_id, draft_id, kind, is_practice, series_id, doc_number, doc_date,"
            " fy, gstin, supplier_state_code, customer_id, counterparty_gstin, counterparty_name, pos_state_code,"
            " is_inter_state, supply_class, return_instance_id, return_period, credit_days, due_date,"
            " original_document_id, reason_code, stock_treatment, gross_total, line_discount_total, invoice_discount,"
            " charges_total, taxable_total, cgst_total, sgst_total, utgst, igst_total, round_off, doc_total,"
            " amount_in_words, print, rounding_mode, method_version, finalized_by) values (:id, :b, :draft,"
            " 'credit_note', :practice, :series, :number, :doc_date, :fy, :gstin, :supplier_state, :customer, :cp_gstin,"
            " :cp_name, :pos, :inter, :class, :instance, :period, 0, null, :orig, :reason, :stock, :taxable, 0, 0, 0,"
            " :taxable, :cgst, :sgst, :utgst, :igst, 0, :total, :words, :print, :rounding, :method, :me)"
        ).bindparams(bindparam("print", type_=JSON)),
        {"id": document_id, "b": b, "draft": draft_id, "practice": practice, "series": series_id, "number": number,
         "doc_date": note_date, "fy": fy, "gstin": inv["gstin"], "supplier_state": inv["supplier_state_code"],
         "customer": inv["customer_id"], "cp_gstin": inv["counterparty_gstin"], "cp_name": inv["counterparty_name"],
         "pos": inv["pos_state_code"], "inter": inv["is_inter_state"], "class": supply_class,
         "instance": None if assigned is None else assigned.id,
         "period": None if assigned is None else assigned.period, "orig": invoice_id, "reason": reason, "stock": stock,
         "taxable": taxable_total, "cgst": cgst, "sgst": sgst, "utgst": inv["utgst"], "igst": igst, "total": total,
         "words": words.inr(total), "print": print_, "rounding": inv["rounding_mode"], "method": METHOD, "me": me},
    )
    for n, ln in enumerate(lines, start=1):
        line_id = uuid7()
        o = ln.original
        tx.execute(
            text("insert into sales.document_lines (id, business_id, document_id, line_no, product_id, original_line_id,"
                 " code, name, hsn, uqc, quantity, unit_price, gross, line_discount, discount_share, charge_share,"
                 " taxable, rate, rate_confirmed) values (:id, :b, :doc, :n, :product, :orig, :code, :name, :hsn, :uqc,"
                 " :q, null, :taxable, 0, 0, 0, :taxable, :rate, :confirmed)"),
            {"id": line_id, "b": b, "doc": document_id, "n": n, "product": o.product_id, "orig": o.line_id,
             "code": o.code, "name": o.name, "hsn": o.hsn, "uqc": o.uqc, "q": ln.quantity, "taxable": ln.taxable,
             "rate": o.rate, "confirmed": o.rate_confirmed},
        )
        for component, amount in ln.taxes.items():
            tx.execute(
                text("insert into sales.document_line_taxes (line_id, business_id, component, rate, amount)"
                     " values (:line, :b, :component, :rate, :amount)"),
                {"line": line_id, "b": b, "component": component, "rate": o.tax_rates[component], "amount": amount},
            )
        if reason == "goods_returned" and o.product_id is not None:
            record_credit_note_return(uow, product_id=o.product_id, quantity=ln.quantity, note_id=document_id,
                                      note_line_id=line_id, on=note_date, practice=practice,
                                      write_off=stock == "write_off")
    tx.execute(text("update sales.drafts set status = 'finalized' where id = :d and business_id = :b"),
               {"d": draft_id, "b": b})
    audit.record(
        uow, "credit_note.issued", "document", document_id,
        data={"number": number, "practice": practice, "original_id": str(invoice_id),
              "original_number": inv["doc_number"], "reason": reason}
        | ({} if assigned is None else {"return_period": assigned.period, "form": assigned.form}),
    )
    return finalize.get_document(uow, document_id)

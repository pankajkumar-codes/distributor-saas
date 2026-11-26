"""Finalize, F1: a draft becomes an insert-only document with a number (LLD-4 §4, BH-5).

Off until refdata `sales.finalize.enabled` is true (D-044): the numbering scope
(D-010) waits for the CA, so the route is a 404 and no number is ever issued while the
switch is off. F1 issues practice documents only, which is every business's starting
state (series_settings.practice_mode defaults to true, and no settings row means
practice). A live finalize (return assignment, lock_gstin, the e-invoicing block) is F2;
until then a business set to live numbering is refused here, before any number is taken.

Everything happens in the caller's unit of work, so any failure rolls back the number
with the rest (TD-7, D-030: a counter row locked FOR UPDATE, never a sequence).
"""

import uuid
from datetime import date, timedelta

from sqlalchemy import bindparam, text
from sqlalchemy.types import JSON

from app.modules.business.interface import Profile, SeriesSetting, fy_of, get_profile, series_setting
from app.modules.filing.interface import FREE_INVOICES, invoicing_allowed, target_return_instance
from app.modules.catalog.interface import customer_snapshot, mark_used, record_sale_out
from app.modules.refdata import RefdataMissing, first_valid_from, value_on
from platform_common import audit
from platform_common.errors import AppError, Deny, Invalid
from platform_common.ids import uuid7
from platform_common.uow import UnitOfWork

from . import drafts
from .compute import Computation, Issue

# The numbering scopes refdata `sales.numbering_scope` may name (D-010). L4-2's first one: a series per GSTIN,
# document kind and FY. Pankaj's (#457, 2026-11-26): a series per GSTIN, kind and month of the invoice date.
SCOPE_GSTIN_KIND_FY = "gstin_kind_fy"
SCOPE_GSTIN_KIND_MONTH = "gstin_kind_month"  # #457: INV/YY-MM/NNNNNN, a series per month of the invoice date


def monthly_prefix(prefix: str, on: date) -> str:
    """INV and an invoice dated in November 2026 -> "INV/26-11/". The month is the invoice date's, never the finalize
    date's."""
    return f"{prefix}/{on.year % 100:02d}-{on.month:02d}/"


def monthly_number_fits(prefix: str, width: int, max_length: int) -> bool:
    """Whether every number of a monthly series fits Rule 46(b)'s limit (refdata invoice.number.max_length): prefix +
    "/YY-MM/" + width digits. For the numbering settings to check when they are saved (#457); allocate checks each
    number again."""
    return len(monthly_prefix(prefix, date.min)) + width <= max_length


_DOCUMENT_COLUMNS = (
    "id, draft_id, kind, is_practice, doc_number, doc_date, fy, gstin, supply_class, pos_state_code, original_document_id,"
    " reason_code,"
    " is_inter_state, customer_id, counterparty_name, due_date, taxable_total, cgst_total, sgst_total, utgst,"
    " igst_total, round_off, doc_total, finalized_at,"
    # #456: set when the invoice is cancelled (the document row itself never changes)
    " (select c.reason from sales.document_cancellations c where c.document_id = d.id"
    " and c.business_id = d.business_id) as cancel_reason"
)


class FinalizeBlocked(Invalid):
    """422 with every block (LLD-4 §3.4): nothing was written."""

    def __init__(self, blocks: tuple[Issue, ...]):
        super().__init__("finalize_blocked", "Fix these before finalizing.")
        self.blocks = blocks

    def body(self) -> dict:
        out = super().body()
        out["error"]["blocks"] = [
            {"code": i.code, "fix": i.fix, "field": i.field, "line_no": i.line_no} for i in self.blocks
        ]
        return out


class InvoicePlanRequired(AppError):
    """402: the business has used its free invoices and has no invoicing plan (R2-M7, D-086)."""

    status = 402
    code = "invoice_plan_required"


def invoices_used(uow: UnitOfWork) -> int:
    """Finalized invoices of this business, practice or not (D-086), counted on the server."""
    return uow.tx.execute(
        text("select count(*) from sales.documents where business_id = :b and kind = 'invoice'"),
        {"b": _business(uow)},
    ).scalar_one()


def check_plan(uow: UnitOfWork) -> None:
    """The free invoices are the first FREE_INVOICES; the next needs the invoicing plan. While payments are a placeholder
    (FREE_FOR_NOW) the plan is free and nothing is refused. Called inside the series lock, so two finalizes in one series
    cannot both take the last free one."""
    if invoices_used(uow) >= FREE_INVOICES and not invoicing_allowed(uow.tx, _business(uow)):
        raise InvoicePlanRequired(
            message=f"Your first {FREE_INVOICES} invoices are free. Choose an invoicing plan to issue more.",
            fix="Choose an invoicing plan",
        )


def enabled(uow: UnitOfWork, today: date) -> bool:
    """The switch. No row on `today` counts as off."""
    try:
        return value_on(uow.tx, "sales.finalize.enabled", today) is True
    except RefdataMissing:
        return False


def live_enabled(uow: UnitOfWork, today: date) -> bool:
    """The second switch, for live numbers and return assignment. No row counts as off."""
    try:
        return value_on(uow.tx, "sales.finalize.live", today) is True
    except RefdataMissing:
        return False


def _business(uow: UnitOfWork) -> uuid.UUID:
    return uow.principal.business_id


def document_for_draft(uow: UnitOfWork, draft_id: uuid.UUID) -> dict | None:
    row = (
        uow.tx.execute(
            text(f"select {_DOCUMENT_COLUMNS} from sales.documents d where draft_id = :d and business_id = :b"),
            {"d": draft_id, "b": _business(uow)},
        )
        .mappings()
        .one_or_none()
    )
    return None if row is None else dict(row)


def get_document(uow: UnitOfWork, document_id: uuid.UUID) -> dict:
    """One finalized document of this business; another business's, or an unknown one, is a 404."""
    row = (
        uow.tx.execute(
            text(f"select {_DOCUMENT_COLUMNS} from sales.documents d where id = :i and business_id = :b"),
            {"i": document_id, "b": _business(uow)},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise Deny("not_found")
    return dict(row)


def list_documents(uow: UnitOfWork, limit: int, offset: int, q: str | None = None) -> tuple[list[dict], bool]:
    """This business's finalized documents, newest first. `q` matches part of the number or the
    buyer's name, or the start of the buyer's GSTIN; the business filter is always applied."""
    where = ["business_id = :b"]
    params: dict = {"b": _business(uow), "n": limit + 1, "o": offset}
    if q and q.strip():
        needle = q.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where.append("(doc_number ilike :frag or counterparty_name ilike :frag or counterparty_gstin like :prefix)")
        params.update(frag=f"%{needle}%", prefix=f"{needle.upper().replace(' ', '')}%")
    rows = (
        uow.tx.execute(
            text(f"select {_DOCUMENT_COLUMNS} from sales.documents d where {' and '.join(where)}"
                 " order by finalized_at desc, id desc limit :n offset :o"),
            params,
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows[:limit]], len(rows) > limit


def finalize(uow: UnitOfWork, draft_id: uuid.UUID, if_match: int | None, today: date) -> dict:
    """The draft's document. A draft finalized already (a retry, a second tab) gives the
    same document back, whatever the key (BH-5, AC4-3)."""
    done = document_for_draft(uow, draft_id)
    if done is not None:
        return done
    try:
        # get() filters status = 'open': a request that waited on this lock while another
        # finalized the draft re-checks the row, finds it finalized and falls through to
        # returning that document. Without the filter the race is a unique-violation 500.
        d = drafts.get(uow, draft_id, lock=True)
    except Deny:
        # Another request finalized it while this one waited for the row lock.
        done = document_for_draft(uow, draft_id)
        if done is not None:
            return done
        raise
    drafts.check_version(d, if_match)
    if d["kind"] != "invoice":
        raise Invalid("kind_unsupported", "Only invoices can be finalized for now", field="kind")
    c = drafts.computation(uow, d, today=today)
    if c.blocks:
        raise FinalizeBlocked(c.blocks)
    setting = series_setting(uow.tx, d["kind"])
    practice = setting is None or setting.practice_mode
    if not practice and not live_enabled(uow, today):
        raise Invalid(
            "live_numbering_unavailable",
            "Live invoice numbers aren't available yet; this business can issue practice invoices only.",
            field="numbering",
        )
    if not practice and c.supply_class == "B2B" and any(w.code == "einvoice_unsure" for w in c.warnings):
        # Rule 48(5): an invoice that had to carry an IRN and doesn't is not an invoice. A practice document may go
        # ahead with the warning; a live one waits until the business answers (#455).
        raise Invalid(
            "einvoice_unsure_live",
            "Tell us whether e-invoicing applies to your business before you issue a live invoice to a GST-registered"
            " buyer. An invoice that needed an e-invoice number and doesn't have one doesn't count as an invoice.",
            field="business",
        )
    profile = get_profile(uow.tx)
    if profile is None or not profile.gstin:  # ready_for_documents blocks this first; kept as a guard
        raise Invalid("business_profile_missing", "Add your business details first.", field="business")
    doc_date = d["doc_date"] or today
    fy = fy_of(doc_date)
    assigned = None  # a practice document is in no return; a live one is assigned once, here (LLD-5 §4)
    if not practice:
        assigned = target_return_instance(
            uow.tx, profile.gstin, "invoice", doc_date, c.supply_class, taxable_value=c.taxable_total, today=today
        )
    series_id, number = allocate(
        uow, gstin=profile.gstin, kind=d["kind"], fy=fy, practice=practice, setting=setting, on=doc_date
    )
    check_plan(uow)
    mark_used(uow.tx, [ln.product.product_id for ln in c.lines], d["customer_id"])
    document_id = _insert(
        uow, d, c, profile, series_id=series_id, number=number, doc_date=doc_date, fy=fy, practice=practice,
        assigned=assigned,
    )
    uow.tx.execute(
        text("update sales.drafts set status = 'finalized' where id = :d and business_id = :b"),
        {"d": draft_id, "b": _business(uow)},
    )
    audit.record(
        uow,
        "document.finalized",
        "document",
        document_id,
        data={"number": number, "kind": d["kind"], "practice": practice, "draft_id": str(draft_id)}
        | ({} if assigned is None else {"return_period": assigned.period, "form": assigned.form}),
    )
    if d["pos_override"] is not None:
        audit.record(
            uow,
            "document.pos_override",
            "document",
            document_id,
            reason=d["pos_override_reason"],
            data={"computed_pos": c.computed_pos, "chosen_pos": c.pos_state_code},
        )
    return document_for_draft(uow, draft_id)


_LABELS = {"invoice": "an invoice", "credit_note": "a credit note", "debit_note": "a debit note"}


def _refuse_before_settings(tx, *, kind: str, practice: bool, on: date) -> None:
    """A document dated before the numbering settings it needs begin is refused with a plain 422, not a 500 (#494).
    The settings are read on the document's date (below); a date before their first row has no value, and backfilling
    those rows is a separate decision (CEO, 2026-11-27)."""
    if practice:
        keys = ("sales.practice_prefix" if kind == "invoice" else f"sales.practice_{kind}_prefix", "sales.practice_width")
    else:
        keys = ("sales.numbering_scope",)
    starts = [d for d in (first_valid_from(tx, k) for k in keys) if d is not None]
    if starts and on < max(starts):
        first = max(starts)
        raise Invalid(
            "doc_date_too_early",
            f"Kartaa can't issue {_LABELS.get(kind, 'a document')} dated before {first.strftime('%d-%b-%Y')} yet."
            f" Change the date to {first.strftime('%d-%b-%Y')} or later.",
            field="doc_date",
        )


def allocate(
    uow: UnitOfWork, *, gstin: str, kind: str, fy: str, practice: bool, setting: SeriesSetting | None, on: date
) -> tuple[uuid.UUID, str]:
    """The next number in the series the configured scope picks (D-030). The series row is created on first use with
    the prefix in force then (L4-2), then locked FOR UPDATE and advanced by one. A rollback leaves next_value where it
    was. Practice numbers are always one series per FY (PR-0001). Live numbers follow `sales.numbering_scope`:
    gstin_kind_fy, one series per FY; or gstin_kind_month (#457, Pankaj's decision, D-114), one series per month of the
    invoice date, numbered <prefix>/YY-MM/NNNNNN (INV/26-11/000001) and restarting at 1 each month."""
    tx = uow.tx
    month = ""
    _refuse_before_settings(tx, kind=kind, practice=practice, on=on)
    if practice:
        # Each kind has its own practice series (PR-0001, PR-CN-0001): a credit note never takes an invoice's number.
        series_kind = "practice" if kind == "invoice" else f"practice_{kind}"
        prefix = value_on(tx, "sales.practice_prefix" if kind == "invoice" else f"sales.practice_{kind}_prefix", on)
        width = value_on(tx, "sales.practice_width", on)
        first = 1
    else:
        assert setting is not None
        scope = value_on(tx, "sales.numbering_scope", on)
        if scope not in (SCOPE_GSTIN_KIND_FY, SCOPE_GSTIN_KIND_MONTH):
            raise RuntimeError(f"numbering scope {scope!r} is not built")
        series_kind, prefix, width, first = kind, setting.prefix, setting.width, setting.first_value
        if scope == SCOPE_GSTIN_KIND_MONTH:
            month = f"{on.year:04d}-{on.month:02d}"
            prefix = monthly_prefix(setting.prefix, on)
            # first_value continues a series begun in other software: only the FY's first series of this kind uses it.
            earlier = tx.execute(
                text(
                    "select 1 from sales.number_series where business_id = :b and gstin = :g and kind = :k"
                    " and fy = :fy limit 1"
                ),
                {"b": _business(uow), "g": gstin, "k": kind, "fy": fy},
            ).first()
            first = 1 if earlier is not None else first
    key = {"b": _business(uow), "g": gstin, "k": series_kind, "fy": fy, "m": month}
    # Two kinds must never print the same number (Staff review of #463): a prefix renamed to one another kind already
    # started this FY (an invoice series renamed to CN while a CN/26-11/ credit series exists) is refused here, and
    # number_series_prefix_uq stops a race between two kinds.
    taken = tx.execute(
        text("select 1 from sales.number_series where business_id = :b and gstin = :g and fy = :fy and kind <> :k"
             " and lower(prefix) = lower(:prefix) limit 1"),
        {**key, "prefix": prefix},
    ).first()
    if taken is not None:
        raise Invalid(
            "prefix_in_use",
            "Another kind of document already uses this prefix this financial year.",
            field="numbering",
            fix="Choose a different prefix in your numbering settings",
        )
    tx.execute(
        text(
            "insert into sales.number_series (id, business_id, gstin, kind, fy, month, prefix, width, next_value)"
            " values (:id, :b, :g, :k, :fy, :m, :prefix, :width, :first)"
            " on conflict (business_id, gstin, kind, fy, month) do nothing"
        ),
        {**key, "id": uuid7(), "prefix": prefix, "width": width, "first": first},
    )
    series_id, prefix, width, value = tx.execute(
        text(
            "select id, prefix, width, next_value from sales.number_series"
            " where business_id = :b and gstin = :g and kind = :k and fy = :fy and month = :m for update"
        ),
        key,
    ).one()
    number = f"{prefix}{value:0{width}d}"
    if len(number) > value_on(tx, "invoice.number.max_length", on) or not value_on(
        tx, "invoice.number.charset", on
    ).fullmatch(number):
        raise Invalid(
            "number_too_long",
            "This invoice number would be too long or has characters GST doesn't allow.",
            field="numbering",
            fix="Shorten the prefix in your numbering settings",
        )
    tx.execute(text("update sales.number_series set next_value = next_value + 1 where id = :id"), {"id": series_id})
    return series_id, number


def _insert(
    uow: UnitOfWork,
    d: dict,
    c: Computation,
    profile: Profile,
    *,
    series_id: uuid.UUID,
    number: str,
    doc_date: date,
    fy: str,
    practice: bool,
    assigned=None,
) -> uuid.UUID:
    tx, b = uow.tx, _business(uow)
    document_id = uuid7()
    credit_days = customer_snapshot(tx, d["customer_id"]).credit_days if d["customer_id"] else 0
    bill_to = d["bill_to"] or {}
    tx.execute(
        text(
            "insert into sales.documents (id, business_id, draft_id, kind, is_practice, series_id, doc_number,"
            " doc_date, fy, gstin, supplier_state_code, customer_id, counterparty_gstin, counterparty_name,"
            " pos_state_code, is_inter_state, supply_class, return_instance_id, return_period, credit_days, due_date, gross_total, line_discount_total,"
            " invoice_discount, charges_total, taxable_total, cgst_total, sgst_total, utgst, igst_total, round_off,"
            " doc_total, amount_in_words, print, rounding_mode, method_version, finalized_by) values (:id, :b, :draft,"
            " :kind, :practice, :series, :number, :doc_date, :fy, :gstin, :supplier_state, :customer, :cp_gstin,"
            " :cp_name, :pos, :inter, :class, :instance, :period, :credit_days, :due, :gross, :line_disc, :inv_disc, :charges, :taxable,"
            " :cgst, :sgst, :utgst, :igst, :round_off, :total, :words, :print, :rounding, :method, :me)"
        ).bindparams(bindparam("print", type_=JSON)),
        {
            "id": document_id,
            "b": b,
            "draft": d["id"],
            "kind": d["kind"],
            "practice": practice,
            "series": series_id,
            "number": number,
            "doc_date": doc_date,
            "fy": fy,
            "gstin": profile.gstin,
            "supplier_state": profile.state_code,
            "customer": d["customer_id"],
            "cp_gstin": bill_to.get("gstin"),
            "cp_name": bill_to.get("name"),
            "pos": c.pos_state_code,
            "inter": c.is_inter_state,
            "class": c.supply_class,
            "instance": None if assigned is None else assigned.id,
            "period": None if assigned is None else assigned.period,
            "credit_days": credit_days,
            "due": doc_date + timedelta(days=credit_days),
            "gross": c.gross_total,
            "line_disc": c.line_discount_total,
            "inv_disc": c.invoice_discount,
            "charges": c.charges_total,
            "taxable": c.taxable_total,
            "cgst": c.cgst_total,
            "sgst": c.sgst_total,
            "utgst": c.utgst,
            "igst": c.igst_total,
            "round_off": c.round_off,
            "total": c.doc_total,
            "words": c.amount_in_words,
            "print": _print(d, profile),
            "rounding": c.rounding_mode,
            "method": c.method_version,
            "me": uow.principal.user_id,
        },
    )
    # #450: a percent discount keeps its percent for the PDF ("50% / 175.00"); the amount is the computed one.
    percent_off = {dl["line_no"]: dl["discount_value"] for dl in d["lines"]
                   if dl.get("discount_kind") == "percent" and dl.get("discount_value") is not None}
    for ln in c.lines:
        line_id = uuid7()
        p = ln.product
        tx.execute(
            text(
                "insert into sales.document_lines (id, business_id, document_id, line_no, product_id, code, name, hsn,"
                " uqc, quantity, unit_price, gross, line_discount, discount_share, charge_share, taxable, rate,"
                " rate_confirmed, mrp, discount_percent) values (:id, :b, :doc, :line_no, :product, :code, :name, :hsn,"
                " :uqc, :qty, :price, :gross, :line_disc, :disc_share, :charge_share, :taxable, :rate, :confirmed, :mrp,"
                " :disc_pct)"
            ),
            {
                "id": line_id,
                "b": b,
                "doc": document_id,
                "line_no": ln.line_no,
                "product": p.product_id,
                "code": p.code,
                "name": p.name,
                "hsn": p.hsn or "",  # blank only on a B2C line the compute warned about (hsn_missing_b2c)
                "uqc": p.uqc,
                "qty": ln.quantity,
                "price": ln.unit_price,
                "gross": ln.gross,
                "line_disc": ln.line_discount,
                "disc_share": ln.discount_share,
                "charge_share": ln.charge_share,
                "taxable": ln.taxable,
                "rate": ln.rate,
                "confirmed": p.rate_confirmed,
                "mrp": p.mrp,  # #450: printed on the PDF as issued, never read back from the product
                "disc_pct": percent_off.get(ln.line_no),
            },
        )
        # R2-M4: the sale takes stock out, once per invoice line, in this same transaction. It
        # never refuses for lack of stock (the balance may go to or below zero).
        record_sale_out(uow, product_id=p.product_id, quantity=ln.quantity, document_id=document_id,
                        document_line_id=line_id, sold_on=doc_date, practice=practice)
        for t in ln.taxes:
            tx.execute(
                text(
                    "insert into sales.document_line_taxes (line_id, business_id, component, rate, amount)"
                    " values (:line, :b, :component, :rate, :amount)"
                ),
                {"line": line_id, "b": b, "component": t.component, "rate": t.rate, "amount": t.amount},
            )
    if d["pos_override"] is not None:
        tx.execute(
            text(
                "insert into sales.pos_overrides (document_id, business_id, computed_pos, chosen_pos, reason)"
                " values (:doc, :b, :computed, :chosen, :reason)"
            ),
            {
                "doc": document_id,
                "b": b,
                "computed": c.computed_pos,
                "chosen": c.pos_state_code,
                "reason": d["pos_override_reason"],
            },
        )
    return document_id


def _print(d: dict, profile: Profile) -> dict:
    """What the PDF shows besides the money (L4-9), as it is at finalize: later edits to
    the profile or the customer never change it. No amounts. Branding waits for LLD-1's
    branding table and is empty until then."""
    return {
        "seller": {
            "legal_name": profile.legal_name,
            "trade_name": profile.trade_name,
            "gstin": profile.gstin,
            "line1": profile.address_line1,
            "line2": profile.address_line2,
            "city": profile.city,
            "pin": profile.pin,
            "state_code": profile.address_state_code or profile.state_code,
        },
        "bill_to": d["bill_to"],
        "ship_to": d["ship_to"],
        "cash_buyer": d["cash_buyer"],
        "ship_to_third_party": d["ship_to_third_party"],
        "customer_collects": d["customer_collects"],
        "eway": d["eway"],
        "charge_labels": [ch["label"] for ch in d["charges"]],
        "branding": {},
    }

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

from app.modules.business.fiscal import fy_of
from app.modules.business.interface import Profile, SeriesSetting, get_profile, series_setting
from app.modules.catalog.interface import customer_snapshot, mark_used
from app.modules.refdata import RefdataMissing, value_on
from platform_common import audit
from platform_common.errors import Deny, Invalid
from platform_common.ids import uuid7
from platform_common.uow import UnitOfWork

from . import drafts
from .compute import Computation, Issue

# L4-2's default: one series per GSTIN, document kind and FY. The only scope refdata may
# name today; another one needs code here and a migration for its unique index.
SCOPE_GSTIN_KIND_FY = "gstin_kind_fy"
_DOCUMENT_COLUMNS = (
    "id, draft_id, kind, is_practice, doc_number, doc_date, fy, gstin, supply_class, pos_state_code,"
    " is_inter_state, customer_id, counterparty_name, due_date, taxable_total, cgst_total, sgst_total, utgst,"
    " igst_total, round_off, doc_total, finalized_at"
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


def enabled(uow: UnitOfWork, today: date) -> bool:
    """The switch. No row on `today` counts as off."""
    try:
        return value_on(uow.tx, "sales.finalize.enabled", today) is True
    except RefdataMissing:
        return False


def _business(uow: UnitOfWork) -> uuid.UUID:
    return uow.principal.business_id


def document_for_draft(uow: UnitOfWork, draft_id: uuid.UUID) -> dict | None:
    row = (
        uow.tx.execute(
            text(f"select {_DOCUMENT_COLUMNS} from sales.documents where draft_id = :d and business_id = :b"),
            {"d": draft_id, "b": _business(uow)},
        )
        .mappings()
        .one_or_none()
    )
    return None if row is None else dict(row)


def finalize(uow: UnitOfWork, draft_id: uuid.UUID, if_match: int | None, today: date) -> dict:
    """The draft's document. A draft finalized already (a retry, a second tab) gives the
    same document back, whatever the key (BH-5, AC4-3)."""
    done = document_for_draft(uow, draft_id)
    if done is not None:
        return done
    try:
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
    if not practice:
        raise Invalid(
            "live_numbering_unavailable",
            "Live invoice numbers aren't available yet; this business can issue practice invoices only.",
            field="numbering",
        )
    profile = get_profile(uow.tx)
    if profile is None or not profile.gstin:  # ready_for_documents blocks this first; kept as a guard
        raise Invalid("business_profile_missing", "Add your business details first.", field="business")
    doc_date = d["doc_date"] or today
    fy = fy_of(doc_date)
    series_id, number = allocate(
        uow, gstin=profile.gstin, kind=d["kind"], fy=fy, practice=practice, setting=setting, on=doc_date
    )
    mark_used(uow.tx, [ln.product.product_id for ln in c.lines], d["customer_id"])
    document_id = _insert(
        uow, d, c, profile, series_id=series_id, number=number, doc_date=doc_date, fy=fy, practice=practice
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
        data={"number": number, "kind": d["kind"], "practice": practice, "draft_id": str(draft_id)},
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


def allocate(
    uow: UnitOfWork, *, gstin: str, kind: str, fy: str, practice: bool, setting: SeriesSetting | None, on: date
) -> tuple[uuid.UUID, str]:
    """The next number in the series the configured scope picks (D-030): the FY's series
    row is created on first use with the prefix in force then (L4-2), then locked FOR
    UPDATE and advanced by one. A rollback leaves next_value where it was."""
    tx = uow.tx
    scope = value_on(tx, "sales.numbering_scope", on)
    if scope != SCOPE_GSTIN_KIND_FY:
        raise RuntimeError(f"numbering scope {scope!r} is not built")  # refdata allows only the one
    if practice:
        series_kind = "practice"
        prefix = value_on(tx, "sales.practice_prefix", on)
        width = value_on(tx, "sales.practice_width", on)
        first = 1
    else:  # F2; unreachable in F1
        assert setting is not None
        series_kind, prefix, width, first = kind, setting.prefix, setting.width, setting.first_value
    key = {"b": _business(uow), "g": gstin, "k": series_kind, "fy": fy}
    tx.execute(
        text(
            "insert into sales.number_series (id, business_id, gstin, kind, fy, prefix, width, next_value)"
            " values (:id, :b, :g, :k, :fy, :prefix, :width, :first)"
            " on conflict (business_id, gstin, kind, fy) do nothing"
        ),
        {**key, "id": uuid7(), "prefix": prefix, "width": width, "first": first},
    )
    series_id, prefix, width, value = tx.execute(
        text(
            "select id, prefix, width, next_value from sales.number_series"
            " where business_id = :b and gstin = :g and kind = :k and fy = :fy for update"
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
) -> uuid.UUID:
    tx, b = uow.tx, _business(uow)
    document_id = uuid7()
    credit_days = customer_snapshot(tx, d["customer_id"]).credit_days if d["customer_id"] else 0
    bill_to = d["bill_to"] or {}
    tx.execute(
        text(
            "insert into sales.documents (id, business_id, draft_id, kind, is_practice, series_id, doc_number,"
            " doc_date, fy, gstin, supplier_state_code, customer_id, counterparty_gstin, counterparty_name,"
            " pos_state_code, is_inter_state, supply_class, credit_days, due_date, gross_total, line_discount_total,"
            " invoice_discount, charges_total, taxable_total, cgst_total, sgst_total, utgst, igst_total, round_off,"
            " doc_total, amount_in_words, print, rounding_mode, method_version, finalized_by) values (:id, :b, :draft,"
            " :kind, :practice, :series, :number, :doc_date, :fy, :gstin, :supplier_state, :customer, :cp_gstin,"
            " :cp_name, :pos, :inter, :class, :credit_days, :due, :gross, :line_disc, :inv_disc, :charges, :taxable,"
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
    for ln in c.lines:
        line_id = uuid7()
        p = ln.product
        tx.execute(
            text(
                "insert into sales.document_lines (id, business_id, document_id, line_no, product_id, code, name, hsn,"
                " uqc, quantity, unit_price, gross, line_discount, discount_share, charge_share, taxable, rate,"
                " rate_confirmed) values (:id, :b, :doc, :line_no, :product, :code, :name, :hsn, :uqc, :qty, :price,"
                " :gross, :line_disc, :disc_share, :charge_share, :taxable, :rate, :confirmed)"
            ),
            {
                "id": line_id,
                "b": b,
                "doc": document_id,
                "line_no": ln.line_no,
                "product": p.product_id,
                "code": p.code,
                "name": p.name,
                "hsn": p.hsn,
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
            },
        )
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

"""Finalized-invoice PDFs (R2-M5): the same job-and-renderer path as the draft preview.

    POST /b/{b}/documents/{id}/pdf          -> 202 {job_id, attempt}
    GET  /b/{b}/documents/{id}/pdf/{job_id} -> {status, url?}

A finalized document never changes (sales.documents is insert-only), so its PDF is made from
the stored rows and the print snapshot taken at finalize (finalize._print), never from the
live profile, customer or product. Asking again gives the same job and the same PDF. Only if
the last attempt failed does a new request make a new attempt: the job's natural key is
`<document id>:<attempt>`, and the earlier failed jobs stay as the record.

Until live numbering is approved (D-010, D-044) every document is a practice document and the
page says so; the renderer refuses anything else (renderer/document_template.py). The PDF is
made on request, not queued by finalize, so a finalize never waits on the renderer.
Every value is a decimal string formatted here. The only sums are a line's own total (its stored
taxable value plus its stored tax amounts) and the tax summary by HSN and rate (#450), which adds
up the stored line amounts, so it always equals the stored invoice totals.
"""

import re
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import text

from app.modules.identity.interface import member_role
from app.modules.refdata import state_name
from platform_common import audit, jobs, render
from platform_common.clock import get_clock
from platform_common.errors import Deny
from platform_common.permissions import Permission, has_permission
from platform_common.storage import get_store
from platform_common.uow import UnitOfWork

JOB = "sales.document_pdf"
_GSTIN_PAN = re.compile(r"[0-9]{2}([A-Z]{5}[0-9]{4}[A-Z])[0-9A-Z]{3}")


def _exists(uow: UnitOfWork, document_id: uuid.UUID) -> None:
    found = uow.tx.execute(
        text("select 1 from sales.documents where id = :d and business_id = :b"),
        {"d": document_id, "b": uow.principal.business_id},
    ).first()
    if found is None:
        raise Deny("not_found")


def _failed(uow: UnitOfWork, job: jobs.JobView) -> str | None:
    """The error code if this attempt has failed, else None."""
    if job.status == "failed":
        return job.error_code
    if job.status != "done":
        return None
    business = uow.principal.business_id
    if render.is_rendered(business, job.id):
        return None
    if render.has_failed(business, job.id) or get_clock().now() - job.updated_at > render.GIVE_UP_AFTER:
        return "render_failed"
    return None


def _attempt(job: jobs.JobView) -> int:
    *_, number = (job.natural_key or "").rpartition(":")
    return int(number)


def queue(uow: UnitOfWork, document_id: uuid.UUID) -> tuple[uuid.UUID, int]:
    """The job for this document's PDF: (job id, attempt). A new attempt only after the last one failed."""
    _exists(uow, document_id)
    last = jobs.latest(uow, JOB, f"{document_id}:")
    attempt = 1 if last is None else _attempt(last) + (1 if _failed(uow, last) else 0)
    job_id = jobs.create(uow, JOB, natural_key=f"{document_id}:{attempt}")
    if last is None or attempt != _attempt(last):
        audit.record(uow, "document.pdf_requested", "document", document_id, data={"attempt": attempt})
    return job_id, attempt


def status(uow: UnitOfWork, document_id: uuid.UUID, job_id: uuid.UUID) -> dict:
    """queued, rendering, ready (with a 60-second link) or failed. A job that is not this
    document's PDF is the same 404 as one that doesn't exist."""
    job = jobs.get(uow, job_id)
    if job is None or job.type != JOB or not (job.natural_key or "").startswith(f"{document_id}:"):
        raise Deny("not_found")
    code = _failed(uow, job)
    if code is not None:
        return {"status": "failed", "error_code": code}
    if job.status != "done":
        return {"status": "queued"}
    business = uow.principal.business_id
    if not render.is_rendered(business, job_id):
        return {"status": "rendering"}
    kind = uow.tx.execute(
        text("select kind from sales.documents where id = :d and business_id = :b"), {"d": document_id, "b": business},
    ).scalar_one_or_none()
    name = "practice-credit-note.pdf" if kind == "credit_note" else "practice-invoice.pdf"
    url = get_store().presign_get(business, render.document_key(business, job_id), download_name=name)
    return {"status": "ready", "url": url}


def current(uow: UnitOfWork, document_id: uuid.UUID) -> dict:
    """Where the PDF stands, without asking for one: `none` before any request, else the newest attempt's status
    (queued, rendering, ready with a link, failed) and its job id, so a reload can pick the poll up again."""
    last = jobs.latest(uow, JOB, f"{document_id}:")
    if last is None:
        return {"status": "none", "job_id": None, "attempt": None}
    return {**status(uow, document_id, last.id), "job_id": str(last.id), "attempt": _attempt(last)}


# -- the job ------------------------------------------------------------------------------

def _money(value) -> str | None:
    return None if value is None else str(Decimal(value).quantize(Decimal("0.01")))


def _qty(value) -> str:
    return format(Decimal(value).normalize(), "f")


def _state(tx, code: str | None, on: date) -> str | None:
    if not code:
        return None
    name = state_name(tx, code, on)
    return f"{name} ({code})" if name else code


def _address(*parts) -> list[str]:
    return [p for p in parts if p]


def _ship_to(tx, snap: dict, on: date) -> dict | None:
    """The ship-to for the page: its address and state, and a name (#452): the consignee named on the invoice, else the
    bill-to's name, because without a consignee the goods go to the buyer's own delivery address."""
    ship = _party(tx, snap.get("ship_to"), on)
    if ship is None:
        return None
    bill = snap.get("bill_to") or snap.get("cash_buyer") or {}
    return {"name": ship["name"] or bill.get("name") or bill.get("legal_name"), "address": ship["address"],
            "state": ship["state"]}


def _party(tx, p: dict | None, on: date) -> dict | None:
    if p is None:
        return None
    return {
        "name": p.get("name") or p.get("legal_name"),
        "gstin": p.get("gstin"),
        "address": _address(p.get("line1"), p.get("line2"), " ".join(_address(p.get("city"), p.get("pin"))) or None),
        "state": _state(tx, p.get("state_code"), on),
    }


def _lines(tx, business_id: uuid.UUID, document_id: uuid.UUID) -> list[dict]:
    """The stored lines with their stored tax amounts, as decimal strings; the only sum is a line's own total."""
    lines = []
    for ln in tx.execute(
        text("select id, line_no, name, hsn, uqc, quantity, unit_price, gross, line_discount, taxable, rate, mrp,"
             " discount_percent from sales.document_lines where document_id = :d and business_id = :b order by line_no"),
        {"d": document_id, "b": business_id},
    ).mappings().all():
        taxes = tx.execute(
            text("select component, rate, amount from sales.document_line_taxes where line_id = :l and"
                 " business_id = :b order by component"),
            {"l": ln["id"], "b": business_id},
        ).all()
        lines.append({
            "no": str(ln["line_no"]), "description": ln["name"], "hsn": ln["hsn"], "quantity": _qty(ln["quantity"]),
            "uqc": ln["uqc"], "mrp": _money(ln["mrp"]), "unit_price": _money(ln["unit_price"]),
            "gross": _money(ln["gross"]),
            "discount": _money(ln["line_discount"]) if ln["line_discount"] else None,
            "discount_percent": _qty(ln["discount_percent"])
            if ln["line_discount"] and ln["discount_percent"] is not None else None,
            "taxable": _money(ln["taxable"]),
            "taxes": [{"component": c, "rate": _qty(r), "amount": _money(a)} for c, r, a in taxes],
            "total": _money(Decimal(ln["taxable"]) + sum((Decimal(a) for _, _, a in taxes), Decimal())),
            "_rate": ln["rate"],  # for hsn_summary only; dropped before the render input is written
        })
    return lines


def _without_rate(lines: list[dict]) -> list[dict]:
    return [{k: v for k, v in ln.items() if k != "_rate"} for ln in lines]


def hsn_summary(lines: list[dict]) -> list[dict]:
    """The stored lines added up by (HSN, GST rate), in first-seen order: taxable value and each tax component.
    Sums of stored amounts only, so the rows always add up to the invoice's stored totals (#450)."""
    groups: dict[tuple[str, Decimal], dict] = {}
    for ln in lines:
        g = groups.setdefault((ln["hsn"], Decimal(ln["_rate"])), {"taxable": Decimal(), "taxes": {}})
        g["taxable"] += Decimal(ln["taxable"])
        for t in ln["taxes"]:
            g["taxes"][t["component"]] = g["taxes"].get(t["component"], Decimal()) + Decimal(t["amount"])
    return [
        {"hsn": hsn, "rate": _qty(rate), "taxable": _money(g["taxable"]),
         "taxes": [{"component": c, "amount": _money(a)} for c, a in g["taxes"].items()]}
        for (hsn, rate), g in groups.items()
    ]


def pan_of(gstin: str | None) -> str | None:
    """The PAN inside a GSTIN (the ten characters after the state code), when it has the PAN shape; else None."""
    found = _GSTIN_PAN.fullmatch(gstin or "")
    return found.group(1) if found else None


def _pos_basis(tx, business_id: uuid.UUID, document_id: uuid.UUID, counterparty_gstin: str | None,
               snap: dict) -> tuple[str, str | None]:
    """Why the stored place of supply is what it is, read back from what finalize stored: the override trail, whether
    the buyer had a GSTIN, and the third-party and customer-collects flags in the print snapshot. The same order as
    `compute.core._place_of_supply`; it states what the app did and adds no rule of its own."""
    reason = tx.execute(
        text("select reason from sales.pos_overrides where document_id = :d and business_id = :b"),
        {"d": document_id, "b": business_id},
    ).scalar_one_or_none()
    if reason is not None:
        return "override", reason
    if not counterparty_gstin:
        return "buyer_address", None
    if snap.get("ship_to_third_party"):
        return "third_party", None
    if snap.get("customer_collects"):
        return "customer_collects", None
    return "delivery", None


def view(tx, business_id: uuid.UUID, document_id: uuid.UUID) -> dict:
    """What the invoice page shows besides the stored header: the buyer and ship-to as snapshotted at finalize, the
    place of supply, the lines with their tax split, and the amount in words. Read-only; no money is worked out."""
    doc = tx.execute(
        text("select print, doc_date, pos_state_code, counterparty_gstin, amount_in_words, gross_total,"
             " line_discount_total, invoice_discount, charges_total, cess_total"
             " from sales.documents where id = :d and business_id = :b"),
        {"d": document_id, "b": business_id},
    ).mappings().one()
    snap, on = doc["print"], doc["doc_date"]
    basis, override_reason = _pos_basis(tx, business_id, document_id, doc["counterparty_gstin"], snap)
    buyer = _party(tx, snap.get("bill_to"), on)
    if buyer is None and snap.get("cash_buyer"):
        buyer = _party(tx, snap["cash_buyer"], on)
    ship = _ship_to(tx, snap, on)
    labels = snap.get("charge_labels") or []
    return {
        "buyer": buyer,
        "ship_to": None if ship is None else {"address": ship["address"], "state": ship["state"]},
        "place_of_supply": _state(tx, doc["pos_state_code"], on),
        "pos_basis": basis,
        "pos_override_reason": override_reason,
        "lines": _without_rate(_lines(tx, business_id, document_id)),
        "gross_total": _money(doc["gross_total"]),
        "line_discount_total": _money(doc["line_discount_total"]),
        "invoice_discount": _money(doc["invoice_discount"]),
        "charges_total": _money(doc["charges_total"]),
        "charges_label": ", ".join(labels) or ("Charges" if doc["charges_total"] else None),
        "cess_total": _money(doc["cess_total"]),
        "amount_in_words": doc["amount_in_words"],
        "original": snap.get("original"),
        "reason": snap.get("reason"),
        "stock_treatment": snap.get("stock_treatment"),
    }


def build(tx, business_id: uuid.UUID, document_id: uuid.UUID) -> dict:
    """The render input for one stored document (template invoice-document)."""
    doc = tx.execute(
        text("select doc_number as number, kind, doc_date, due_date, is_practice, print, pos_state_code, taxable_total,"
             " cgst_total, sgst_total, utgst, igst_total, round_off, doc_total, amount_in_words, is_inter_state,"
             " invoice_discount, charges_total from sales.documents where id = :d and business_id = :b"),
        {"d": document_id, "b": business_id},
    ).mappings().one_or_none()
    if doc is None:
        raise jobs.JobFailed("document_not_found")
    if not doc["is_practice"]:
        raise jobs.JobFailed("live_template_not_approved")
    on, snap = doc["doc_date"], doc["print"]
    lines = _lines(tx, business_id, document_id)
    if doc["is_inter_state"]:
        heads = [("IGST", doc["igst_total"])]
    else:
        heads = [("CGST", doc["cgst_total"]), ("UTGST" if doc["utgst"] else "SGST", doc["sgst_total"])]
    labels = snap.get("charge_labels") or []
    seller = snap.get("seller") or {}
    ship = _ship_to(tx, snap, on)
    seller_out = _party(tx, seller, on) or {}
    trade = seller.get("trade_name")
    seller_out["trade_name"] = trade if trade and trade != seller.get("legal_name") else None
    seller_out["pan"] = pan_of(seller_out.get("gstin"))
    note = None
    # CGST Rule 48(1): goods invoices in triplicate. One PDF holds the three copies, each its own page set (#454).
    copies = ["Original for Recipient", "Duplicate for Transporter", "Triplicate for Supplier"]
    if doc["kind"] == "credit_note":
        # Rule 53(1A) (#456): the note names the invoice it adjusts; an original and a duplicate, no transporter copy.
        original = snap.get("original") or {}
        note = {"kind": "credit_note", "original_number": original.get("number"),
                "original_date": original.get("date"), "reason": snap.get("reason")}
        copies = ["Original for Recipient", "Duplicate for Supplier"]
    return {
        "template": "invoice-document",
        "practice": True,
        "note": note,
        "number": doc["number"],
        "doc_date": on.isoformat(),
        "due_date": doc["due_date"].isoformat() if doc["due_date"] and note is None else None,
        "copy_label": "Original for Recipient",
        "copies": copies,
        "seller": seller_out,
        "buyer": _party(tx, snap.get("bill_to"), on),
        "ship_to": ship,
        "place_of_supply": _state(tx, doc["pos_state_code"], on),
        "reverse_charge": "No",
        "lines": _without_rate(lines),
        "hsn_summary": hsn_summary(lines),
        "charges": [{"label": ", ".join(labels) or "Charges", "amount": _money(doc["charges_total"])}]
        if doc["charges_total"] else [],
        "invoice_discount": _money(doc["invoice_discount"]) if doc["invoice_discount"] else None,
        "totals": {
            "taxable": _money(doc["taxable_total"]),
            "taxes": [{"component": c, "amount": _money(a)} for c, a in heads],
            "round_off": _money(doc["round_off"]) if doc["round_off"] else None,
            "total": _money(doc["doc_total"]),
            "in_words": doc["amount_in_words"],
        },
    }


@jobs.handler(JOB)
def run(ctx: jobs.JobContext) -> dict:
    view = jobs.get(ctx.uow, ctx.job_id)
    if view is None or not view.natural_key:
        raise jobs.JobFailed("not_found")
    document_id = uuid.UUID(view.natural_key.partition(":")[0])
    p = ctx.uow.principal
    # The job runs as whoever asked, a moment later; they may have lost access since.
    if not has_permission(member_role(ctx.uow.tx, p.business_id, p.user_id), Permission.DOCUMENTS_VIEW):
        raise jobs.JobFailed("not_allowed")
    render.request(p.business_id, ctx.job_id, build(ctx.uow.tx, p.business_id, document_id))
    return {"render_id": str(ctx.job_id)}

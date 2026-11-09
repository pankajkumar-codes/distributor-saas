"""Draft preview PDFs (S4, BH-6; D-042): the first use of the PDF renderer.

    POST /b/{b}/drafts/{id}/preview          -> 202 {job_id, draft_version}
    GET  /b/{b}/drafts/{id}/preview/{job_id} -> {status, url?}

The POST queues one `sales.draft_preview` job per draft version (the natural key is
`<draft id>:<version>`), so asking twice for the same version gives the same job and the
same PDF. The job, on the worker, reads the draft as it is at that version, builds the
render input (template "invoice-draft", renderer/renderer/template.py has its shape) and
hands it to platform_common.render, which writes it under render-input/b/ and queues
its key for the renderer. The PDF lands at documents/b/<business>/<job id>/document.pdf.

A preview is not a tax invoice and says so: it has no number and its title is "Draft, not
a tax invoice". Its tax figures are the invoice computation's, exactly as a save stores
them (drafts.computation, which is compute(load_inputs(...)), S4-b): the place of supply,
each line's taxable value, rate, tax and total, the totals, round-off and amount in
words. What still stops the draft from being finalized (the computation's blocks) is
listed under "Before you can finalize". A draft the computation refuses (for example a
date the app has no GST rules for) fails the job with that error code, as a save would.
Every value is a decimal string formatted here; nothing here does tax arithmetic.
"""

import uuid
from datetime import date
from decimal import Decimal

from app.modules.business.interface import get_profile
from app.modules.catalog.interface import products_for_lines
from app.modules.identity.interface import member_role
from app.modules.refdata import state_name
from platform_common import jobs, render
from platform_common.clock import get_clock
from platform_common.errors import Deny, Invalid
from platform_common.permissions import Permission, has_permission
from platform_common.storage import get_store
from platform_common.uow import UnitOfWork

from . import drafts
from .compute import Computation

JOB = "sales.draft_preview"
MAX_BLOCKS = 50  # the template prints at most this many (renderer template MAX_LIST)


def queue(uow: UnitOfWork, draft_id: uuid.UUID) -> tuple[uuid.UUID, int]:
    """The preview job for the draft's current version: (job id, version)."""
    version = drafts.get(uow, draft_id)["version"]
    return jobs.create(uow, JOB, natural_key=f"{draft_id}:{version}"), version


def status(uow: UnitOfWork, draft_id: uuid.UUID, job_id: uuid.UUID) -> dict:
    """queued, rendering, ready (with a 60-second link) or failed (the job's error code, or
    render_failed when the renderer gave up after its last try, or still has no PDF
    render.GIVE_UP_AFTER after the job queued it). A job that is not this
    draft's preview is the same 404 as one that doesn't exist."""
    job = jobs.get(uow, job_id)
    if job is None or job.type != JOB or not (job.natural_key or "").startswith(f"{draft_id}:"):
        raise Deny("not_found")
    if job.status == "failed":
        return {"status": "failed", "error_code": job.error_code}
    if job.status != "done":
        return {"status": "queued"}
    business = uow.principal.business_id
    if not render.is_rendered(business, job_id):
        # The renderer gave up (failed.json), or its last try ended without a word (a
        # timeout or out of memory) and the message is in the DLQ by now.
        if render.has_failed(business, job_id) or get_clock().now() - job.updated_at > render.GIVE_UP_AFTER:
            return {"status": "failed", "error_code": "render_failed"}
        return {"status": "rendering"}
    url = get_store().presign_get(business, render.document_key(business, job_id),
                                  download_name="draft-preview.pdf")
    return {"status": "ready", "url": url}


# -- the job ------------------------------------------------------------------------------

def _state(tx, code: str | None, on: date) -> str | None:
    if not code:
        return None
    name = state_name(tx, code, on)
    return f"{name} ({code})" if name else code


def _address(*parts) -> list[str]:
    return [p for p in parts if p]


def _money(value) -> str | None:
    return None if value is None else str(Decimal(value).quantize(Decimal("0.01")))


def _qty(value: Decimal) -> str:
    return format(Decimal(value).normalize(), "f")  # 2.000 -> 2, 1.250 -> 1.25


def _components(comp: Computation) -> list[tuple[str, Decimal]]:
    """The tax heads the document carries: IGST inter-state, CGST and SGST (or UTGST)
    intra-state, none while the place of supply is unknown."""
    if comp.is_inter_state is None:
        return []
    if comp.is_inter_state:
        return [("IGST", comp.igst_total)]
    return [("CGST", comp.cgst_total), ("UTGST" if comp.utgst else "SGST", comp.sgst_total)]


def _totals(comp: Computation) -> dict:
    return {
        "taxable": _money(comp.taxable_total),
        "taxes": [{"component": c, "amount": _money(a)} for c, a in _components(comp)],
        "round_off": None if not comp.round_off else _money(comp.round_off),
        "total": _money(comp.doc_total),
        "in_words": comp.amount_in_words,
    }


def _line_tax(out) -> dict:
    return {
        "taxable": _money(out.taxable),
        "rate": None if out.rate is None else _qty(out.rate),
        "taxes": [{"component": t.component, "rate": _qty(t.rate), "amount": _money(t.amount)} for t in out.taxes],
        "total": _money(out.total),
    }


def _blocks(comp: Computation) -> list[str]:
    """What stops a finalize, each fix once, in the computation's order."""
    out: list[str] = []
    for b in comp.blocks:
        fix = f"Line {b.line_no}: {b.fix}" if b.line_no else b.fix
        if fix not in out:
            out.append(fix)
    return out[:MAX_BLOCKS]


def build(tx, d: dict, today: date, comp: Computation) -> dict:
    """The render input for one draft (render input v1, template invoice-draft), with the
    computation `comp` for that same draft."""
    on = d["doc_date"] or today
    computed = {ln.line_no: ln for ln in comp.lines}
    profile = get_profile(tx)
    if profile is None:
        raise jobs.JobFailed("no_profile")
    seller = {
        "name": profile.legal_name or profile.trade_name or "",
        "trade_name": profile.trade_name if profile.trade_name and profile.trade_name != profile.legal_name else None,
        "gstin": profile.gstin,
        "address": _address(profile.address_line1, profile.address_line2,
                            " ".join(_address(profile.city, profile.pin)) or None),
        "state": _state(tx, profile.address_state_code or profile.state_code, on),
    }
    bill = d["bill_to"]
    buyer = None
    if bill is not None:
        cash = d["cash_buyer"] or {}
        buyer = {
            "name": bill.get("name"),
            "gstin": bill.get("gstin"),
            "address": _address(bill.get("line1"), bill.get("line2"),
                                " ".join(_address(bill.get("city"), bill.get("pin"))) or None, cash.get("address")),
            "state": _state(tx, bill.get("state_code"), on),
        }
    ship = d["ship_to"]
    ship_to = None
    if ship is not None and bill is not None and any(ship.get(k) != bill.get(k) for k in ship):
        ship_to = {"address": _address(ship.get("line1"), ship.get("line2"),
                                       " ".join(_address(ship.get("city"), ship.get("pin"))) or None),
                   "state": _state(tx, ship.get("state_code"), on)}
    products = products_for_lines(tx, [ln["product_id"] for ln in d["lines"]], on)
    lines = []
    for ln in d["lines"]:
        p = products.get(ln["product_id"])
        discount = None
        if ln["discount_kind"] == "percent":
            discount = f"{_money(ln['discount_value'])}%"
        elif ln["discount_kind"] == "amount":
            discount = _money(ln["discount_value"])
        lines.append({
            "no": str(ln["line_no"]),
            "description": p.name if p else "Product no longer in your list",
            "hsn": p.hsn if p else None,
            "quantity": _qty(ln["quantity"]),
            "uqc": (p.uqc if p else None),
            "unit_price": _money(ln["unit_price"]),
            "discount": discount,
            **(_line_tax(computed[ln["line_no"]]) if ln["line_no"] in computed else {}),
        })
    return {
        "template": "invoice-draft",
        "seller": seller,
        "buyer": buyer,
        "ship_to": ship_to,
        "doc_date": on.isoformat() if d["doc_date"] else None,
        "place_of_supply": _state(tx, comp.pos_state_code, on),
        "reverse_charge": "No",
        "lines": lines,
        "charges": [{"label": c["label"], "amount": _money(c["amount"])} for c in d["charges"] or []],
        "invoice_discount": _money(d["invoice_discount"]),
        "totals": _totals(comp),
        "blocks": _blocks(comp),
    }


def _target(ctx: jobs.JobContext) -> tuple[uuid.UUID, int]:
    """The draft and version are the job's natural key, read under RLS, never from the
    queue message."""
    view = jobs.get(ctx.uow, ctx.job_id)
    if view is None or not view.natural_key:
        raise jobs.JobFailed("not_found")
    draft_id, _, version = view.natural_key.partition(":")
    return uuid.UUID(draft_id), int(version)


@jobs.handler(JOB)
def run(ctx: jobs.JobContext) -> dict:
    draft_id, version = _target(ctx)
    p = ctx.uow.principal
    # The job runs as whoever asked, a moment later; they may have lost access since.
    if not has_permission(member_role(ctx.uow.tx, p.business_id, p.user_id), Permission.DOCUMENTS_VIEW):
        raise jobs.JobFailed("not_allowed")
    try:
        d = drafts.get(ctx.uow, draft_id)
    except Deny:
        raise jobs.JobFailed("draft_not_found") from None
    if d["version"] != version:
        raise jobs.JobFailed("draft_changed")  # the user saved again; they ask for a new preview
    today = get_clock().today()
    try:
        comp = drafts.computation(ctx.uow, d, today=today)
    except Invalid as e:
        raise jobs.JobFailed(e.code) from None  # e.g. doc_date_not_supported, as the save says
    render.request(p.business_id, ctx.job_id, build(ctx.uow.tx, d, today, comp))
    return {"render_id": str(ctx.job_id)}

"""Debit notes (#456 part 3, CGST s.34(3)): made from an issued invoice, by amount (value charged too low) or by
quantity (more goods sent, which leave stock), tax at the line's own rate, practice notes in their own PR-DN- series,
and what is left to credit grows by what a debit note adds. A live one is a supply line with note type D.

Made-up data. Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import sys
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text

from .conftest import PG_ADMIN_URL, as_user, scalar
from .test_cancel_postgres import MISTAKE, cancel
from .test_credit_notes_postgres import invoice, note, returned, state, taxes_of
from .test_finalize_live_postgres import flip_live, live  # noqa: F401
from .test_finalize_postgres import fin, ready_draft, shop, switch  # noqa: F401

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


def rendered(body: dict) -> list[str]:
    """The renderer's own template over a PDF body (#466: the page it draws, not only the input we build). Pure
    HTML; WeasyPrint is not needed for this step."""
    root = str(Path(__file__).resolve().parents[6] / "renderer")
    if root not in sys.path:
        sys.path.insert(0, root)
    from renderer import template

    return template.render_htmls({**body, "v": 1})  # platform_common.render adds the version when it writes


def debit(pg, biz, doc_id, body, sub="alice", key=None):
    return pg.client.post(f"/api/v1/b/{biz}/documents/{doc_id}/debit-notes", json=body,
                          headers={**as_user(sub), "Idempotency-Key": key or uuid.uuid4().hex})


def by_value(line_id, taxable):
    return {"reason": "value_too_low", "lines": [{"original_line_id": line_id, "taxable": taxable}]}


def more_goods(line_id, qty):
    return {"reason": "more_goods", "lines": [{"original_line_id": line_id, "quantity": qty}]}


def test_a_value_debit_note_takes_its_own_series_adds_tax_at_the_line_rate_and_makes_room_to_credit(shop):  # noqa: F811
    pg, biz, _ = shop
    switch(pg, True)
    inv = invoice(pg, biz, qty="2", price="100.00")  # taxable 200.00 at 18%
    line = state(pg, biz, inv["id"]).json()["lines"][0]["original_line_id"]
    r = debit(pg, biz, inv["id"], by_value(line, "50.00"))
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["kind"] == "debit_note" and d["doc_number"] == "PR-DN-0001" and d["is_practice"]
    assert d["original_document_id"] == inv["id"] and d["reason_code"] == "value_too_low" and d["supply_class"] == "CDNR"
    assert d["taxable_total"] == "50.00" and d["doc_total"] == "59.00"
    assert sum(taxes_of(pg, d["id"]).values()) == Decimal("9.00")
    assert scalar(pg.owner, "select count(*) from catalog.stock_movements where source_id = :d", d=d["id"]) == 0
    s = state(pg, biz, inv["id"]).json()
    assert s["lines"][0]["remaining_taxable"] == "250.00" and s["lines"][0]["remaining_quantity"] == "2"
    assert Decimal(s["remaining_total"]) == Decimal(inv["doc_total"]) + Decimal("59.00")
    assert [(n["kind"], n["doc_number"]) for n in s["notes"]] == [("debit_note", "PR-DN-0001")]
    assert s["debit_reasons"] == {"value_too_low": "Taxable value charged too low",
                                  "more_goods": "More goods sent than invoiced"}
    # A credit note can now take back up to the invoice plus the debit note, never more.
    over = {"reason": "value_too_high", "lines": [{"original_line_id": line, "taxable": "250.01"}]}
    assert note(pg, biz, inv["id"], over).json()["error"]["code"] == "credit_value_too_high"
    full = {"reason": "value_too_high", "lines": [{"original_line_id": line, "taxable": "250.00"}]}
    r = note(pg, biz, inv["id"], full)
    assert r.status_code == 201, r.text
    assert Decimal(r.json()["doc_total"]) == Decimal(inv["doc_total"]) + Decimal("59.00")
    assert state(pg, biz, inv["id"]).json()["remaining_total"] == "0.00"
    with pg.owner.connect() as c:
        audit = c.execute(text("select action, data from platform.audit_log where target_id = :d"), {"d": d["id"]}).one()
        draft = c.execute(text("select l.quantity, l.credit_taxable, l.debit_taxable from sales.draft_lines l"
                               " join sales.documents x on x.draft_id = l.draft_id where x.id = :d"), {"d": d["id"]}).one()
    assert audit.action == "debit_note.issued" and audit.data["original_number"] == inv["doc_number"]
    assert (draft.quantity, draft.credit_taxable, draft.debit_taxable) == (None, None, Decimal("50.00"))


def test_more_goods_sent_are_valued_at_the_invoice_price_and_leave_stock(shop):  # noqa: F811
    pg, biz, _ = shop
    switch(pg, True)
    inv = invoice(pg, biz, qty="4", price="10.00")  # taxable 40.00, so 10.00 a unit
    line = state(pg, biz, inv["id"]).json()["lines"][0]["original_line_id"]
    r = debit(pg, biz, inv["id"], more_goods(line, "1"))
    assert r.status_code == 201, r.text
    assert r.json()["taxable_total"] == "10.00" and r.json()["doc_total"] == "11.80"
    with pg.owner.connect() as c:
        rows = c.execute(text("select kind, quantity, source_type from catalog.stock_movements where source_id = :n"),
                         {"n": r.json()["id"]}).all()
    assert [(x.kind, x.quantity, x.source_type) for x in rows] == [("sale_out", Decimal("-1.000"), "sales_debit_note")]
    detail = pg.client.get(f"/api/v1/b/{biz}/documents/{r.json()['id']}", headers=as_user("alice")).json()
    assert detail["stock_movements"] == 1 and detail["reason"] == "More goods sent than invoiced"
    s = state(pg, biz, inv["id"]).json()["lines"][0]
    assert s["remaining_quantity"] == "5" and s["remaining_taxable"] == "50.00"
    assert note(pg, biz, inv["id"], returned(line, "5")).status_code == 201  # all five can come back


@pytest.mark.parametrize("body, code", [
    ({"reason": "value_too_low", "lines": []}, "lines_required"),
    ({"reason": "value_too_low", "lines": [{"original_line_id": "L", "quantity": "1"}]}, "quantity_or_amount"),
    ({"reason": "more_goods", "lines": [{"original_line_id": "L", "taxable": "1.00"}]}, "quantity_or_amount"),
    ({"reason": "value_too_low", "lines": [{"original_line_id": "L", "taxable": "0"}]}, "amount_invalid"),
    ({"reason": "more_goods", "lines": [{"original_line_id": "L", "quantity": "-1"}]}, "quantity_invalid"),
    ({"reason": "value_too_low", "lines": [{"original_line_id": "x", "taxable": "1.00"}]}, "line_not_on_invoice"),
    ({"reason": "value_too_low", "doc_date": "2099-01-01", "lines": [{"original_line_id": "L", "taxable": "1.00"}]},
     "date_in_future"),
])
def test_bad_debit_notes_are_refused_and_write_nothing(shop, body, code):  # noqa: F811
    pg, biz, _ = shop
    switch(pg, True)
    inv = invoice(pg, biz)
    line = state(pg, biz, inv["id"]).json()["lines"][0]["original_line_id"]
    body = {**body, "lines": [{**ln, "original_line_id": line if ln["original_line_id"] == "L" else ln["original_line_id"]}
                              for ln in body["lines"]]}
    r = debit(pg, biz, inv["id"], body)
    assert r.status_code == 422 and r.json()["error"]["code"] == code, r.text
    assert scalar(pg.owner, "select count(*) from sales.documents where kind = 'debit_note'") == 0


def test_a_credit_note_reason_is_not_a_debit_reason(shop):  # noqa: F811
    pg, biz, _ = shop
    switch(pg, True)
    inv = invoice(pg, biz)
    line = state(pg, biz, inv["id"]).json()["lines"][0]["original_line_id"]
    r = debit(pg, biz, inv["id"], {"reason": "goods_returned", "lines": [{"original_line_id": line, "quantity": "1"}]})
    assert r.status_code == 422  # refused by the request model


def test_the_same_key_gives_one_debit_note_and_roles_and_the_switch_apply(shop):  # noqa: F811
    pg, biz, other = shop
    switch(pg, True)
    inv = invoice(pg, biz)
    line = state(pg, biz, inv["id"]).json()["lines"][0]["original_line_id"]
    first = debit(pg, biz, inv["id"], by_value(line, "1.00"), key="dn-1")
    again = debit(pg, biz, inv["id"], by_value(line, "1.00"), key="dn-1")
    assert first.status_code == again.status_code == 201 and first.json() == again.json()
    assert debit(pg, biz, inv["id"], by_value(line, "1.00"), sub="cathy").status_code == 404  # the CA reads only
    assert debit(pg, other, inv["id"], by_value(line, "1.00"), sub="bob").status_code == 404
    assert debit(pg, biz, first.json()["id"], by_value(line, "1.00")).status_code == 404  # a note takes no note
    assert debit(pg, biz, inv["id"], by_value(line, "1.00"), sub="bill").status_code == 201  # billing
    switch(pg, False)
    assert debit(pg, biz, inv["id"], by_value(line, "1.00")).status_code == 404
    assert scalar(pg.owner, "select count(*) from sales.documents where kind = 'debit_note'") == 2


def test_a_debit_note_blocks_cancel_and_a_cancelled_invoice_takes_none(shop):  # noqa: F811
    pg, biz, _ = shop
    switch(pg, True)
    inv = invoice(pg, biz)
    line = state(pg, biz, inv["id"]).json()["lines"][0]["original_line_id"]
    made = debit(pg, biz, inv["id"], by_value(line, "1.00")).json()
    r = cancel(pg, biz, inv["id"], MISTAKE)
    assert r.status_code == 409 and r.json()["error"]["code"] == "has_credit_note"
    assert f"Debit note {made['doc_number']}" in r.json()["error"]["message"]
    gone = invoice(pg, biz)
    assert cancel(pg, biz, gone["id"], MISTAKE).status_code == 200
    gone_line = state(pg, biz, gone["id"]).json()["lines"][0]["original_line_id"]
    r = debit(pg, biz, gone["id"], by_value(gone_line, "1.00"))
    assert r.status_code == 422 and r.json()["error"]["code"] == "invoice_cancelled"


def test_a_practice_debit_note_never_reaches_filing_and_its_pdf_says_debit_note(shop):  # noqa: F811
    from app.modules.sales import document_pdf

    pg, biz, _ = shop
    switch(pg, True)
    inv = invoice(pg, biz)
    line = state(pg, biz, inv["id"]).json()["lines"][0]["original_line_id"]
    made = debit(pg, biz, inv["id"], by_value(line, "1.00")).json()
    assert scalar(pg.owner, "select count(*) from sales.v_filing_lines") == 0
    with pg.owner.connect() as c:
        body = document_pdf.build(c, biz, uuid.UUID(made["id"]))
    assert body["note"] == {"kind": "debit_note", "original_number": inv["doc_number"],
                            "original_date": inv["doc_date"], "reason": "Taxable value charged too low"}
    assert body["copies"] == ["Original for Recipient", "Duplicate for Supplier"] and body["number"] == "PR-DN-0001"
    pages = rendered(body)
    assert len(pages) == 2 and "PRACTICE DEBIT NOTE" in pages[0] and "Amount payable" in pages[0]


@pytest.mark.parametrize("body", [
    {"reason": "goods_returned", "stock_treatment": "restock", "lines": [{"original_line_id": "L", "quantity": "1"}]},
    {"reason": "value_too_high", "lines": [{"original_line_id": "L", "taxable": "0.10"}]},
])
def test_a_credit_note_pdf_renders_with_no_unit_price(shop, body):  # noqa: F811
    """#466: a note line has no unit price (and one by amount no quantity); the renderer drew neither and refused."""
    from app.modules.sales import document_pdf

    pg, biz, _ = shop
    switch(pg, True)
    inv = invoice(pg, biz)
    line = state(pg, biz, inv["id"]).json()["lines"][0]["original_line_id"]
    body = {**body, "lines": [{**ln, "original_line_id": line} for ln in body["lines"]]}
    made = note(pg, biz, inv["id"], body)
    assert made.status_code == 201, made.text
    with pg.owner.connect() as c:
        pdf = document_pdf.build(c, biz, uuid.UUID(made.json()["id"]))
    assert pdf["lines"][0]["unit_price"] == "—"
    pages = rendered(pdf)
    assert len(pages) == 2 and "PRACTICE CREDIT NOTE" in pages[0] and "Credit amount" in pages[0]


def test_a_live_debit_note_takes_a_live_number_its_return_and_is_a_supply_line(live):  # noqa: F811
    pg, biz = live
    flip_live(pg, True)
    r = fin(pg, biz, ready_draft(pg, biz))
    assert r.status_code == 200, r.text
    inv = r.json()
    line = state(pg, biz, inv["id"]).json()["lines"][0]["original_line_id"]
    r = debit(pg, biz, inv["id"], by_value(line, "10.00"))
    assert r.status_code == 201, r.text
    n = r.json()
    assert not n["is_practice"] and n["doc_number"] == "DN000001"  # default DN settings, the FY scope before 26-11
    with pg.owner.connect() as c:
        period = c.execute(text("select i.return_period from sales.documents d join filing.return_instances i"
                                " on i.id = d.return_instance_id where d.id = :d"), {"d": n["id"]}).scalar()
        lines = c.execute(text("select source_kind, doc_kind, original_doc_number, taxable_value from"
                               " filing.v_supply_lines where source_id = :d"), {"d": n["id"]}).all()
    assert period == "2026-11"
    assert [tuple(x) for x in lines] == [("own_debit_note", "debit_note", inv["doc_number"], Decimal("10.00"))]

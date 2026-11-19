"""R3-M3: the GSTR-1 build over our own finalized invoices and credit notes, on PostgreSQL through the real view
(sales.v_filing_lines -> filing.v_supply_lines) and build_return. Live documents are seeded as the database owner with the
return assignment already set (live finalize is R3-M5; numbering stays off, D-010), so these are live-mode fixtures only.
Practice documents must never reach a return. Made-up data. Skipped unless PG_ADMIN_URL is set."""

import uuid
from types import SimpleNamespace
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.filing.interface import build_return, ensure_instances

from .conftest import PG_ADMIN_URL, ctx, new_business, user_id
from .test_periods_postgres import choose

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")
GSTIN = "19AAPFU0939F1ZS"
BUYER = "29AAACX3333C1ZL"


def seed(pg, sql, **p):
    with pg.owner.connect() as c:
        c.execute(text("set session_replication_role = replica"))
        c.execute(text(sql), p)
        c.execute(text("set session_replication_role = default"))


def instances(pg, biz, sub="alice"):
    with pg.app_rw.begin() as c:
        ctx(c, user_id(pg.owner, sub), biz)
        return {i.form: i for i in ensure_instances(Session(bind=c), GSTIN, date(2026, 11, 1)) if i.period == "2026-11"}


def doc(
    pg,
    biz,
    inst,
    number,
    on,
    *,
    kind="invoice",
    practice=False,
    cls="B2B",
    buyer=BUYER,
    pos="29",
    inter=True,
    taxable="1000.00",
    tax="180.00",
    original=None,
    assign=True,
):
    d, line = uuid.uuid4(), uuid.uuid4()
    igst, half = (tax, "0") if inter else ("0", str(Decimal(tax) / 2))
    seed(
        pg,
        "insert into sales.documents (id, business_id, draft_id, kind, is_practice, series_id, doc_number, doc_date, fy,"
        " gstin, supplier_state_code, counterparty_gstin, counterparty_name, pos_state_code, is_inter_state,"
        " supply_class, return_instance_id, return_period, original_document_id, gross_total, line_discount_total,"
        " invoice_discount, charges_total, taxable_total, cgst_total, sgst_total, utgst, igst_total, doc_total,"
        " amount_in_words, print, rounding_mode, method_version, finalized_by) values (:d, :b, :dr, :k, :p, :sr, :n,"
        " :on, '2026-27', :g, '19', :bg, :bn, :pos, :inter, :cls, :ri, :rp, :orig, :t, 0, 0, 0, :t, :h, :h, false,"
        " :i, :tot, 'x', '{}', 'none', 'v1', :u)",
        d=d,
        b=biz,
        dr=uuid.uuid4(),
        k=kind,
        p=practice,
        sr=uuid.uuid4(),
        n=number,
        on=on,
        g=GSTIN,
        bg=buyer,
        bn="Buyer" if buyer else None,
        pos=pos,
        inter=inter,
        cls=cls,
        ri=inst.id if assign else None,
        rp="2026-11" if assign else None,
        orig=original,
        t=Decimal(taxable),
        h=Decimal(half),
        i=Decimal(igst),
        tot=Decimal(taxable) + Decimal(tax),
        u=uuid.uuid4(),
    )
    seed(
        pg,
        "insert into sales.document_lines (id, business_id, document_id, line_no, name, hsn, uqc, quantity, unit_price,"
        " gross, line_discount, discount_share, charge_share, taxable, rate, rate_confirmed)"
        " values (:l, :b, :d, 1, 'Tee', '610910', 'PCS', 1, :t, :t, 0, 0, 0, :t, 18, true)",
        l=line,
        b=biz,
        d=d,
        t=Decimal(taxable),
    )
    for comp, amt in (("IGST", igst), ("CGST", half), ("SGST", half)):
        if Decimal(amt):
            seed(
                pg,
                "insert into sales.document_line_taxes (line_id, business_id, component, rate, amount)"
                " values (:l, :b, :c, 18, :a)",
                l=line,
                b=biz,
                c=comp,
                a=Decimal(amt),
            )
    return d


def built(pg, biz, inst, sub="alice"):
    with pg.app_rw.begin() as c:
        ctx(c, user_id(pg.owner, sub), biz)
        return build_return(Session(bind=c), inst)


@pytest.fixture()
def shop(pg):
    biz = new_business(pg, "alice")
    choose(pg, biz, "monthly")
    return pg, biz, instances(pg, biz)["GSTR1"]


def test_live_invoices_and_a_credit_note_build_into_the_right_sections_and_reconcile(shop):
    pg, biz, inst = shop
    inv = doc(pg, biz, inst, "INV-1", date(2026, 11, 3))
    doc(pg, biz, inst, "INV-2", date(2026, 11, 4), cls="B2CS", buyer=None, pos="19", inter=False)
    doc(
        pg,
        biz,
        inst,
        "CN-1",
        date(2026, 11, 9),
        kind="credit_note",
        cls="CDNR",
        taxable="200.00",
        tax="36.00",
        original=inv,
    )
    b = built(pg, biz, inst)
    assert b.draft and [r.invoice_number for r in b.sections.b2b] == ["INV-1"]
    assert [r.note_number for r in b.sections.cdnr] == ["CN-1"]
    assert b.sections.b2cs and b.line_items == b.sections.line_items > 0
    assert b.liability.taxable_value == Decimal("1800.00")  # 1000 + 1000 - 200
    assert b.liability.igst == Decimal("144.00") and b.gap.is_zero()
    assert all(m.split("|")[1] in ("own_invoice", "own_credit_note") for m in b.members)


def test_a_practice_document_is_never_in_a_return_even_if_it_carries_an_instance(shop):
    pg, biz, inst = shop
    doc(pg, biz, inst, "INV-1", date(2026, 11, 3))
    before = built(pg, biz, inst)
    doc(pg, biz, inst, "PRACTICE-1", date(2026, 11, 5), practice=True, taxable="99999.00", tax="0.00")
    after = built(pg, biz, inst)
    assert after.fingerprint == before.fingerprint and after.members == before.members


def test_a_document_not_yet_assigned_to_a_return_is_not_in_one(shop):
    pg, biz, inst = shop
    doc(pg, biz, inst, "INV-1", date(2026, 11, 3), assign=False)
    assert built(pg, biz, inst).line_items == 0


def test_the_fingerprint_changes_when_a_live_document_is_added_and_not_otherwise(shop):
    pg, biz, inst = shop
    doc(pg, biz, inst, "INV-1", date(2026, 11, 3))
    a, same = built(pg, biz, inst), built(pg, biz, inst)
    assert a.fingerprint == same.fingerprint
    doc(pg, biz, inst, "INV-2", date(2026, 11, 4))
    assert built(pg, biz, inst).fingerprint != a.fingerprint


def test_each_return_gets_only_its_own_documents(shop):
    pg, biz, inst = shop
    other = instances(pg, biz)  # the November GSTR-1 is `inst`; the December one is a different return
    with pg.app_rw.begin() as c:
        ctx(c, user_id(pg.owner, "alice"), biz)
        dec = [
            i
            for i in ensure_instances(Session(bind=c), GSTIN, date(2026, 12, 1))
            if i.form == "GSTR1" and i.period == "2026-12"
        ][0]
    doc(pg, biz, inst, "INV-NOV", date(2026, 11, 3))
    doc(pg, biz, dec, "INV-DEC", date(2026, 12, 3))
    assert [m.split("|")[0] for m in built(pg, biz, inst).members] == ["INV-NOV"]
    assert [m.split("|")[0] for m in built(pg, biz, dec).members] == ["INV-DEC"]
    assert other["GSTR1"].id == inst.id


def test_another_business_never_sees_the_documents(shop):
    pg, biz, inst = shop
    doc(pg, biz, inst, "INV-1", date(2026, 11, 3))
    bob = new_business(pg, "bob")
    with pg.app_rw.begin() as c:
        ctx(c, user_id(pg.owner, "bob"), bob)
        n = c.execute(text("select count(*) from filing.v_supply_lines")).scalar()
    assert n == 0


# -- The whole path, nothing staged: documents -> build -> checks -> file -> mark filed ---------------------------


@pytest.fixture()
def real(pg, tmp_path):
    from pathlib import Path

    from app import api as app_api
    from app.modules.filing import entitlement
    from migrator.refdata import load
    from platform_common.clock import IST, FrozenClock, get_clock
    from platform_common.queue import FakeQueue, set_queue
    from platform_common.storage import LocalObjectStore, set_store

    from .conftest import as_user as _as_user  # noqa: F401

    app_api.app.dependency_overrides[get_clock] = lambda: FrozenClock(datetime(2026, 11, 15, 12, 0, tzinfo=IST))
    with pg.owner.connect() as c:
        load(c.connection.driver_connection, Path(__file__).resolve().parents[6] / "refdata")
    queue = FakeQueue()
    set_queue(queue)
    set_store(LocalObjectStore(tmp_path))
    biz = new_business(pg, "alice")
    choose(pg, biz, "monthly")
    try:
        yield pg, biz, queue
    finally:
        set_queue(None)
        set_store(None)
        entitlement.set_check(None)


def test_a_live_month_is_exported_and_locked_without_staging_anything(real):
    from platform_common import jobs

    from .conftest import as_user, scalar

    pg, biz, queue = real
    gstin = scalar(pg.owner, "select gstin from business.profiles where business_id = :b", b=biz)
    rows = pg.client.get(f"/api/v1/b/{biz}/returns", params={"fy": "2026-27"}, headers=as_user("alice")).json()[
        "returns"
    ]
    inst_id = next(x["instance_id"] for x in rows if x["form"] == "GSTR1" and x["period"] == "2026-10")
    inst = SimpleNamespace(id=uuid.UUID(inst_id))
    global GSTIN
    keep, GSTIN = GSTIN, gstin
    try:
        doc(pg, biz, inst, "INV-1", date(2026, 10, 3))
        doc(pg, biz, inst, "PRACTICE-1", date(2026, 10, 4), practice=True)
    finally:
        GSTIN = keep
    ok = pg.client.post(
        f"/api/v1/b/{biz}/returns/{inst_id}/check-acceptances",
        headers=as_user("alice"),
        json={"check_code": "C-16", "note": "CA rules still open; test"},
    )
    assert ok.status_code == 200, ok.text
    for item in ("purchases_uploaded", "invoices_in_portal"):  # a business with own invoices files through the gate (D-095)
        gate = pg.client.put(
            f"/api/v1/b/{biz}/period-gate",
            headers=as_user("alice"),
            json={"kind": "month", "start": "2026-10-01", "item": item, "confirmed": True},
        )
        assert gate.status_code == 200, gate.text
    t13 = pg.client.get(f"/api/v1/b/{biz}/returns/{inst_id}/table13", headers=as_user("alice")).json()
    assert t13["required"] and not t13["confirmed"]  # Table 13 comes from the live invoice only: the practice one is nowhere
    assert [(x["from_no"], x["to_no"], x["total_issued"], x["source"]) for x in t13["rows"]] == [("INV-1", "INV-1", 1, "own_live")]
    refused = pg.client.post(f"/api/v1/b/{biz}/returns/{inst_id}/exports", headers=as_user("alice"))
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "not_ready"  # C-08 blocks until it is confirmed
    put = pg.client.put(f"/api/v1/b/{biz}/returns/{inst_id}/table13", headers=as_user("alice"),
                        json={"rows": [{k: x[k] for k in ("nature", "from_no", "to_no", "total_issued", "cancelled", "counted")}
                                       for x in t13["rows"]]})
    assert put.status_code == 200 and put.json()["confirmed"], put.text
    r = pg.client.post(f"/api/v1/b/{biz}/returns/{inst_id}/exports", headers=as_user("alice"))
    assert r.status_code == 202, r.text
    queue.drain(jobs.handle_message)
    s = pg.client.get(
        f"/api/v1/b/{biz}/returns/{inst_id}/exports/{r.json()['job_id']}", headers=as_user("alice")
    ).json()
    assert s["status"] == "ready" and len(s["files"]) == 1, s
    kinds = [r[0] for r in pg.owner.connect().execute(text("select source_kind from filing.snapshot_members"))]
    assert kinds == ["own_invoice"]  # the live invoice only; the practice document is nowhere
    snap_docs = pg.owner.connect().execute(
        text("select nature, from_no, to_no, total_count, cancelled_count from filing.snapshot_lines where section = 'docs'")
    ).all()
    assert [tuple(x) for x in snap_docs] == [(1, "INV-1", "INV-1", 1, 0)]
    done = pg.client.post(
        f"/api/v1/b/{biz}/returns/{inst_id}/filed",
        headers=as_user("alice"),
        json={"filed_on": "2026-11-10", "arn": "AA1910260000001"},
    )
    assert done.status_code == 200 and done.json()["status"] == "filed_locked" and done.json()["has_file"], done.text

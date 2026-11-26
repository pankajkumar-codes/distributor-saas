"""A quarterly (QRMP) filer's live documents in its returns (#482, #483): a B2B invoice and a credit note dated in an IFF
month are assigned to that month's IFF. The IFF lists them with no false "something is wrong on our side" blocks, and
the quarterly GSTR-1 carries them in its B2B and CDNR tables until the IFF is marked filed, warning that it does (C-19).

Made-up data. Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import uuid
from datetime import datetime

import pytest
from sqlalchemy import text

from .conftest import PG_ADMIN_URL, as_user, user_id
from .test_credit_notes_postgres import note, state
from .test_finalize_live_postgres import flip_live
from .test_finalize_postgres import fin, ready_draft, shop, switch  # noqa: F401

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


def _clock(y, m, d):
    from app import api as app_api
    from platform_common.clock import IST, FrozenClock, get_clock

    app_api.app.dependency_overrides[get_clock] = lambda: FrozenClock(datetime(y, m, d, 12, 0, tzinfo=IST))


@pytest.fixture()
def qrmp(shop):  # noqa: F811
    pg, biz, _ = shop
    _clock(2026, 11, 15)
    switch(pg, True)
    flip_live(pg, True)
    r = pg.client.post(f"/api/v1/b/{biz}/filing-profile/frequency",
                       json={"frequency": "quarterly", "effective_from": "2026-10-01"},
                       headers={**as_user("alice"), "Idempotency-Key": uuid.uuid4().hex})  # fmt: skip
    assert r.status_code in (200, 201), r.text
    with pg.owner.connect() as c:
        for kind, prefix in (("invoice", "INV"), ("credit_note", "CN")):
            c.execute(text("insert into business.series_settings (business_id, kind, prefix, width, practice_mode, updated_by)"
                           " values (:b, :k, :p, 6, false, :u)"),
                      {"b": biz, "k": kind, "p": prefix, "u": user_id(pg.owner, "alice")})  # fmt: skip
    yield pg, biz
    flip_live(pg, False)


def get(pg, biz, path):
    r = pg.client.get(f"/api/v1/b/{biz}{path}", headers=as_user("alice"))
    assert r.status_code == 200, r.text
    return r.json()


def instances(pg, biz):
    rows = get(pg, biz, "/returns?fy=2026-27")["returns"]
    return {(x["form"], x["period"]): x["instance_id"] for x in rows}


def numbers(pg, biz, inst, section, key):
    return sorted(r[key] for r in get(pg, biz, f"/returns/{inst}/sections/{section}")["rows"])


def codes(ret):
    return sorted({f["code"] for f in ret["findings"]})


def test_an_iff_month_is_usable_and_the_quarter_carries_it_until_the_iff_is_filed(qrmp):
    pg, biz = qrmp
    r = fin(pg, biz, ready_draft(pg, biz))  # a registered buyer: B2B, dated 15 Nov, so November's IFF
    assert r.status_code == 200, r.text
    inv = r.json()
    assert inv["supply_class"] == "B2B" and not inv["is_practice"]
    line = state(pg, biz, inv["id"]).json()["lines"][0]["original_line_id"]
    cn = note(pg, biz, inv["id"], {"reason": "goods_returned", "stock_treatment": "restock",
                                   "lines": [{"original_line_id": line, "quantity": "1"}]})  # fmt: skip
    assert cn.status_code == 201, cn.text
    cn = cn.json()
    ids = instances(pg, biz)
    iff, quarter = ids[("IFF", "2026-11")], ids[("GSTR1", "2026-Q3")]

    # #482: the IFF has its B2B invoice and note, no Table 12 to reconcile, and no "something is wrong on our side" block.
    ret = get(pg, biz, f"/returns/{iff}")
    assert "C-07" not in codes(ret) and "C-09" not in codes(ret)
    assert all(v in ("0", "0.00") for v in ret["totals"]["gap"].values())
    assert [f["level"] for f in ret["findings"] if f["level"] == "block"] == []
    assert numbers(pg, biz, iff, "b2b", "invoice_number") == [inv["doc_number"]]
    assert numbers(pg, biz, iff, "cdnr", "note_number") == [cn["doc_number"]]

    # #483: while the IFF is not marked filed, the quarter carries its lines in Tables 4A and 9B, and says so (C-19).
    ret = get(pg, biz, f"/returns/{quarter}")
    assert numbers(pg, biz, quarter, "b2b", "invoice_number") == [inv["doc_number"]]
    assert numbers(pg, biz, quarter, "cdnr", "note_number") == [cn["doc_number"]]
    assert all(v in ("0", "0.00") for v in ret["totals"]["gap"].values())
    [c19] = [f for f in ret["findings"] if f["code"] == "C-19"]
    assert c19["level"] == "warn" and "Nov 2026" in c19["message"]
    assert sorted(c19["source_refs"]) == sorted([inv["doc_number"], cn["doc_number"]])
    liability = ret["totals"]["liability"]

    # Once the IFF is marked filed, its lines leave the quarter's tables but still count in its liability and Table 12.
    _clock(2026, 12, 10)
    r = pg.client.post(f"/api/v1/b/{biz}/returns/{iff}/filed", headers=as_user("alice"),
                       json={"filed_on": "2026-12-10", "arn": "AA191226000001X",
                             "accept_changed": {"reason": "filed on the portal from my own records"}})  # fmt: skip
    assert r.status_code == 200, r.text
    ret = get(pg, biz, f"/returns/{quarter}")
    assert numbers(pg, biz, quarter, "b2b", "invoice_number") == []
    assert numbers(pg, biz, quarter, "cdnr", "note_number") == []
    assert "C-19" not in codes(ret)
    assert ret["totals"]["liability"] == liability
    assert all(v in ("0", "0.00") for v in ret["totals"]["gap"].values())

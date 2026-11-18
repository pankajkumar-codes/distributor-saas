"""R3-M5: live finalize and return assignment, behind the second switch `sales.finalize.live`. Live numbers stay off until the
CA confirms the numbering scope (D-010, D-044), so these tests flip both switches as test setup only. Made-up data. Skipped
unless PG_ADMIN_URL points at a disposable server."""

import uuid
from datetime import datetime

import pytest
from sqlalchemy import text

from .conftest import PG_ADMIN_URL, as_user, ctx, user_id
from .test_finalize_postgres import counts, fin, ready_draft, shop, switch  # noqa: F401

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


def flip_live(pg, on):
    with pg.owner.connect() as c:
        c.execute(
            text("update refdata.values set value = :v where key = 'sales.finalize.live'"), {"v": "true" if on else "false"}
        )
        c.execute(
            text(
                "insert into refdata.loads (id, git_sha, files, rows_inserted, rows_closed, rows_updated)"
                " values (:i, 'test', '{}', 0, 0, 1)"
            ),
            {"i": uuid.uuid4()},
        )


@pytest.fixture()
def live(shop):  # noqa: F811
    from app import api as app_api
    from platform_common.clock import IST, FrozenClock, get_clock

    pg, biz, _ = shop
    app_api.app.dependency_overrides[get_clock] = lambda: FrozenClock(datetime(2026, 11, 15, 12, 0, tzinfo=IST))
    switch(pg, True)
    r = pg.client.post(
        f"/api/v1/b/{biz}/filing-profile/frequency",
        json={"frequency": "monthly", "effective_from": "2026-10-01"},
        headers={**as_user("alice"), "Idempotency-Key": uuid.uuid4().hex},
    )
    assert r.status_code in (200, 201), r.text
    with pg.owner.connect() as c:
        c.execute(
            text(
                "insert into business.series_settings (business_id, kind, prefix, width, practice_mode, updated_by)"
                " values (:b, 'invoice', 'INV-', 4, false, :u)"
            ),
            {"b": biz, "u": user_id(pg.owner, "alice")},
        )
    return pg, biz


def test_a_live_finalize_is_refused_while_the_live_switch_is_off(live):
    pg, biz = live
    r = fin(pg, biz, ready_draft(pg, biz))
    assert r.status_code == 422 and r.json()["error"]["code"] == "live_numbering_unavailable"
    assert counts(pg) == (0, 0, 0, 0)


def test_a_live_invoice_is_assigned_once_to_the_return_covering_its_date_and_reaches_filing(live):
    pg, biz = live
    flip_live(pg, True)
    r = fin(pg, biz, ready_draft(pg, biz))
    assert r.status_code == 200, r.text
    with pg.owner.connect() as c:
        doc = c.execute(
            text(
                "select d.is_practice, d.doc_number, d.return_period, i.form, i.return_period as ip, i.status"
                " from sales.documents d join filing.return_instances i on i.id = d.return_instance_id"
            )
        ).one()
    assert not doc.is_practice and doc.doc_number == "INV-0001"
    assert (doc.return_period, doc.ip, doc.form, doc.status) == ("2026-11", "2026-11", "GSTR1", "open")
    with pg.app_rw.connect() as c, c.begin():
        ctx(c, user_id(pg.owner, "alice"), tenant=biz)
        assert c.execute(text("select count(*) from filing.v_supply_lines where return_instance_id is not null")).scalar() == 1
    data = pg.owner.connect().execute(text("select data from platform.audit_log where action = 'document.finalized'")).scalar()
    assert data["practice"] is False and data["return_period"] == "2026-11" and data["form"] == "GSTR1"


def test_an_invoice_for_a_filed_return_is_refused_and_takes_no_number(live):
    pg, biz = live
    flip_live(pg, True)
    d = ready_draft(pg, biz)
    assert fin(pg, biz, ready_draft(pg, biz)).status_code == 200  # makes sure the November return exists
    before = counts(pg)
    with pg.owner.connect() as c:
        c.execute(text("set session_replication_role = replica"))
        c.execute(text("update filing.return_instances set status = 'filed_locked' where form = 'GSTR1' and return_period = '2026-11'"))
        c.execute(text("set session_replication_role = default"))
    r = fin(pg, biz, d)
    assert r.status_code == 409 and r.json()["error"]["code"] == "period_locked", r.text
    assert counts(pg) == before


def test_a_practice_business_is_unchanged_by_the_live_switch(live):
    pg, biz = live
    flip_live(pg, True)
    with pg.owner.connect() as c:
        c.execute(text("update business.series_settings set practice_mode = true"))
    assert fin(pg, biz, ready_draft(pg, biz)).status_code == 200
    with pg.owner.connect() as c:
        assert c.execute(text("select is_practice, return_instance_id is null from sales.documents")).one() == (True, True)

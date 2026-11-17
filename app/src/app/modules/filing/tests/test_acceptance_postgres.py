"""Accepting findings and the export gate (R1-M8 S1)."""

import uuid
from datetime import datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from .conftest import PG_ADMIN_URL, as_user, new_business, scalar, seed_member
from .test_periods_postgres import choose, lock

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


@pytest.fixture()
def ret(pg):
    from app import api as app_api
    from platform_common.clock import IST, FrozenClock, get_clock

    app_api.app.dependency_overrides[get_clock] = lambda: FrozenClock(datetime(2026, 11, 15, 12, 0, tzinfo=IST))
    b = new_business(pg, "alice")
    choose(pg, b, "monthly")
    rows = pg.client.get(f"/api/v1/b/{b}/returns", params={"fy": "2026-27"}, headers=as_user("alice")).json()["returns"]
    inst = next(x["instance_id"] for x in rows if x["form"] == "GSTR1" and x["period"] == "2026-10")
    return pg, b, inst


def detail(pg, b, inst, sub="alice"):
    return pg.client.get(f"/api/v1/b/{b}/returns/{inst}", headers=as_user(sub))


def accept(pg, b, inst, body, sub="alice"):
    return pg.client.post(f"/api/v1/b/{b}/returns/{inst}/check-acceptances", json=body, headers=as_user(sub))


def c16(pg, b, inst):
    return next(x for x in detail(pg, b, inst).json()["findings"] if x["code"] == "C-16")


def test_a_standing_warning_gates_export_until_accepted_then_is_marked(ret):
    pg, b, inst = ret
    d = detail(pg, b, inst).json()
    assert d["export"]["ready"] is False and d["export"]["to_accept"] >= 1
    f = c16(pg, b, inst)
    assert f["accepted"] is False
    r = accept(pg, b, inst, {"check_code": "C-16", "subject_fp": f["subject_fp"], "note": "CA to confirm later"})
    assert r.status_code == 200 and r.json() == {"check_code": "C-16", "accepted": 1}
    d = detail(pg, b, inst).json()
    assert c16(pg, b, inst)["accepted"] is True
    assert next(g for g in d["finding_groups"] if g["code"] == "C-16")["accepted"] == 1
    assert (
        accept(pg, b, inst, {"check_code": "C-16", "subject_fp": f["subject_fp"], "note": "again"}).json()["accepted"]
        == 0
    )  # idempotent
    assert scalar(pg.owner, "select count(*) from filing.check_acceptances") == 1
    assert scalar(pg.owner, "select count(*) from platform.audit_log where action = 'filing.accept_warning'") == 1


def test_accepting_by_code_alone_covers_the_current_warnings(ret):
    pg, b, inst = ret
    r = accept(pg, b, inst, {"check_code": "C-16", "note": "ok"})
    assert r.json()["accepted"] == 1
    assert c16(pg, b, inst)["accepted"] is True


def test_a_stale_subject_a_missing_code_and_bad_input_are_refused(ret):
    pg, b, inst = ret
    assert accept(pg, b, inst, {"check_code": "C-16", "subject_fp": "0" * 64, "note": "x"}).status_code == 409
    assert accept(pg, b, inst, {"check_code": "C-99", "note": "x"}).status_code == 409
    assert accept(pg, b, inst, {"check_code": "C-16"}).status_code == 422  # a note is required
    assert accept(pg, b, inst, {"check_code": "C-16", "note": "  "}).status_code == 422
    assert accept(pg, b, inst, {"check_code": "bad", "note": "x"}).status_code == 422
    assert scalar(pg.owner, "select count(*) from filing.check_acceptances") == 0


def test_an_information_finding_is_not_acceptable(ret):
    pg, b, inst = ret
    # no information finding exists on an empty build; the pure gate covers it. Here: an unknown code is a conflict.
    assert accept(pg, b, inst, {"check_code": "A-04", "note": "x"}).status_code == 409


def test_a_locked_return_takes_no_acceptance(ret):
    pg, b, inst = ret
    lock(pg, b, inst)
    assert accept(pg, b, inst, {"check_code": "C-16", "note": "ok"}).status_code == 409


def test_who_may_accept_and_which_business(pg, ret):
    pg, b, inst = ret
    seed_member(pg, b, "bill", "billing")
    seed_member(pg, b, "carol", "ca")
    assert accept(pg, b, inst, {"check_code": "C-16", "note": "ok"}, "bill").status_code in (403, 404)
    assert accept(pg, b, inst, {"check_code": "C-16", "note": "ok"}, "carol").status_code == 200
    other = new_business(pg, "mallory")
    assert accept(pg, other, inst, {"check_code": "C-16", "note": "ok"}, "mallory").status_code == 404
    assert accept(pg, b, inst, {"check_code": "C-16", "note": "ok"}, "mallory").status_code in (403, 404)


def test_acceptances_cannot_be_changed_or_deleted(ret):
    pg, b, inst = ret
    accept(pg, b, inst, {"check_code": "C-16", "note": "ok"})
    for sql in ("update filing.check_acceptances set note = 'x'", "delete from filing.check_acceptances"):
        with pytest.raises(DBAPIError), pg.owner.connect() as c:
            c.execute(text(sql))
    assert uuid.UUID(str(scalar(pg.owner, "select business_id from filing.check_acceptances"))) == b

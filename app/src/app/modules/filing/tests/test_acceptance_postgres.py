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


def test_an_unknown_code_is_a_conflict(ret):
    pg, b, inst = ret
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


def test_a_missing_note_cannot_be_stored_even_past_the_api(ret):
    pg, b, inst = ret
    for note in ("null", "'  '"):
        with pytest.raises(DBAPIError, match="note"), pg.owner.connect() as c:
            c.execute(
                text(
                    "insert into filing.check_acceptances (id, business_id, instance_id, check_code, subject_fp, note, accepted_by)"
                    f" values (:e, :b, :i, 'C-16', repeat('a', 64), {note}, gen_random_uuid())"
                ),
                {"e": uuid.uuid4(), "b": b, "i": inst},
            )


def test_a_support_user_under_a_grant_is_refused_cleanly(ret):
    pg, b, inst = ret
    from .test_returns_api_postgres import scalar_user

    with pg.owner.connect() as c:
        uid = c.execute(text("select identity.dev_ensure_user('sam-support')")).scalar()
        c.execute(
            text("update identity.users set is_support = true, totp_enabled_at = now() where id = :u"), {"u": uid}
        )
        c.execute(
            text(
                "insert into identity.support_grants (id, business_id, granted_by, starts_at, expires_at)"
                " values (:g, :b, :u, now() - interval '1 hour', now() + interval '23 hours')"
            ),
            {"g": uuid.uuid4(), "b": b, "u": scalar_user(pg)},
        )
    r = accept(pg, b, inst, {"check_code": "C-16", "note": "support"}, "sam-support")
    assert r.status_code in (403, 404, 409), r.text
    assert scalar(pg.owner, "select count(*) from filing.check_acceptances") == 0


# -- the route refuses what cannot be accepted (findings staged, so the route is tested end to end) ---------------


def stage(monkeypatch, *findings):
    from app.modules.filing import api

    monkeypatch.setattr(api, "run_checks", lambda tx, b: list(findings))


def finding(code, level, fp="a" * 64):
    from app.modules.filing.checks import Finding

    return Finding(code, level, "m", (), fp)


def error_code(r):
    return r.json()["error"]["code"]


def test_a_block_is_refused_with_cannot_accept_and_nothing_is_recorded(ret, monkeypatch):
    pg, b, inst = ret
    stage(monkeypatch, finding("C-02", "block"))
    for body in ({"check_code": "C-02", "note": "x"}, {"check_code": "C-02", "subject_fp": "a" * 64, "note": "x"}):
        r = accept(pg, b, inst, body)
        assert r.status_code == 422 and error_code(r) == "cannot_accept"
    assert scalar(pg.owner, "select count(*) from filing.check_acceptances") == 0


def test_an_information_finding_is_refused_with_cannot_accept(ret, monkeypatch):
    pg, b, inst = ret
    stage(monkeypatch, finding("A-04", "info"))
    r = accept(pg, b, inst, {"check_code": "A-04", "note": "x"})
    assert r.status_code == 422 and error_code(r) == "cannot_accept"
    assert r.json()["error"]["message"] == "This does not need accepting."
    assert scalar(pg.owner, "select count(*) from filing.check_acceptances") == 0


def test_accepting_by_code_fails_whole_when_one_of_the_items_is_a_block(ret, monkeypatch):
    pg, b, inst = ret
    stage(monkeypatch, finding("A-01", "warn", "a" * 64), finding("A-01", "block", "b" * 64))
    r = accept(pg, b, inst, {"check_code": "A-01", "note": "x"})
    assert r.status_code == 422 and error_code(r) == "cannot_accept"
    assert scalar(pg.owner, "select count(*) from filing.check_acceptances") == 0
    # the warning alone, named by its subject, can be accepted
    assert accept(pg, b, inst, {"check_code": "A-01", "subject_fp": "a" * 64, "note": "x"}).status_code == 200


# -- the table itself: tenant isolation under the app role ------------------------------------------------------


def insert_sql(business):
    return (
        "insert into filing.check_acceptances (id, business_id, instance_id, check_code, subject_fp, note, accepted_by)"
        f" values (gen_random_uuid(), '{business}', :i, 'C-16', repeat('a', 64), 'n', gen_random_uuid())"
    )


def test_the_table_refuses_an_instance_of_another_business(ret, pg):
    pg, a, inst = ret
    other = new_business(pg, "mallory")
    with pytest.raises(DBAPIError, match="foreign key"), pg.owner.connect() as c:
        c.execute(text(insert_sql(other)), {"i": inst})  # business B, instance of A: the composite FK refuses


def test_the_row_level_check_refuses_a_row_for_a_business_other_than_the_bound_one(ret):
    from .conftest import ctx, user_id

    pg, a, inst = ret
    other = new_business(pg, "mallory")
    with pytest.raises(DBAPIError, match="row-level security"), pg.app_rw.begin() as c:
        ctx(c, user_id(pg.owner, "mallory"), other)
        c.execute(text(insert_sql(a)), {"i": inst})  # bound to B, writing a row of A
    with pg.app_rw.begin() as c:  # and a reader bound to B sees none of A's acceptances
        accept(pg, a, inst, {"check_code": "C-16", "note": "ok"})
        ctx(c, user_id(pg.owner, "mallory"), other)
        assert c.execute(text("select count(*) from filing.check_acceptances")).scalar() == 0

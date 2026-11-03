"""The sales tables (LLD-4 §2.1, §2.2): row-level security, grants, the series scope.

Test data is made up. Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from .conftest import PG_ADMIN_URL, ctx, user_id
from .conftest import new_business

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")

GSTIN = "19AAPFU0939F1ZS"


@pytest.fixture()
def two(pg):
    a, b = new_business(pg, "alice"), new_business(pg, "bob")
    return pg, a, b, user_id(pg.owner, "alice"), user_id(pg.owner, "bob")


def add_draft(c, biz, user, with_line=True):
    d = uuid.uuid4()
    c.execute(text("insert into sales.drafts (id, business_id, kind, created_by, updated_by)"
                   " values (:i, :b, 'invoice', :u, :u)"), {"i": d, "b": biz, "u": user})
    if with_line:
        c.execute(text("insert into sales.draft_lines (id, business_id, draft_id, line_no, quantity, unit_price)"
                       " values (:i, :b, :d, 1, 2.500, 10.00)"), {"i": uuid.uuid4(), "b": biz, "d": d})
    return d


def test_each_business_sees_only_its_own_drafts(two):
    pg, a, b, alice, bob = two
    with pg.app_rw.begin() as c:
        ctx(c, alice, a)
        add_draft(c, a, alice)
    with pg.app_rw.begin() as c:
        ctx(c, bob, b)
        assert c.execute(text("select count(*) from sales.drafts")).scalar() == 0
        assert c.execute(text("select count(*) from sales.draft_lines")).scalar() == 0
    with pg.app_rw.begin() as c:
        ctx(c, alice, a)
        assert c.execute(text("select count(*) from sales.draft_lines")).scalar() == 1


@pytest.mark.parametrize("table", ["drafts", "draft_lines", "number_series"])
def test_a_support_grant_id_turns_the_tenant_policies_off(two, table):
    pg, a, _b, alice, _ = two
    with pg.app_rw.begin() as c:
        ctx(c, alice, a)
        add_draft(c, a, alice)
    with pg.app_rw.begin() as c:
        ctx(c, alice, a, grant=uuid.uuid4())
        assert c.execute(text(f"select count(*) from sales.{table}")).scalar() == 0


def test_a_write_for_another_business_is_refused(two):
    pg, a, b, alice, _ = two
    with pytest.raises(DBAPIError):
        with pg.app_rw.begin() as c:
            ctx(c, alice, a)
            add_draft(c, b, alice)


def test_a_line_cannot_point_at_another_businesses_draft(two):
    pg, a, b, alice, bob = two
    with pg.owner.connect() as c:
        d = add_draft(c, b, bob, with_line=False)
    with pytest.raises(DBAPIError):
        with pg.app_rw.begin() as c:
            ctx(c, alice, a)
            c.execute(text("insert into sales.draft_lines (id, business_id, draft_id, line_no)"
                           " values (:i, :b, :d, 1)"), {"i": uuid.uuid4(), "b": a, "d": d})


def test_deleting_a_draft_removes_its_lines(two):
    pg, a, _b, alice, _ = two
    with pg.app_rw.begin() as c:
        ctx(c, alice, a)
        d = add_draft(c, a, alice)
        c.execute(text("delete from sales.drafts where id = :d"), {"d": d})
        assert c.execute(text("select count(*) from sales.draft_lines")).scalar() == 0


def test_line_checks(two):
    pg, a, _b, alice, _ = two
    for col, val in (("quantity", "0"), ("unit_price", "-1")):
        with pytest.raises(DBAPIError):
            with pg.app_rw.begin() as c:
                ctx(c, alice, a)
                d = add_draft(c, a, alice, with_line=False)
                c.execute(text(f"insert into sales.draft_lines (id, business_id, draft_id, line_no, {col})"
                               f" values (:i, :b, :d, 1, {val})"), {"i": uuid.uuid4(), "b": a, "d": d})


def add_series(c, biz, fy="2026-27", kind="invoice", prefix="INV/"):
    c.execute(text("insert into sales.number_series (id, business_id, gstin, kind, fy, prefix, width, next_value)"
                   " values (:i, :b, :g, :k, :fy, :p, 4, 1)"),
              {"i": uuid.uuid4(), "b": biz, "g": GSTIN, "k": kind, "fy": fy, "p": prefix})


def test_one_series_per_gstin_kind_and_fy(two):
    pg, a, _b, alice, _ = two
    with pg.app_rw.begin() as c:
        ctx(c, alice, a)
        add_series(c, a)
        add_series(c, a, fy="2027-28")
        add_series(c, a, kind="credit_note", prefix="CN/")
    with pytest.raises(DBAPIError):
        with pg.app_rw.begin() as c:
            ctx(c, alice, a)
            add_series(c, a, prefix="OTHER/")


def test_app_rw_may_only_advance_next_value(two):
    pg, a, _b, alice, _ = two
    with pg.app_rw.begin() as c:
        ctx(c, alice, a)
        add_series(c, a)
        c.execute(text("update sales.number_series set next_value = next_value + 1"))
    for sql in ("update sales.number_series set prefix = 'X/'",
                "update sales.number_series set fy = '2030-31'",
                "delete from sales.number_series"):
        with pytest.raises(DBAPIError):
            with pg.app_rw.begin() as c:
                ctx(c, alice, a)
                c.execute(text(sql))


def test_app_ro_reads_but_never_writes(two):
    pg, a, _b, alice, _ = two
    with pg.app_rw.begin() as c:
        ctx(c, alice, a)
        add_draft(c, a, alice)
    with pg.app_rw.begin() as c:
        ctx(c, alice, a, role="app_ro")
        assert c.execute(text("select count(*) from sales.drafts")).scalar() == 1
    with pytest.raises(DBAPIError):
        with pg.app_rw.begin() as c:
            ctx(c, alice, a, role="app_ro")
            add_draft(c, a, alice)


def test_next_value_never_goes_back(two):
    pg, a, _b, alice, _ = two
    with pg.app_rw.begin() as c:
        ctx(c, alice, a)
        add_series(c, a)
        c.execute(text("update sales.number_series set next_value = 5"))
        c.execute(text("update sales.number_series set next_value = 5"))  # staying put is fine
    with pytest.raises(DBAPIError) as err:
        with pg.app_rw.begin() as c:
            ctx(c, alice, a)
            c.execute(text("update sales.number_series set next_value = 4"))
    assert err.value.orig.sqlstate == "SNS01"
    with pg.app_rw.begin() as c:
        ctx(c, alice, a)
        assert c.execute(text("select next_value from sales.number_series")).scalar() == 5

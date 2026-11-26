"""#472 on PostgreSQL: past its hourly allowance a user gets 429 with Retry-After, counted per user AND per business,
so nobody else is locked out, and a stranger calling someone else's business spends only their own allowance.
Routes with no limit write no counter. Shown through the customer routes (app/ratelimits.py is the same code for
every route). Skipped unless PG_ADMIN_URL is set."""

import uuid

import pytest
from sqlalchemy import text

from .conftest import PG_ADMIN_URL, as_user, new_business, seed_member

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


def _set(pg, kind: str, value: int) -> None:
    with pg.owner.connect() as c:
        c.execute(text("update refdata.values set value = :v where key = :k"),
                  {"v": str(value), "k": f"ratelimit.{kind}_per_user_per_business_per_hour"})
        c.execute(text("insert into refdata.loads (id, git_sha, files, rows_inserted, rows_closed, rows_updated)"
                       " values (:i, 'test', '{}', 0, 0, 1)"), {"i": uuid.uuid4()})


def _customer(pg, biz, sub="alice"):
    body = {"name": f"Shop {uuid.uuid4().hex[:6]}", "gstin": "27AAPFU0939F1ZV", "credit_days": 30,
            "billing": {"line1": "12 MG Road", "city": "Pune", "pin": "411001"}}
    return pg.client.post(f"/api/v1/b/{biz}/customers", json=body,
                          headers={**as_user(sub), "Idempotency-Key": uuid.uuid4().hex})


def _counters(pg) -> int:
    with pg.owner.connect() as c:
        return c.execute(text("select coalesce(sum(count), 0) from platform.rate_counters")).scalar()


def test_past_the_allowance_a_write_is_429_with_retry_after(pg):
    biz = new_business(pg, "alice")
    _set(pg, "write", 3)
    assert [_customer(pg, biz).status_code for _ in range(3)] == [201, 201, 201]
    r = _customer(pg, biz)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1
    assert r.json()["error"]["code"] == "rate_limited"


def test_the_count_is_per_user_and_per_business(pg):
    biz = new_business(pg, "alice")
    seed_member(pg, biz, "bob", "admin")
    other = new_business(pg, "alice")
    _set(pg, "write", 2)
    assert [_customer(pg, biz).status_code for _ in range(2)] == [201, 201]
    assert _customer(pg, biz).status_code == 429
    assert _customer(pg, biz, sub="bob").status_code == 201  # a colleague is not locked out
    assert _customer(pg, other).status_code == 201  # nor is the same user in another business


def test_a_stranger_spends_only_their_own_allowance(pg):
    biz = new_business(pg, "alice")
    _set(pg, "write", 2)
    assert [_customer(pg, biz, sub="mallory").status_code for _ in range(3)] == [404, 404, 429]
    assert [_customer(pg, biz).status_code for _ in range(2)] == [201, 201]  # alice's allowance is untouched


def test_a_route_with_no_limit_writes_no_counter(pg):
    biz = new_business(pg, "alice")
    before = _counters(pg)
    for _ in range(5):
        assert pg.client.get(f"/api/v1/b/{biz}/customers", headers=as_user("alice")).status_code == 200
    assert _counters(pg) == before


def test_no_signed_in_caller_is_left_to_the_route_and_counts_nothing(pg):
    biz = new_business(pg, "alice")
    before = _counters(pg)
    assert pg.client.post(f"/api/v1/b/{biz}/customers", json={}).status_code == 401
    assert _counters(pg) == before

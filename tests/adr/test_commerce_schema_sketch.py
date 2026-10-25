"""Proves the invariants in docs/adr/0001-commerce-data-model.md on real PostgreSQL.

Applies the identity migrations and the commerce design sketch to a throwaway
database, then exercises it as svc_commerce. Skipped unless PG_ADMIN_URL points at a
disposable server, e.g.
PG_ADMIN_URL=postgresql+psycopg://postgres@localhost:5432/postgres
"""

import os
import threading
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.exc import DBAPIError, IntegrityError

ADMIN_URL = os.environ.get("PG_ADMIN_URL")
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="PG_ADMIN_URL not set")

SERVICES = Path(__file__).resolve().parents[2]
IDENTITY_MIGRATIONS = sorted((SERVICES / "identity" / "migrations").glob("*.sql"))
SKETCH = SERVICES / "commerce" / "design" / "0001_commerce_schema_sketch.sql"


@pytest.fixture(scope="module")
def dbs():
    dbname = f"t_{uuid.uuid4().hex[:10]}"
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f"create database {dbname}"))
        c.execute(text("do $$ begin if not exists (select from pg_roles where rolname='rds_iam') then create role rds_iam; end if; end $$"))
    url = make_url(ADMIN_URL)
    owner = create_engine(url.set(database=dbname), isolation_level="AUTOCOMMIT")
    with owner.connect() as c:
        raw = c.connection.driver_connection  # no parameter parsing, so '%' in plpgsql is safe
        for m in IDENTITY_MIGRATIONS:
            raw.execute(m.read_text())
        raw.execute(SKETCH.read_text())
        c.execute(text("alter role svc_commerce password 'test-only'"))
    svc = create_engine(url.set(username="svc_commerce", password="test-only", database=dbname))
    yield owner, svc
    svc.dispose()
    owner.dispose()
    with admin.connect() as c:
        c.execute(text(f"drop database {dbname} with (force)"))


def _tenant(owner, user):
    tid = uuid.uuid4()
    with owner.connect() as c:
        c.execute(text("insert into identity.tenants (id, name) values (:t, 'T')"), {"t": tid})
        c.execute(
            text("insert into identity.memberships (id, tenant_id, user_sub, role) values (:i, :t, :u, 'owner')"),
            {"i": uuid.uuid4(), "t": tid, "u": user},
        )
    return tid


def _as(conn, tenant_id, user):
    conn.execute(text("select set_config('app.tenant_id', :t, true), set_config('app.user_sub', :u, true)"),
                 {"t": str(tenant_id), "u": user})


@pytest.fixture()
def world(dbs):
    """A tenant with one product, one location and one numbering series."""
    owner, svc = dbs
    user = f"u_{uuid.uuid4().hex[:6]}"
    tid = _tenant(owner, user)
    ids = {k: uuid.uuid4() for k in ("product", "location", "series")}
    with svc.begin() as c:
        _as(c, tid, user)
        c.execute(text("insert into commerce.products (id, tenant_id, sku, name, unit) values (:p, :t, 'SKU1', 'Shampoo', 'pcs')"),
                  {"p": ids["product"], "t": tid})
        c.execute(text("insert into commerce.locations (id, tenant_id, name) values (:l, :t, 'Main')"),
                  {"l": ids["location"], "t": tid})
        c.execute(text("insert into commerce.number_series (id, tenant_id, doc_type, financial_year, prefix) "
                       "values (:s, :t, 'invoice', '2026-27', 'INV-')"), {"s": ids["series"], "t": tid})
    return svc, owner, tid, user, ids


def _receipt(c, tid, ids, source_id, qty="10"):
    c.execute(
        text("insert into commerce.stock_movements (id, tenant_id, product_id, location_id, movement_type, "
             "on_hand_delta, unit_cost, occurred_at, source_type, source_id, created_by) "
             "values (:id, :t, :p, :l, 'purchase_receipt', :q, 100.0000, now(), 'goods_receipt', :s, 'u')"),
        {"id": uuid.uuid4(), "t": tid, "p": ids["product"], "l": ids["location"], "q": qty, "s": source_id},
    )


def _draft_invoice(c, tid, ids):
    doc = uuid.uuid4()
    c.execute(text("insert into commerce.sales_documents (id, tenant_id, doc_type, document_date, rounding_mode, "
                   "rounding_level, created_by) values (:d, :t, 'invoice', current_date, 'ROUND_HALF_UP', 'line', 'u')"),
              {"d": doc, "t": tid})
    c.execute(text("insert into commerce.sales_lines (id, tenant_id, document_id, line_no, product_id, product_sku, "
                   "product_name, quantity, unit_price, taxable_value) "
                   "values (:i, :t, :d, 1, :p, 'SKU1', 'Shampoo', 2, 150.0000, 300.00)"),
              {"i": uuid.uuid4(), "t": tid, "d": doc, "p": ids["product"]})
    return doc


def _finalize(c, tid, ids, doc):
    seq = c.execute(text("update commerce.number_series set next_value = next_value + 1 "
                         "where id = :s returning next_value - 1"), {"s": ids["series"]}).scalar_one()
    c.execute(text("update commerce.sales_documents set status = 'finalized', series_id = :s, sequence_no = :n, "
                   "document_number = 'INV-' || lpad(cast(:n as text), 5, '0'), finalized_at = now(), finalized_by = 'u', "
                   "total_amount = 300.00 where id = :d"), {"s": ids["series"], "n": seq, "d": doc})
    return seq


def test_retried_receipt_moves_stock_once(world):
    svc, _, tid, user, ids = world
    with svc.begin() as c:
        _as(c, tid, user)
        _receipt(c, tid, ids, "GRN-1")
    with pytest.raises(IntegrityError), svc.begin() as c:
        _as(c, tid, user)
        _receipt(c, tid, ids, "GRN-1")
    with svc.begin() as c:
        _as(c, tid, user)
        total = c.execute(text("select sum(on_hand_delta) from commerce.stock_movements where product_id = :p"),
                          {"p": ids["product"]}).scalar_one()
    assert str(total) == "10.000"


def test_posted_movements_cannot_be_edited_or_deleted(world):
    svc, _, tid, user, ids = world
    with svc.begin() as c:
        _as(c, tid, user)
        _receipt(c, tid, ids, "GRN-2")
    for stmt in ("update commerce.stock_movements set on_hand_delta = 99",
                 "delete from commerce.stock_movements"):
        with pytest.raises(DBAPIError), svc.begin() as c:
            _as(c, tid, user)
            c.execute(text(stmt))


def test_movement_can_be_reversed_only_once(world):
    svc, _, tid, user, ids = world
    with svc.begin() as c:
        _as(c, tid, user)
        _receipt(c, tid, ids, "GRN-3")
        original = c.execute(text("select id from commerce.stock_movements where source_id = 'GRN-3'")).scalar_one()

    def reverse(c, n):
        c.execute(text("insert into commerce.stock_movements (id, tenant_id, product_id, location_id, movement_type, "
                       "on_hand_delta, occurred_at, source_type, source_id, source_line_id, reverses_movement_id, created_by) "
                       "values (:id, :t, :p, :l, 'reversal', -10, now(), 'correction', :s, '', :r, 'u')"),
                  {"id": uuid.uuid4(), "t": tid, "p": ids["product"], "l": ids["location"], "s": f"C-{n}", "r": original})

    with svc.begin() as c:
        _as(c, tid, user)
        reverse(c, 1)
    with pytest.raises(IntegrityError), svc.begin() as c:
        _as(c, tid, user)
        reverse(c, 2)


def test_finalized_invoice_is_immutable_but_cancellable(world):
    svc, _, tid, user, ids = world
    with svc.begin() as c:
        _as(c, tid, user)
        doc = _draft_invoice(c, tid, ids)
        _finalize(c, tid, ids, doc)
    with svc.begin() as c:
        _as(c, tid, user)
        other_draft = _draft_invoice(c, tid, ids)
    for stmt in ("update commerce.sales_documents set total_amount = 1 where id = :d",
                 # Re-parenting a finalized line onto a draft would empty the invoice.
                 f"update commerce.sales_lines set document_id = '{other_draft}', line_no = 2 where document_id = :d",
                 "update commerce.sales_lines set quantity = 5 where document_id = :d",
                 "delete from commerce.sales_lines where document_id = :d",
                 "update commerce.sales_documents set status = 'cancelled', cancelled_at = now(), "
                 "document_number = 'X' where id = :d"):
        with pytest.raises(DBAPIError), svc.begin() as c:
            _as(c, tid, user)
            c.execute(text(stmt), {"d": doc})
    with svc.begin() as c:
        _as(c, tid, user)
        c.execute(text("update commerce.sales_documents set status = 'cancelled', cancelled_at = now(), "
                       "cancelled_by = 'u', cancel_reason = 'wrong customer' where id = :d"), {"d": doc})
    with pytest.raises(DBAPIError), svc.begin() as c:
        _as(c, tid, user)
        c.execute(text("update commerce.sales_documents set status = 'finalized' where id = :d"), {"d": doc})


def test_failed_finalization_returns_its_number(world):
    svc, _, tid, user, ids = world
    with svc.begin() as c:
        _as(c, tid, user)
        doc = _draft_invoice(c, tid, ids)
    with pytest.raises(RuntimeError), svc.begin() as c:
        _as(c, tid, user)
        _finalize(c, tid, ids, doc)
        raise RuntimeError("stock check failed after numbering")
    with svc.begin() as c:
        _as(c, tid, user)
        assert _finalize(c, tid, ids, doc) == 1


def test_concurrent_finalizations_get_distinct_gapless_numbers(world):
    svc, _, tid, user, ids = world
    with svc.begin() as c:
        _as(c, tid, user)
        docs = [_draft_invoice(c, tid, ids) for _ in range(8)]
    results, errors = [], []

    def run(doc):
        try:
            with svc.begin() as c:
                _as(c, tid, user)
                results.append(_finalize(c, tid, ids, doc))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(d,)) for d in docs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert sorted(results) == list(range(1, 9))


def test_cross_tenant_reference_is_rejected_by_the_database(world, dbs):
    svc, owner, tid_a, user_a, ids_a = world
    user_b = f"u_{uuid.uuid4().hex[:6]}"
    tid_b = _tenant(owner, user_b)
    with svc.begin() as c:
        _as(c, tid_b, user_b)
        c.execute(text("insert into commerce.locations (id, tenant_id, name) values (:l, :t, 'B')"),
                  {"l": uuid.uuid4(), "t": tid_b})
    # Tenant B tries to receive stock into tenant A's product id.
    with pytest.raises(IntegrityError), svc.begin() as c:
        _as(c, tid_b, user_b)
        loc_b = c.execute(text("select id from commerce.locations")).scalar_one()
        _receipt(c, tid_b, {"product": ids_a["product"], "location": loc_b}, "GRN-X")


def test_rls_hides_other_tenants_and_non_members(world, dbs):
    svc, owner, tid_a, user_a, ids_a = world
    user_b = f"u_{uuid.uuid4().hex[:6]}"
    tid_b = _tenant(owner, user_b)
    with svc.begin() as c:
        _as(c, tid_b, user_b)
        assert c.execute(text("select count(*) from commerce.products where id = :p"), {"p": ids_a["product"]}).scalar_one() == 0
        # Writing a row tagged with tenant A while acting as tenant B fails the policy.
        with pytest.raises(DBAPIError):
            with c.begin_nested():
                c.execute(text("insert into commerce.locations (id, tenant_id, name) values (:l, :t, 'sneaky')"),
                          {"l": uuid.uuid4(), "t": tid_a})
    # Claiming tenant A's id without being a member of it shows nothing.
    with svc.begin() as c:
        _as(c, tid_a, user_b)
        assert c.execute(text("select count(*) from commerce.products")).scalar_one() == 0


def test_allocations_are_append_only(world):
    svc, _, tid, user, ids = world
    pay = uuid.uuid4()
    with svc.begin() as c:
        _as(c, tid, user)
        doc = _draft_invoice(c, tid, ids)
        _finalize(c, tid, ids, doc)
        c.execute(text("insert into commerce.payments (id, tenant_id, direction, amount, payment_date, created_by) "
                       "values (:p, :t, 'received', 300.00, current_date, 'u')"), {"p": pay, "t": tid})
        c.execute(text("insert into commerce.payment_allocations (id, tenant_id, payment_id, sales_document_id, amount, created_by) "
                       "values (:i, :t, :p, :d, 300.00, 'u')"), {"i": uuid.uuid4(), "t": tid, "p": pay, "d": doc})
    with pytest.raises(DBAPIError), svc.begin() as c:
        _as(c, tid, user)
        c.execute(text("update commerce.payment_allocations set amount = 1"))

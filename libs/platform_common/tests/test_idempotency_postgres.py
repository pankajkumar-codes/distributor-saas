"""T-006: idempotency keys on real PostgreSQL. Skipped unless PG_ADMIN_URL is set.

Runs against the real platform migration, as app_rw, so RLS applies as in production.
"""

import os
import threading
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.orm import sessionmaker

from platform_common.errors import AppError, Conflict
from platform_common.idempotency import request_hash, run_once

ADMIN_URL = os.environ.get("PG_ADMIN_URL")
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="PG_ADMIN_URL not set")
MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
ROUTE = "/api/v1/b/{business_id}/demo"


@pytest.fixture(scope="module")
def factory():
    dbname = f"t_{uuid.uuid4().hex[:10]}"
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f"create database {dbname}"))
        for role in ("app_rw", "app_ro", "retention_owner"):  # the platform migrations grant to all three
            c.execute(text(
                f"do $$ begin if not exists (select from pg_roles where rolname = '{role}') "
                f"then create role {role} nologin; end if; end $$"
            ))
    eng = create_engine(make_url(ADMIN_URL).set(database=dbname))
    with eng.begin() as c:
        for f in sorted(MIGRATIONS.glob("*.sql")):
            c.exec_driver_sql(f.read_text())
        c.execute(text("create schema demo"))
        c.execute(text("create table demo.effects (id serial primary key, tenant_id uuid not null, note text)"))
        c.execute(text("grant usage on schema demo to app_rw"))
        c.execute(text("grant select, insert on demo.effects to app_rw"))
        c.execute(text("grant usage on sequence demo.effects_id_seq to app_rw"))
    yield sessionmaker(bind=eng)
    eng.dispose()
    with admin.connect() as c:
        c.execute(text(f"drop database {dbname} with (force)"))


def _as_app(s, tenant):
    s.execute(text("set local role app_rw"))
    s.execute(text("select set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})


def _post(factory, tenant, key, payload, fail=False, pause=None, route=ROUTE, scope=None):
    with factory() as s, s.begin():
        _as_app(s, tenant)

        def op():
            new_id = s.execute(text("insert into demo.effects (tenant_id, note) values (:t, :n) returning id"),
                               {"t": tenant, "n": payload["note"]}).scalar_one()
            if pause:
                pause.wait(5)
            if fail:
                raise RuntimeError("boom")
            return {"id": new_id, "note": payload["note"]}
        return run_once(s, scope or tenant, key, method="POST", route=route, payload=payload, operation=op)


def _effects(factory, tenant):
    with factory() as s:
        return s.scalar(text("select count(*) from demo.effects where tenant_id = :t"), {"t": tenant})


def test_retry_returns_the_first_result_and_has_one_effect(factory):
    t = uuid.uuid4()
    first = _post(factory, t, "k1", {"note": "a"})
    again = _post(factory, t, "k1", {"note": "a"})
    assert first == again
    assert _effects(factory, t) == 1


def test_same_key_different_body_is_409(factory):
    t = uuid.uuid4()
    _post(factory, t, "k1", {"note": "a"})
    with pytest.raises(Conflict) as exc:
        _post(factory, t, "k1", {"note": "b"})
    assert exc.value.status == 409 and exc.value.code == "idempotency_mismatch"
    assert _effects(factory, t) == 1


def test_same_key_and_body_on_another_route_is_409(factory):
    t = uuid.uuid4()
    _post(factory, t, "k1", {"note": "a"})
    with pytest.raises(Conflict):
        _post(factory, t, "k1", {"note": "a"}, route="/api/v1/b/{business_id}/other")
    assert _effects(factory, t) == 1


def test_keys_are_per_scope(factory):
    t1, t2 = uuid.uuid4(), uuid.uuid4()
    _post(factory, t1, "k1", {"note": "a"})
    _post(factory, t2, "k1", {"note": "b"})
    assert _effects(factory, t1) == 1 and _effects(factory, t2) == 1


def test_rls_refuses_a_key_for_another_scope(factory):
    t, other = uuid.uuid4(), uuid.uuid4()
    with pytest.raises(Exception, match="row-level security"):
        _post(factory, t, "k1", {"note": "a"}, scope=other)


def test_rls_hides_another_scopes_keys(factory):
    t1, t2 = uuid.uuid4(), uuid.uuid4()
    _post(factory, t1, "k-hidden", {"note": "a"})
    with factory() as s, s.begin():
        _as_app(s, t2)
        assert s.scalar(text("select count(*) from platform.idempotency_keys")) == 0
        _as_app(s, t1)
        assert s.scalar(text("select count(*) from platform.idempotency_keys where key = 'k-hidden'")) == 1


def test_failed_operation_leaves_key_free_for_retry(factory):
    t = uuid.uuid4()
    with pytest.raises(RuntimeError):
        _post(factory, t, "k1", {"note": "a"}, fail=True)
    assert _effects(factory, t) == 0
    _post(factory, t, "k1", {"note": "a"})
    assert _effects(factory, t) == 1


def test_concurrent_duplicates_run_once(factory):
    t = uuid.uuid4()
    gate = threading.Event()
    results = []
    first = threading.Thread(target=lambda: results.append(_post(factory, t, "k1", {"note": "a"}, pause=gate)))
    first.start()
    threading.Timer(0.5, gate.set).start()
    second = threading.Thread(target=lambda: results.append(_post(factory, t, "k1", {"note": "a"})))
    second.start()
    first.join(10)
    second.join(10)
    assert len(results) == 2 and results[0] == results[1]
    assert _effects(factory, t) == 1


def test_bad_keys_are_400(factory):
    t = uuid.uuid4()
    for key in (None, "", "x" * 201, "a\nb"):
        with pytest.raises(AppError) as exc:
            _post(factory, t, key, {"note": "a"})
        assert exc.value.status == 400 and exc.value.code == "idempotency_key_required"
    assert _effects(factory, t) == 0


def test_hash_ignores_key_order_but_not_method_or_route():
    assert request_hash("POST", ROUTE, {"a": 1, "b": 2}) == request_hash("post", ROUTE, {"b": 2, "a": 1})
    assert request_hash("POST", ROUTE, {}) != request_hash("PUT", ROUTE, {})
    assert request_hash("POST", ROUTE, {}) != request_hash("POST", ROUTE + "/x", {})

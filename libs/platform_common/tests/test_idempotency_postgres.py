"""T-006: idempotency keys on real PostgreSQL. Skipped unless PG_ADMIN_URL is set."""

import os
import threading
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.orm import sessionmaker

from platform_common.idempotency import request_hash, run_once

ADMIN_URL = os.environ.get("PG_ADMIN_URL")
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="PG_ADMIN_URL not set")
TABLE = "demo.idempotency_keys"


@pytest.fixture(scope="module")
def factory():
    dbname = f"t_{uuid.uuid4().hex[:10]}"
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f"create database {dbname}"))
    eng = create_engine(make_url(ADMIN_URL).set(database=dbname))
    with eng.begin() as c:
        c.execute(text("create schema demo"))
        c.execute(text("""create table demo.idempotency_keys (
            tenant_id uuid not null, key varchar(200) not null, request_hash char(64) not null,
            response jsonb, created_at timestamptz not null default now(), primary key (tenant_id, key))"""))
        c.execute(text("create table demo.effects (id serial primary key, tenant_id uuid not null, note text)"))
    yield sessionmaker(bind=eng)
    eng.dispose()
    with admin.connect() as c:
        c.execute(text(f"drop database {dbname} with (force)"))


def _post(factory, tenant, key, payload, fail=False, pause=None):
    with factory() as s, s.begin():
        def op():
            new_id = s.execute(text("insert into demo.effects (tenant_id, note) values (:t, :n) returning id"),
                               {"t": tenant, "n": payload["note"]}).scalar_one()
            if pause:
                pause.wait(5)
            if fail:
                raise RuntimeError("boom")
            return {"id": new_id, "note": payload["note"]}
        return run_once(s, TABLE, tenant, key, payload, op)


def _effects(factory, tenant):
    with factory() as s:
        return s.scalar(text("select count(*) from demo.effects where tenant_id = :t"), {"t": tenant})


def test_retry_returns_the_first_result_and_has_one_effect(factory):
    t = uuid.uuid4()
    first = _post(factory, t, "k1", {"note": "a"})
    again = _post(factory, t, "k1", {"note": "a"})
    assert first == again
    assert _effects(factory, t) == 1


def test_same_key_different_request_is_409(factory):
    t = uuid.uuid4()
    _post(factory, t, "k1", {"note": "a"})
    with pytest.raises(HTTPException) as exc:
        _post(factory, t, "k1", {"note": "b"})
    assert exc.value.status_code == 409
    assert _effects(factory, t) == 1


def test_keys_are_per_tenant(factory):
    t1, t2 = uuid.uuid4(), uuid.uuid4()
    _post(factory, t1, "k1", {"note": "a"})
    _post(factory, t2, "k1", {"note": "b"})
    assert _effects(factory, t1) == 1 and _effects(factory, t2) == 1


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


def test_bad_inputs(factory):
    t = uuid.uuid4()
    for key in ("", "x" * 201, "a\nb"):
        with pytest.raises(HTTPException) as exc:
            _post(factory, t, key, {"note": "a"})
        assert exc.value.status_code == 400
    with factory() as s, pytest.raises(ValueError):
        run_once(s, "demo.effects; drop table x", t, "k", {}, lambda: None)


def test_hash_ignores_key_order():
    assert request_hash({"a": 1, "b": 2}) == request_hash({"b": 2, "a": 1})

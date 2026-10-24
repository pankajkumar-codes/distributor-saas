"""Runs the real migration on PostgreSQL as the svc_imports role.

Skipped unless PG_ADMIN_URL points at a disposable server, e.g.
PG_ADMIN_URL=postgresql+psycopg://postgres@localhost:5432/postgres
"""

import os
import threading
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, make_url, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app import staging
from app.models import ImportRow, ImportRun
from app.parsing import FieldSpec, MappingProfile, read_table

ADMIN_URL = os.environ.get("PG_ADMIN_URL")
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="PG_ADMIN_URL not set")
MIGRATIONS = sorted((Path(__file__).parent.parent / "migrations").glob("*.sql"))
PROFILE = MappingProfile(
    marketplace="meesho",
    report_type="orders",
    version="t",
    fields=(FieldSpec("sub_order", ("Sub Order No",)), FieldSpec("status", ("Status",))),
    dedup_key=("sub_order",),
)


@pytest.fixture()
def svc():
    dbname = f"t_{uuid.uuid4().hex[:10]}"
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f"create database {dbname}"))
        c.execute(
            text(
                "do $$ begin if not exists (select from pg_roles where rolname='rds_iam') "
                "then create role rds_iam; end if; end $$"
            )
        )
    url = make_url(ADMIN_URL)
    owner = create_engine(url.set(database=dbname), isolation_level="AUTOCOMMIT")
    with owner.connect() as c:
        for m in MIGRATIONS:
            c.exec_driver_sql(m.read_text())
        c.execute(text("alter role svc_imports password 'test-only'"))
    eng = create_engine(url.set(username="svc_imports", password="test-only", database=dbname))
    yield eng
    eng.dispose()
    owner.dispose()
    with admin.connect() as c:
        c.execute(text(f"drop database {dbname} with (force)"))
    admin.dispose()


def tenant_session(eng, tenant_id):
    s = Session(eng)
    s.execute(text("select set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
    return s


def do_stage(eng, tenant_id, body=b"Sub Order No,Status\nS1,shipped\n"):
    with tenant_session(eng, tenant_id) as s:
        run, created = staging.stage(
            s, tenant_id=tenant_id, user_sub="u", table=read_table(body, "m.csv"), profile=PROFILE
        )
        run_id = run.id
        s.commit()  # ends the transaction, so app.tenant_id is cleared again
        return run_id, created


def test_rls_hides_other_tenants_runs(svc):
    a, b = uuid.uuid4(), uuid.uuid4()
    run_a, _ = do_stage(svc, a)
    with tenant_session(svc, b) as s:
        assert s.scalars(select(ImportRun)).all() == []
        assert s.scalars(select(ImportRow)).all() == []
        with pytest.raises(LookupError):
            staging.confirm(s, tenant_id=a, run_id=run_a, user_sub="mallory")  # even naming tenant A
    with tenant_session(svc, a) as s:
        assert [r.id for r in s.scalars(select(ImportRun))] == [run_a]


def test_no_tenant_context_sees_nothing_and_cannot_write(svc):
    do_stage(svc, uuid.uuid4())
    with Session(svc) as s:
        assert s.scalars(select(ImportRun)).all() == []
    with pytest.raises(DBAPIError):
        with Session(svc) as s:
            staging.stage(
                s, tenant_id=uuid.uuid4(), user_sub="u", table=read_table(b"Sub Order No,Status\nS9,x\n", "m.csv"),
                profile=PROFILE,
            )
            s.commit()


def test_rows_are_append_only(svc):
    tenant = uuid.uuid4()
    do_stage(svc, tenant)
    with tenant_session(svc, tenant) as s, pytest.raises(DBAPIError, match="permission denied"):
        s.execute(text("update imports.import_rows set status = 'new'"))
    with tenant_session(svc, tenant) as s, pytest.raises(DBAPIError, match="permission denied"):
        s.execute(text("delete from imports.import_runs"))


def test_concurrent_uploads_of_one_file_make_one_run(svc):
    tenant = uuid.uuid4()
    results, barrier = [], threading.Barrier(4)

    def upload():
        barrier.wait()
        results.append(do_stage(svc, tenant))

    threads = [threading.Thread(target=upload) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len({run_id for run_id, _ in results}) == 1
    assert sum(created for _, created in results) == 1

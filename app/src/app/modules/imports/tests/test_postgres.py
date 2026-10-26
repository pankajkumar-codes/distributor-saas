"""Runs the real migration on PostgreSQL as app_rw, so row-level security applies.

Skipped unless PG_ADMIN_URL points at a disposable server, e.g.
PG_ADMIN_URL=postgresql+psycopg://postgres@localhost:5432/postgres
"""

import os
import threading
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, make_url, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.modules.imports import staging
from app.modules.imports.models import ImportRow, ImportRun
from app.modules.imports.parsing import FieldSpec, MappingProfile, read_table

ADMIN_URL = os.environ.get("PG_ADMIN_URL")
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="PG_ADMIN_URL not set")
MIGRATIONS = sorted((Path(__file__).parent.parent / "migrations").glob("*.sql"))
USER = uuid.uuid4()
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
        # The migrator's bootstrap.sql creates these on a real run.
        for role in ("app_rw", "app_ro"):
            c.execute(
                text(
                    f"do $$ begin if not exists (select from pg_roles where rolname = '{role}') "
                    f"then create role {role} nologin; end if; end $$"
                )
            )
    url = make_url(ADMIN_URL).set(database=dbname)
    owner = create_engine(url, isolation_level="AUTOCOMMIT")
    with owner.connect() as c:
        for m in MIGRATIONS:
            c.exec_driver_sql(m.read_text())
    eng = create_engine(url)

    @event.listens_for(eng, "connect")
    def _as_app_rw(dbapi_conn, _):
        with dbapi_conn.cursor() as cur:
            cur.execute("set role app_rw")
        dbapi_conn.commit()

    yield eng
    eng.dispose()
    owner.dispose()
    with admin.connect() as c:
        c.execute(text(f"drop database {dbname} with (force)"))
    admin.dispose()


def business_session(eng, business_id):
    s = Session(eng)
    s.execute(text("select set_config('app.tenant_id', :t, true)"), {"t": str(business_id)})
    return s


def do_stage(eng, business_id, body=b"Sub Order No,Status\nS1,shipped\n"):
    with business_session(eng, business_id) as s:
        run, created = staging.stage(
            s, business_id=business_id, user_id=USER, table=read_table(body, "m.csv"), profile=PROFILE
        )
        run_id = run.id
        s.commit()  # ends the transaction, so app.tenant_id is cleared again
        return run_id, created


def test_rls_hides_other_businesses_runs(svc):
    a, b = uuid.uuid4(), uuid.uuid4()
    run_a, _ = do_stage(svc, a)
    with business_session(svc, b) as s:
        assert s.scalars(select(ImportRun)).all() == []
        assert s.scalars(select(ImportRow)).all() == []
        with pytest.raises(LookupError):
            staging.confirm(s, business_id=a, run_id=run_a, user_id=uuid.uuid4())  # even naming business A
    with business_session(svc, a) as s:
        assert [r.id for r in s.scalars(select(ImportRun))] == [run_a]


def test_no_business_context_sees_nothing_and_cannot_write(svc):
    do_stage(svc, uuid.uuid4())
    with Session(svc) as s:
        assert s.scalars(select(ImportRun)).all() == []
    with pytest.raises(DBAPIError):
        with Session(svc) as s:
            staging.stage(
                s, business_id=uuid.uuid4(), user_id=USER, table=read_table(b"Sub Order No,Status\nS9,x\n", "m.csv"),
                profile=PROFILE,
            )
            s.commit()


def test_rows_are_append_only(svc):
    business = uuid.uuid4()
    do_stage(svc, business)
    with business_session(svc, business) as s, pytest.raises(DBAPIError, match="permission denied"):
        s.execute(text("update imports.import_rows set status = 'new'"))
    with business_session(svc, business) as s, pytest.raises(DBAPIError, match="permission denied"):
        s.execute(text("delete from imports.import_runs"))


def test_concurrent_uploads_of_one_file_make_one_run(svc):
    business = uuid.uuid4()
    results, barrier = [], threading.Barrier(4)

    def upload():
        barrier.wait()
        results.append(do_stage(svc, business))

    threads = [threading.Thread(target=upload) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len({run_id for run_id, _ in results}) == 1
    assert sum(created for _, created in results) == 1


def test_run_update_is_limited_to_the_status_columns(svc):
    business = uuid.uuid4()
    run_id, _ = do_stage(svc, business)
    with business_session(svc, business) as s, pytest.raises(DBAPIError, match="permission denied"):
        s.execute(text("update imports.import_runs set filename = 'x' where id = :i"), {"i": run_id})
    with business_session(svc, business) as s:
        staging.confirm(s, business_id=business, run_id=run_id, user_id=USER)
        s.commit()


def test_row_cannot_point_at_another_business_run(svc):
    a, b = uuid.uuid4(), uuid.uuid4()
    run_a, _ = do_stage(svc, a)
    with business_session(svc, b) as s, pytest.raises(DBAPIError):
        s.execute(
            text(
                "insert into imports.import_rows (id, run_id, business_id, row_number, status, raw) "
                "values (:i, :r, :b, 99, 'new', '{}')"
            ),
            {"i": uuid.uuid4(), "r": run_a, "b": b},
        )


def test_a_support_session_sees_no_rows_until_support_read_exists(svc):
    business = uuid.uuid4()
    do_stage(svc, business)
    with business_session(svc, business) as s:
        s.execute(text("select set_config('app.support_grant_id', :g, true)"), {"g": str(uuid.uuid4())})
        assert s.scalars(select(ImportRun)).all() == []


def test_columns_are_jsonb(svc):
    with Session(svc) as s:
        types = dict(
            s.execute(
                text(
                    "select column_name, data_type from information_schema.columns "
                    "where table_schema = 'imports' and data_type like 'json%'"
                )
            ).all()
        )
    assert set(types.values()) == {"jsonb"} and {"raw", "normalized", "errors", "summary"} <= set(types)

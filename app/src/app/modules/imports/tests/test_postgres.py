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
REPO = Path(__file__).resolve().parents[6]
MODULE_RANK = {"platform": 0, "identity": 1, "imports": 2}  # migrator.handler.MODULE_ORDER


def _migration_order(module_and_file):
    # migrator.handler.ordered's rule: NNNN_ files first, then by timestamp, then module.
    module, f = module_and_file
    rank = MODULE_RANK[module]
    return (1, f.name[:12], rank, f.name) if f.name[:12].isdigit() else (0, "", rank, f.name)


# support_read needs identity's platform.support_grant_active, so the whole ledger runs.
MIGRATIONS = [
    f
    for _, f in sorted(
        [("imports", f) for f in (Path(__file__).parent.parent / "migrations").glob("*.sql")]
        + [("identity", f) for f in (REPO / "app/src/app/modules/identity/migrations").glob("*.sql")]
        + [("platform", f) for f in (REPO / "libs/platform_common/migrations").glob("*.sql")],
        key=_migration_order,
    )
]
BOOTSTRAP = REPO / "migrator" / "migrator" / "bootstrap.sql"
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
        c.execute(
            text(
                "do $$ begin if not exists (select from pg_roles where rolname='rds_iam') "
                "then create role rds_iam; end if; end $$"
            )
        )
    url = make_url(ADMIN_URL).set(database=dbname)
    owner = create_engine(url, isolation_level="AUTOCOMMIT")
    with owner.connect() as c:
        # As migrator.local does it, straight to psycopg with no parameters, so a '%'
        # in RAISE messages or %rowtype is not read as a placeholder.
        for m in [BOOTSTRAP, *MIGRATIONS, BOOTSTRAP]:
            c.connection.driver_connection.execute(m.read_text())
    eng = create_engine(url)

    @event.listens_for(eng, "connect")
    def _as_app_rw(dbapi_conn, _):
        with dbapi_conn.cursor() as cur:
            cur.execute("set role app_rw")
        dbapi_conn.commit()

    eng.owner = owner  # for seeding identity rows past RLS
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


def test_a_support_session_without_a_live_grant_sees_no_rows(svc):
    business = uuid.uuid4()
    do_stage(svc, business)
    with business_session(svc, business) as s:
        # The tenant policies step aside for support sessions; support_read then needs
        # the named grant to exist and be active, which this made-up one is not.
        s.execute(text("select set_config('app.support_grant_id', :g, true)"), {"g": str(uuid.uuid4())})
        assert s.scalars(select(ImportRun)).all() == []
        assert s.scalars(select(ImportRow)).all() == []


def test_support_read_is_select_only_and_on_every_table(svc):
    with Session(svc) as s:
        rows = s.execute(
            text("select tablename, cmd from pg_policies where schemaname = 'imports' and policyname = 'support_read'")
        ).all()
    assert sorted(rows) == [("document_lines", "SELECT"), ("documents", "SELECT"), ("import_rows", "SELECT"),
                           ("import_runs", "SELECT"), ("period_confirmations", "SELECT"),
                           ("row_resolutions", "SELECT"), ("uploads", "SELECT")]


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


def test_a_confirmed_run_cannot_be_reopened(svc):
    business = uuid.uuid4()
    run_id, _ = do_stage(svc, business)
    with business_session(svc, business) as s:
        staging.confirm(s, business_id=business, run_id=run_id, user_id=USER)
        s.commit()
    for sql in (
        "update imports.import_runs set status = 'discarded' where id = :i",
        "update imports.import_runs set status = 'staged', confirmed_by = null, confirmed_at = null where id = :i",
        "update imports.import_runs set confirmed_at = now() where id = :i",
    ):
        with business_session(svc, business) as s, pytest.raises(DBAPIError, match="import run|only when"):
            s.execute(text(sql), {"i": run_id})


def test_concurrent_confirms_of_overlapping_files_import_a_record_once(svc):
    business = uuid.uuid4()
    run_a, _ = do_stage(svc, business, body=b"Sub Order No,Status\nS1,shipped\n")
    run_b, _ = do_stage(svc, business, body=b"Sub Order No,Status\nS1,shipped\nS2,shipped\n")
    outcomes, barrier = [], threading.Barrier(2)

    def confirm(run_id):
        with business_session(svc, business) as s:
            barrier.wait()
            try:
                staging.confirm(s, business_id=business, run_id=run_id, user_id=USER)
                s.commit()
                outcomes.append("confirmed")
            except staging.StaleRun:
                outcomes.append("stale")

    threads = [threading.Thread(target=confirm, args=(r,)) for r in (run_a, run_b)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert sorted(outcomes) == ["confirmed", "stale"]


def test_a_support_user_with_a_live_grant_reads_but_cannot_write(svc):
    business, owner, support, grant = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    run_id, _ = do_stage(svc, business)
    with svc.owner.connect() as c:
        for uid, is_support in ((owner, False), (support, True)):
            c.execute(
                text("insert into identity.users (id, cognito_sub, email, is_support) values (:i, :s, :e, :f)"),
                {"i": uid, "s": f"sub-{uid}", "e": f"{uid}@example.com", "f": is_support},
            )
        c.execute(
            text("insert into identity.businesses (id, name, created_by) values (:b, 'Co', :u)"),
            {"b": business, "u": owner},
        )
        c.execute(
            text(
                "insert into identity.support_grants (id, business_id, granted_by, expires_at) "
                "values (:g, :b, :u, now() + interval '1 hour')"
            ),
            {"g": grant, "b": business, "u": owner},
        )
    with Session(svc) as s:
        s.execute(
            # Bound to the business as well, so the refusals below come from the support
            # exclusion in the tenant policies, not from a missing tenant (Staff, #35).
            text(
                "select set_config('app.user_id', :u, true), set_config('app.support_grant_id', :g, true),"
                " set_config('app.tenant_id', :b, true)"
            ),
            {"u": str(support), "g": str(grant), "b": str(business)},
        )
        assert [r.id for r in s.scalars(select(ImportRun))] == [run_id]
        assert len(s.scalars(select(ImportRow)).all()) == 1
        # No write policy covers a support session: an update finds nothing, an insert is refused.
        result = s.execute(text("update imports.import_runs set status = 'discarded' where id = :i"), {"i": run_id})
        assert result.rowcount == 0
        with pytest.raises(DBAPIError):
            s.execute(
                text(
                    "insert into imports.import_rows (id, run_id, business_id, row_number, status, raw) "
                    "values (gen_random_uuid(), :r, :b, 99, 'new', '{}')"
                ),
                {"r": run_id, "b": business},
            )


def test_overlapping_files_staged_at_once_are_serialised_so_the_overlap_is_seen(svc):
    """Two parse jobs for overlapping files of one report type: the second must see the first's
    rows (the report-type lock), so the shared record is `new` once and `duplicate` once."""
    business = uuid.uuid4()
    barrier = threading.Barrier(2)

    def stage_one(body):
        with business_session(svc, business) as s:
            barrier.wait()
            staging.stage(s, business_id=business, user_id=USER, table=read_table(body, "m.csv"), profile=PROFILE,
                          flag_live_overlap=True)
            s.commit()

    bodies = (b"Sub Order No,Status\nS1,shipped\nS2,shipped\n", b"Sub Order No,Status\nS2,shipped\nS3,shipped\n")
    threads = [threading.Thread(target=stage_one, args=(b,)) for b in bodies]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    with business_session(svc, business) as s:
        statuses = [r.status.value for r in s.scalars(select(ImportRow).where(ImportRow.business_id == business))]
    assert statuses.count("duplicate") == 1 and statuses.count("new") == 3


def _insert_document(s, business, run_id, row_id, *, number="INV-1"):
    doc, line = uuid.uuid4(), uuid.uuid4()
    s.execute(text(
        "insert into imports.documents (id, business_id, gstin, source, doc_kind, doc_number, doc_key, fy, doc_date,"
        " supply_class, pos_state_code, is_inter_state, first_run_id, created_by, return_instance_id, return_period)"
        " values (:i, :b, '19DEMOA1234A1Z5', 'own_upload', 'invoice', :n, :n, '2026-27', '2026-10-05', 'B2CS', '19',"
        " false, :r, :u, gen_random_uuid(), '2026-10')"), {"i": doc, "b": business, "n": number, "r": run_id, "u": USER})
    s.execute(text(
        "insert into imports.document_lines (id, business_id, document_id, source_row_id, line_key, line_pos, hsn, hsn_from,"
        " rate, taxable_value, igst, cgst, sgst, cess, created_by)"
        " values (:i, :b, :d, :w, repeat('a', 64), 1, '61091000', 'file', 5, 100, 0, 2.5, 2.5, 0, :u)"),
        {"i": line, "b": business, "d": doc, "w": row_id, "u": USER})
    return doc, line


def _a_confirmed_document(svc, business):
    run_id, _ = do_stage(svc, business)
    with business_session(svc, business) as s:
        row_id = s.scalars(select(ImportRow.id)).first()
        doc, line = _insert_document(s, business, run_id, row_id)
        s.commit()
    return run_id, row_id, doc, line


TABLES = ("documents", "document_lines", "period_confirmations")


def test_confirmed_document_tables_are_tenant_isolated_and_insert_only(svc):
    a, b = uuid.uuid4(), uuid.uuid4()
    run_a, row_a, doc_a, line_a = _a_confirmed_document(svc, a)
    with business_session(svc, a) as s:
        s.execute(text("insert into imports.period_confirmations (id, business_id, section, month, created_by)"
                       " values (:i, :b, 'amazon', '2026-10-01', :u)"), {"i": uuid.uuid4(), "b": a, "u": USER})
        s.commit()
    # the owning tenant sees its rows
    with business_session(svc, a) as s:
        assert [s.execute(text(f"select count(*) from imports.{t}")).scalar_one() for t in TABLES] == [1, 1, 1]
    # another tenant, and no tenant at all, see nothing
    with business_session(svc, b) as s:
        assert [s.execute(text(f"select count(*) from imports.{t}")).scalar_one() for t in TABLES] == [0, 0, 0]
    with Session(svc) as s:
        assert [s.execute(text(f"select count(*) from imports.{t}")).scalar_one() for t in TABLES] == [0, 0, 0]
    # a read-only session reads its own tenant only and cannot write
    with business_session(svc, a) as s:
        s.execute(text("set local role app_ro"))
        assert s.execute(text("select count(*) from imports.documents")).scalar_one() == 1
        with pytest.raises(DBAPIError):
            s.execute(text("insert into imports.period_confirmations (id, business_id, section, month, created_by)"
                           " values (:i, :b, 'meesho', '2026-10-01', :u)"), {"i": uuid.uuid4(), "b": a, "u": USER})
    with business_session(svc, b) as s:
        s.execute(text("set local role app_ro"))
        assert s.execute(text("select count(*) from imports.documents")).scalar_one() == 0
    # a tenant cannot insert for another tenant
    with pytest.raises(DBAPIError):
        with business_session(svc, b) as s:
            _insert_document(s, a, run_a, row_a, number="INV-X")
    # insert-only for everyone, the owner included: no update, delete or truncate
    for t in TABLES:
        for stmt in (f"update imports.{t} set business_id = business_id", f"delete from imports.{t}", f"truncate imports.{t}"):
            with pytest.raises(DBAPIError):
                with svc.owner.connect() as c:
                    c.execute(text(stmt))
            with pytest.raises(DBAPIError):
                with business_session(svc, a) as s:
                    s.execute(text(stmt))


def test_a_confirmed_line_cannot_point_at_another_tenants_document_run_or_row(svc):
    a, b = uuid.uuid4(), uuid.uuid4()
    run_a, row_a, doc_a, _ = _a_confirmed_document(svc, a)
    run_b, _ = do_stage(svc, b)
    with business_session(svc, b) as s:
        row_b = s.scalars(select(ImportRow.id)).first()
    # business B's document may not claim A's run, nor B's line A's document or A's row
    with pytest.raises(DBAPIError):
        with business_session(svc, b) as s:
            _insert_document(s, b, run_a, row_b, number="INV-1")
    with pytest.raises(DBAPIError):
        with business_session(svc, b) as s:
            s.execute(text(
                "insert into imports.document_lines (id, business_id, document_id, source_row_id, line_key, line_pos, hsn,"
                " hsn_from, rate, taxable_value, igst, cgst, sgst, cess, created_by) values (:i, :b, :d, :w,"
                " repeat('b', 64), 1, '61091000', 'file', 5, 1, 0, 0, 0, 0, :u)"),
                {"i": uuid.uuid4(), "b": b, "d": doc_a, "w": row_b, "u": USER})
    with pytest.raises(DBAPIError):
        with business_session(svc, b) as s:
            doc_b = uuid.uuid4()
            s.execute(text(
                "insert into imports.documents (id, business_id, gstin, source, doc_kind, doc_number, doc_key, fy, doc_date,"
                " supply_class, pos_state_code, is_inter_state, first_run_id, created_by, return_instance_id, return_period)"
                " values (:i, :b, '19DEMOA1234A1Z5', 'own_upload', 'invoice', 'I', 'I', '2026-27', '2026-10-05', 'B2CS', '19', false,"
                " :r, :u, gen_random_uuid(), '2026-10')"),
                {"i": doc_b, "b": b, "r": run_b, "u": USER})
            s.execute(text(
                "insert into imports.document_lines (id, business_id, document_id, source_row_id, line_key, line_pos, hsn,"
                " hsn_from, rate, taxable_value, igst, cgst, sgst, cess, created_by) values (:i, :b, :d, :w,"
                " repeat('c', 64), 1, '61091000', 'file', 5, 1, 0, 0, 0, 0, :u)"),
                {"i": uuid.uuid4(), "b": b, "d": doc_b, "w": row_a, "u": USER})

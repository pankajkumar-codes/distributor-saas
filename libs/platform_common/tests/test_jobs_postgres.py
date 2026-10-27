"""Outbox and jobs on PostgreSQL, as app_rw with FORCE row-level security (LLD-0 §3.7,
§4.5; HLD §7; AC-9, AC-16). The queue is FakeQueue throughout; no AWS is touched.

Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import os
import threading
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, make_url, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.orm import sessionmaker

from platform_common import jobs, outbox
from platform_common import uow as uow_mod
from platform_common.queue import FakeQueue, set_queue
from platform_common.uow import Principal, unit_of_work

ADMIN_URL = os.environ.get("PG_ADMIN_URL")
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="PG_ADMIN_URL not set")
ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS = ROOT / "libs" / "platform_common" / "migrations"
BOOTSTRAP = ROOT / "migrator" / "migrator" / "bootstrap.sql"
A, B = uuid.uuid4(), uuid.uuid4()
ASHA, RAVI = uuid.uuid4(), uuid.uuid4()
CALLS: list[tuple] = []
STATE = {}


# Handlers used by these tests. Each records what it saw.
@jobs.handler("test.ok")
def _ok(ctx: jobs.JobContext) -> dict:
    seen = ctx.uow.tx.execute(text("select count(*), count(distinct business_id) from platform.jobs")).one()
    CALLS.append(("ok", ctx.job_id, ctx.uow.principal.business_id, ctx.uow.principal.user_id, tuple(seen)))
    return {"seen_jobs": seen[0]}


@jobs.handler("test.flaky")
def _flaky(ctx: jobs.JobContext) -> dict:
    CALLS.append(("flaky", ctx.job_id, ctx.attempt))
    ctx.uow.tx.execute(text("update platform.jobs set error_code = 'half-done' where id = :i"), {"i": ctx.job_id})
    if ctx.attempt == 1:
        raise RuntimeError("transient")
    return {}


@jobs.handler("test.bad_file")
def _bad(ctx: jobs.JobContext) -> dict:
    raise jobs.JobFailed("bad_file")


@jobs.handler("test.progress")
def _progress(ctx: jobs.JobContext) -> dict:
    ctx.progress(3, 10)
    # Another transaction sees the progress while this one is still open.
    with STATE["admin"].connect() as c:
        STATE["seen_progress"] = c.execute(
            text("select progress_done, progress_total, status from platform.jobs where id = :i"), {"i": ctx.job_id}
        ).one()
    return {}


@pytest.fixture(scope="module")
def db():
    dbname = f"t_{uuid.uuid4().hex[:10]}"
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f"create database {dbname}"))
    url = make_url(ADMIN_URL).set(database=dbname)
    owner = create_engine(url, isolation_level="AUTOCOMMIT")
    with owner.connect() as c:
        raw = c.connection.driver_connection  # psycopg, no placeholder parsing
        raw.execute(BOOTSTRAP.read_text())
        for f in sorted(MIGRATIONS.glob("*.sql")):
            raw.execute(f.read_text())
    eng = create_engine(url)

    @event.listens_for(eng, "connect")
    def _as_app_rw(dbapi_conn, _):
        with dbapi_conn.cursor() as cur:
            cur.execute("set role app_rw")
        dbapi_conn.commit()

    uow_mod.set_session_factory(sessionmaker(bind=eng, expire_on_commit=False))
    STATE["admin"] = owner
    yield owner
    uow_mod.set_session_factory(None)
    set_queue(None)
    eng.dispose()
    owner.dispose()
    with admin.connect() as c:
        c.execute(text(f"drop database {dbname} with (force)"))


@pytest.fixture()
def queue(db):
    q = FakeQueue()
    set_queue(q)
    CALLS.clear()
    yield q
    set_queue(None)


def P(business=A, user=ASHA, grant=None):
    return Principal(user_sub="sub", request_id="req-1", user_id=user, business_id=business, support_grant_id=grant)


def create(type_="test.ok", business=A, user=ASHA, key=None) -> uuid.UUID:
    with unit_of_work(P(business, user)) as uow:
        return jobs.create(uow, type_, natural_key=key)


def job(db, job_id):
    with db.connect() as c:
        return c.execute(text("select * from platform.jobs where id = :i"), {"i": job_id}).one()


def handle(q):
    return q.drain(jobs.handle_message)


# --- create, send, dedupe -----------------------------------------------------------


def test_create_sends_one_message_after_commit_and_marks_it_sent(db, queue):
    job_id = create()
    [m] = queue.sent
    assert m["type"] == "job.run" and m["job_id"] == str(job_id) and m["business_id"] == str(A)
    assert m["request_id"] == "req-1" and set(m) == {"type", "job_id", "outbox_id", "business_id", "request_id"}
    with db.connect() as c:
        sent_at = c.execute(text("select sent_at from platform.outbox where id = :i"), {"i": m["outbox_id"]}).scalar()
    assert sent_at is not None
    assert job(db, job_id).status == "queued" and job(db, job_id).actor_user_id == ASHA


def test_a_rolled_back_request_sends_nothing(db, queue):
    with pytest.raises(RuntimeError):
        with unit_of_work(P()) as uow:
            jobs.create(uow, "test.ok")
            raise RuntimeError("route failed")
    assert queue.sent == []


def test_the_same_natural_key_returns_the_same_job_within_a_business_only(db, queue):
    first = create(key="upload-1")
    assert create(key="upload-1") == first
    assert len(queue.sent) == 1
    other = create(business=B, user=RAVI, key="upload-1")
    assert other != first


def test_unknown_job_types_and_non_id_payloads_are_refused(db, queue):
    with pytest.raises(ValueError, match="no handler"):
        create("test.nobody")
    with unit_of_work(P()) as uow, pytest.raises(ValueError, match="IDs only"):
        outbox.emit(uow, "job.run", {"email": "a@b.c"})


# --- running ------------------------------------------------------------------------


def test_a_job_runs_once_in_its_own_business_however_often_it_is_delivered(db, queue):
    """AC-9 and AC-16: the second delivery is acknowledged without work, and the
    handler's unit of work sees only its own business's rows."""
    create(business=B, user=RAVI)
    job_id = create()
    message = queue.sent[-1]
    queue.sent.append(dict(message))  # SQS delivers twice
    assert handle(queue) == ["done", "done", "skipped"]
    a_calls = [c for c in CALLS if c[1] == job_id]
    assert len(a_calls) == 1
    _, _, business, actor, (seen, businesses) = a_calls[0]
    assert (business, actor, businesses) == (A, ASHA, 1)
    row = job(db, job_id)
    assert (row.status, row.attempt, row.result) == ("done", 1, {"seen_jobs": seen})


def test_the_message_business_is_not_trusted(db, queue):
    job_id = create()
    m = queue.sent.pop()
    m["business_id"] = str(B)
    assert jobs.handle_message(m) == "done"
    assert [c[2] for c in CALLS if c[1] == job_id] == [A]  # from claim_job, not the message


def test_a_failing_attempt_rolls_back_and_is_retried(db, queue):
    job_id = create("test.flaky")
    m = queue.sent[-1]
    assert jobs.handle_message(m) == "retry"
    row = job(db, job_id)
    assert (row.status, row.attempt, row.error_code) == ("failed_retryable", 1, "error")  # 'half-done' rolled back
    assert jobs.handle_message(m) == "done"
    row = job(db, job_id)
    assert (row.status, row.attempt, row.error_code) == ("done", 2, None)


def test_a_permanent_failure_is_not_retried(db, queue):
    job_id = create("test.bad_file")
    assert handle(queue) == ["failed"]
    assert (job(db, job_id).status, job(db, job_id).error_code) == ("failed", "bad_file")
    assert jobs.run(job_id) == "skipped"


def test_a_running_job_is_left_alone_until_its_lease_passes(db, queue):
    job_id = create()
    with db.connect() as c:
        c.execute(text("update platform.jobs set status = 'running', attempt = 1,"
                       " lease_until = now() + interval '5 minutes' where id = :i"), {"i": job_id})
    assert jobs.run(job_id) == "skipped"
    with db.connect() as c:  # the first attempt crashed; its lease runs out
        c.execute(text("update platform.jobs set lease_until = now() - interval '1 second' where id = :i"),
                  {"i": job_id})
    assert jobs.run(job_id) == "done"
    assert job(db, job_id).attempt == 2


def test_attempts_past_the_limit_fail_the_job(db, queue):
    job_id = create()
    with db.connect() as c:
        c.execute(text("update platform.jobs set status = 'failed_retryable', attempt = :n where id = :i"),
                  {"n": jobs.MAX_ATTEMPTS, "i": job_id})
    assert jobs.run(job_id) == "failed"
    assert (job(db, job_id).status, job(db, job_id).error_code) == ("failed", "attempts_exhausted")
    assert not [c for c in CALLS if c[1] == job_id]


def test_progress_is_visible_while_the_handler_runs(db, queue):
    create("test.progress")
    assert handle(queue) == ["done"]
    assert tuple(STATE["seen_progress"]) == (3, 10, "running")


def test_two_workers_claiming_at_once_run_the_job_once(db, queue):
    job_id = create()
    results = []
    threads = [threading.Thread(target=lambda: results.append(jobs.run(job_id))) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["done", "skipped", "skipped", "skipped"]


# --- outbox sweep -------------------------------------------------------------------


class Broken:
    def send(self, body):
        raise ConnectionError("SQS unreachable")


def test_the_sweep_resends_what_the_after_commit_send_lost(db, queue):
    set_queue(Broken())
    job_id = create()  # the after-commit send fails; the commit stands (logged)
    assert job(db, job_id).status == "queued"
    set_queue(queue)
    assert outbox.sweep() == 0  # not yet 30 s old
    with db.connect() as c:
        c.execute(text("update platform.outbox set created_at = now() - interval '1 minute' where sent_at is null"))
    assert outbox.sweep() == 1
    assert queue.sent[-1]["job_id"] == str(job_id)
    assert outbox.sweep() == 0  # marked sent
    assert handle(queue) == ["done"]


# --- what app_rw and app_ro can do directly ---------------------------------------


def test_rls_hides_other_businesses_and_support_principals_see_nothing(db, queue):
    a_job = create()
    with unit_of_work(P(business=B, user=RAVI)) as uow:
        assert jobs.get(uow, a_job) is None
        assert all(j.id != a_job for j in jobs.recent(uow))
        assert uow.tx.execute(text("select count(*) from platform.jobs where id = :i"), {"i": a_job}).scalar() == 0
        assert uow.tx.execute(text("select count(*) from platform.outbox where business_id = :b"), {"b": A}).scalar() == 0
    with unit_of_work(P(), read_only=True) as uow:
        assert jobs.get(uow, a_job).id == a_job  # app_ro reads its own business
    with unit_of_work(P(grant=uuid.uuid4())) as uow:
        assert jobs.get(uow, a_job) is None
    with pytest.raises(ProgrammingError, match="row-level security"):
        with unit_of_work(P(business=B, user=RAVI)) as uow:
            uow.tx.execute(text("insert into platform.jobs (id, business_id, type) values (:i, :b, 'test.ok')"),
                           {"i": uuid.uuid4(), "b": A})


def test_app_rw_cannot_claim_by_hand_or_change_attempts_and_app_ro_cannot_claim(db, queue):
    job_id = create()
    with pytest.raises(ProgrammingError, match="permission denied"):
        with unit_of_work(P()) as uow:
            uow.tx.execute(text("update platform.jobs set attempt = 0, lease_until = null where id = :i"),
                           {"i": job_id})
    with pytest.raises(DBAPIError, match="permission denied"):
        with unit_of_work(P(), read_only=True) as uow:
            uow.tx.execute(text("select * from platform.claim_job(:i, 60)"), {"i": job_id})
    with db.connect() as c:
        public = c.execute(text(
            "select count(*) from information_schema.routine_privileges where routine_schema = 'platform'"
            " and routine_name in ('claim_job', 'sweep_outbox', 'mark_outbox_sent') and grantee = 'PUBLIC'"
        )).scalar()
        owners = {r[0] for r in c.execute(text(
            "select pg_get_userbyid(proowner) from pg_proc where proname in"
            " ('claim_job', 'sweep_outbox', 'mark_outbox_sent')"))}
    assert public == 0 and owners == {"platform_ops"}

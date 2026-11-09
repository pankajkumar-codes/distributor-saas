"""The audit log's CSV export (LLD-2 §7 [D, RM42-11], AC2-12) on PostgreSQL as app_rw,
with the job run through the fake queue and the file in a local object store.

Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import csv
import io
import uuid

import pytest

from platform_common import jobs
from platform_common.queue import FakeQueue, set_queue
from platform_common.storage import LocalObjectStore, set_store

from .conftest import PG_ADMIN_URL, PG_OWNER, REPO, seed_member
from .test_team_api_postgres import H, join, owner_sql, uid
from .test_team_api_postgres import team as team_env  # noqa: F401  (a fixture)

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


@pytest.fixture()
def team(team_env, tmp_path):  # noqa: F811
    """The team routes' database plus refdata (audit.export_max_rows), a fake jobs queue
    and a local object store."""
    from migrator.refdata import load

    with PG_OWNER["engine"].connect() as c:
        load(c.connection.driver_connection, REPO / "refdata")
    queue, store = FakeQueue(), LocalObjectStore(tmp_path)
    set_queue(queue)
    set_store(store)
    try:
        yield (*team_env, queue, store)
    finally:
        set_queue(None)
        set_store(None)


def export(client, tid, by="alice", key=None, **filters):
    return client.post(f"/api/v1/b/{tid}/audit-log/exports", json=filters,
                       headers={**H(by), "idempotency-key": key or str(uuid.uuid4())})


def status(client, tid, job_id, by="alice"):
    return client.get(f"/api/v1/b/{tid}/audit-log/exports/{job_id}", headers=H(by))


def seed_row(tid, sub, action="returns.unlock", reason="filed twice", data="{}"):
    owner_sql(
        "insert into platform.audit_log (id, business_id, user_id, action, target_kind, reason, data, request_id)"
        " values (gen_random_uuid(), :b, :u, :a, 'return_instance', :r, cast(:d as jsonb), 'seed')",
        b=tid, u=uid(sub), a=action, r=reason, d=data,
    )


def csv_rows(store, tid, job_id) -> list[list[str]]:
    body = store.get_bytes(uuid.UUID(tid), f"audit-exports/b/{tid}/{job_id}/audit-log.csv").decode("utf-8-sig")
    return list(csv.reader(io.StringIO(body)))


def test_an_export_is_logged_and_writes_what_the_list_shows(team):
    client, _, mail, tid, queue, store = team
    join(client, mail, tid, "bob", "billing")
    seed_row(tid, "alice", reason="=HYPERLINK(\"http://x\")", data='{"email": "a@b.c", "period": "2026-10"}')

    r = export(client, tid)
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    [row] = owner_sql("select user_id, target_kind, data from platform.audit_log where action = 'audit.export'"
                      " and business_id = :b", b=tid)
    assert str(row.user_id) == uid("alice") and row.target_kind == "business"
    assert row.data["kind"] is None and row.data["actor"] is None and set(row.data) == {"kind", "actor", "from", "to"}
    assert status(client, tid, job_id).json() == {"status": "preparing", "url": None, "rows": None, "error_code": None}

    assert queue.drain(jobs.handle_message) == [jobs.DONE]
    ready = status(client, tid, job_id).json()
    assert ready["status"] == "ready" and ready["url"] and ready["rows"] == 5

    header, *body = csv_rows(store, tid, job_id)
    assert header == ["When (IST)", "Who", "What happened", "Reason or detail"]
    # Newest first, the export's own row included; names as the list shows them.
    assert [b[2] for b in body] == ["Exported the audit log", "Unlocked a filed period", "Joined the business",
                                    "Invited a member", "Created the business"]
    assert body[0][1] == "alice@debug.invalid" and body[2][1] == "bob@debug.invalid"
    # A formula in a reason is printed as text, and data outside the allowlist never leaves.
    assert body[1][3].startswith("'=HYPERLINK")
    assert "a@b.c" not in "".join(sum(body, [])) and body[3][3] == "role: billing"


def test_filters_narrow_the_file_like_the_list(team):
    client, _, mail, tid, queue, store = team
    join(client, mail, tid, "bob", "billing")
    job_id = export(client, tid, kind="team_settings", actor=uid("bob")).json()["job_id"]
    queue.drain(jobs.handle_message)
    _, *body = csv_rows(store, tid, job_id)
    assert [b[2] for b in body] == ["Joined the business"]
    reversed_range = export(client, tid, **{"from": "2026-11-09", "to": "2026-11-01"})
    assert (reversed_range.status_code, reversed_range.json()["error"]["code"]) == (422, "date_range_reversed")


def test_a_retry_with_the_same_key_is_the_same_export(team):
    client, _, _, tid, queue, _ = team
    first, again = export(client, tid, key="k-1"), export(client, tid, key="k-1")
    assert first.json() == again.json()
    assert len(owner_sql("select 1 from platform.audit_log where action = 'audit.export' and business_id = :b", b=tid)) == 1
    assert len(queue.sent) == 1


def test_only_owner_and_admin_and_only_their_business(team):
    client, _, _, tid, queue, _ = team
    for sub, role in (("bill", "billing"), ("cathy", "ca"), ("erin", "admin")):
        seed_member(tid, sub, role)
    job_id = export(client, tid).json()["job_id"]
    for sub in ("bill", "cathy"):
        assert export(client, tid, by=sub).status_code == 404
        assert status(client, tid, job_id, by=sub).status_code == 404
    assert export(client, tid, by="erin").status_code == 202
    assert status(client, tid, job_id, by="erin").status_code == 200
    other = client.post("/api/v1/identity/tenants", json={"name": "O"}, headers=H("olga")).json()["id"]
    assert status(client, other, job_id, by="olga").status_code == 404  # another business's job
    assert status(client, tid, uuid.uuid4()).status_code == 404


def test_a_job_whose_asker_lost_audit_view_writes_nothing(team):
    client, _, _, tid, queue, store = team
    seed_member(tid, "erin", "admin")
    job_id = export(client, tid, by="erin").json()["job_id"]
    owner_sql("update identity.memberships set role = 'billing' where business_id = :b and user_id = :u",
              b=tid, u=uid("erin"))
    assert queue.drain(jobs.handle_message) == [jobs.FAILED]
    assert status(client, tid, job_id).json()["error_code"] == "not_allowed"
    assert store.head(uuid.UUID(tid), f"audit-exports/b/{tid}/{job_id}/audit-log.csv") is None


def test_more_rows_than_the_cap_fails_with_narrow_filter(team, monkeypatch):
    from app.modules.identity import audit_export

    client, _, _, tid, queue, store = team
    for _ in range(3):
        seed_row(tid, "alice")
    monkeypatch.setattr(audit_export, "value_on", lambda tx, key, on: 3)  # 3 seeded + create + export = 5
    job_id = export(client, tid).json()["job_id"]
    assert queue.drain(jobs.handle_message) == [jobs.FAILED]
    assert status(client, tid, job_id).json() == {"status": "failed", "url": None, "rows": None,
                                                  "error_code": "narrow_filter"}
    assert store.head(uuid.UUID(tid), f"audit-exports/b/{tid}/{job_id}/audit-log.csv") is None


def test_a_file_that_is_gone_or_a_day_old_reports_expired(team):
    client, _, _, tid, queue, store = team
    gone, old = export(client, tid).json()["job_id"], export(client, tid).json()["job_id"]
    queue.drain(jobs.handle_message)
    assert status(client, tid, gone).json()["status"] == "ready"
    (store.root / f"audit-exports/b/{tid}/{gone}/audit-log.csv").unlink()  # S3's lifecycle rule ran
    owner_sql("update platform.jobs set updated_at = now() - interval '25 hours' where id = :id", id=old)
    for job_id in (gone, old):  # the file is still there for `old`; the rule may just not have run yet
        assert status(client, tid, job_id).json() == {"status": "expired", "url": None, "rows": None,
                                                      "error_code": None}

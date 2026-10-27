"""GET /b/{id}/jobs[/{job_id}] on PostgreSQL as app_rw (LLD-0 §3.7): every role sees its
own business's jobs; another business's job is the same 404 as an unknown one.

Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import uuid

import pytest

from app.modules.identity.tests.conftest import PG_ADMIN_URL, as_user, seed_member
from platform_common import jobs
from platform_common.queue import FakeQueue, set_queue
from platform_common.uow import Principal, unit_of_work

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


@jobs.handler("test.api")
def _noop(ctx):
    return {"rows": 3}


def business(client, sub):
    r = client.post("/api/v1/identity/tenants", json={"name": f"{sub} Co"}, headers=as_user(sub))
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def test_job_status_for_every_role_and_404_across_businesses(pg_client):
    client, _ = pg_client
    queue = FakeQueue()
    set_queue(queue)
    try:
        a, b = business(client, "alice"), business(client, "bob")
        with unit_of_work(Principal(user_sub="alice", request_id="t", business_id=uuid.UUID(a))) as uow:
            job_id = jobs.create(uow, "test.api", natural_key="x")
        url = f"/api/v1/b/{a}/jobs/{job_id}"
        r = client.get(url, headers=as_user("alice"))
        assert r.status_code == 200 and r.json()["status"] == "queued" and r.json()["type"] == "test.api"

        assert queue.drain(jobs.handle_message) == ["done"]
        done = client.get(url, headers=as_user("alice")).json()
        assert done["status"] == "done" and done["result"] == {"rows": 3}
        for role in ("admin", "billing", "ca"):
            seed_member(a, f"m-{role}", role)
            assert client.get(url, headers=as_user(f"m-{role}")).status_code == 200
        recent = client.get(f"/api/v1/b/{a}/jobs?recent=1", headers=as_user("m-ca")).json()["items"]
        assert [j["id"] for j in recent] == [str(job_id)]

        unknown = client.get(f"/api/v1/b/{b}/jobs/{uuid.uuid4()}", headers=as_user("bob"))
        cross = client.get(f"/api/v1/b/{b}/jobs/{job_id}", headers=as_user("bob"))
        assert cross.status_code == unknown.status_code == 404 and cross.json() == unknown.json()
        assert client.get(url, headers=as_user("bob")).status_code == 404  # not a member of a
        assert client.get(f"/api/v1/b/{b}/jobs?recent=1", headers=as_user("bob")).json()["items"] == []
        assert client.get(f"/api/v1/b/{a}/jobs/not-a-uuid", headers=as_user("alice")).status_code == 404
    finally:
        set_queue(None)

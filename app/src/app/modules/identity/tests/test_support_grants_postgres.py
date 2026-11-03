"""Support grants: the owner's side (LLD-2 §6.1, NF-1) and support's own list (§6.2), on
PostgreSQL as app_rw with FORCE row-level security. Callers are X-Debug-User users.

Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import threading
import uuid
from datetime import datetime, timedelta

import pytest

from .conftest import PG_ADMIN_URL, PG_OWNER, REPO
from .test_team_api_postgres import H, actions, join, owner_sql
from .test_team_api_postgres import team as team_env  # noqa: F401  (a fixture)

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


@pytest.fixture()
def team(team_env):  # noqa: F811
    """The team routes' database plus refdata (support.grant_hours), loaded as the
    migrator does."""
    from migrator.refdata import load

    with PG_OWNER["engine"].connect() as c:
        load(c.connection.driver_connection, REPO / "refdata")
    return team_env


def url(tid, path=""):
    return f"/api/v1/b/{tid}/support-grants{path}"


def give(client, tid, reason=None, by="alice"):
    return client.post(url(tid), json={} if reason is None else {"reason": reason}, headers=H(by))


def grants(client, tid, by="alice"):
    r = client.get(url(tid), headers=H(by))
    assert r.status_code == 200, r.text
    return r.json()["grants"]


def test_an_owner_gives_access_for_the_refdata_hours_and_it_is_audited(team):
    client, _, _, tid = team
    r = give(client, tid, reason="  Invoice PDF looks wrong  ")
    assert r.status_code == 201, r.text
    g = r.json()
    assert (g["status"], g["reason"], g["ended_at"], g["pages_viewed"]) == (
        "active",
        "Invoice PDF looks wrong",
        None,
        0,
    )
    assert g["given_by"]["name"]
    length = datetime.fromisoformat(g["expires_at"]) - datetime.fromisoformat(g["given_at"])
    assert timedelta(hours=24) - timedelta(seconds=5) < length <= timedelta(hours=24)  # support.grant_hours
    [row] = owner_sql(
        "select reason, data, target_kind, target_id from platform.audit_log where action = 'support.grant' and business_id = :b",
        b=tid,
    )
    assert (row.reason, row.target_kind, str(row.target_id)) == ("Invoice PDF looks wrong", "support_grant", g["id"])
    assert set(row.data) == {"expires_at"}


def test_a_new_grant_ends_the_active_one(team):
    client, _, _, tid = team
    first = give(client, tid).json()
    second = give(client, tid).json()
    listed = grants(client, tid)
    assert [g["id"] for g in listed] == [second["id"], first["id"]]
    assert [g["status"] for g in listed] == ["active", "revoked"]
    assert listed[1]["ended_by"]["user_id"] == listed[1]["given_by"]["user_id"]
    data = owner_sql(
        "select data from platform.audit_log where action = 'support.grant' order by at desc, id desc limit 1"
    )[0].data
    assert data["replaced"] == first["id"]
    # The replaced grant's end is its own revoke row, as an owner's revoke would be.
    [revoked] = owner_sql(
        "select target_id, reason from platform.audit_log where action = 'support.revoke' and business_id = :b", b=tid
    )
    assert (str(revoked.target_id), revoked.reason) == (first["id"], "replaced")
    assert actions(tid)[-2:] == ["support.revoke", "support.grant"]


def test_two_grants_at_once_leave_one_active(team):
    client, _, _, tid = team
    results = []
    threads = [threading.Thread(target=lambda: results.append(give(client, tid).status_code)) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == [201, 201]
    assert [g["status"] for g in grants(client, tid)].count("active") == 1


def test_revoke_ends_it_once(team):
    client, _, _, tid = team
    g = give(client, tid).json()
    r = client.post(url(tid, f"/{g['id']}/revoke"), headers=H("alice"))
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["ended_by"]["user_id"]) == ("revoked", g["given_by"]["user_id"])
    again = client.post(url(tid, f"/{g['id']}/revoke"), headers=H("alice"))
    assert (again.status_code, again.json()["error"]["code"]) == (409, "grant_ended")
    assert actions(tid).count("support.revoke") == 1


def test_an_expired_grant_reads_as_expired_and_cant_be_revoked(team):
    client, _, _, tid = team
    g = give(client, tid).json()
    owner_sql(
        "update identity.support_grants set starts_at = now() - interval '25 hours',"
        " expires_at = now() - interval '1 hour' where id = :g",
        g=g["id"],
    )
    [listed] = grants(client, tid)
    assert listed["status"] == "expired" and listed["ended_at"] == listed["expires_at"] and listed["ended_by"] is None
    r = client.post(url(tid, f"/{g['id']}/revoke"), headers=H("alice"))
    assert (r.status_code, r.json()["error"]["code"]) == (409, "grant_ended")


def test_pages_viewed_counts_this_grants_support_views_only(team):
    client, _, _, tid = team
    first = give(client, tid).json()
    second = give(client, tid).json()
    for gid, n in ((first["id"], 2), (second["id"], 3)):
        for _ in range(n):
            owner_sql(
                "insert into platform.audit_log (id, business_id, user_id, support_grant_id, action, target_kind,"
                " data, request_id) values (gen_random_uuid(), :b, null, :g, 'support.view', 'route', '{}', 't')",
                b=tid,
                g=gid,
            )
    assert {g["id"]: g["pages_viewed"] for g in grants(client, tid)} == {first["id"]: 2, second["id"]: 3}


@pytest.mark.parametrize(("role", "can_list"), [("admin", True), ("billing", False), ("ca", False)])
def test_only_the_owner_gives_or_revokes_and_owner_or_admin_lists(team, role, can_list):
    client, _, mail, tid = team
    join(client, mail, tid, "bob", role)
    g = give(client, tid).json()
    assert give(client, tid, by="bob").status_code == 404
    assert client.post(url(tid, f"/{g['id']}/revoke"), headers=H("bob")).status_code == 404
    listed = client.get(url(tid), headers=H("bob"))
    assert listed.status_code == (200 if can_list else 404)
    assert [x["status"] for x in grants(client, tid)] == ["active"]


def test_another_businesss_grant_is_not_found(team):
    client, _, _, tid = team
    other = client.post("/api/v1/identity/tenants", json={"name": "Bob Co"}, headers=H("bob")).json()["id"]
    theirs = give(client, other, by="bob").json()
    for gid in (theirs["id"], str(uuid.uuid4())):
        r = client.post(url(tid, f"/{gid}/revoke"), headers=H("alice"))
        assert r.status_code == 404
    assert grants(client, tid) == []
    assert [g["status"] for g in grants(client, other, by="bob")] == ["active"]


def test_a_reason_over_500_characters_is_refused(team):
    client, _, _, tid = team
    assert give(client, tid, reason="x" * 501).status_code == 422
    assert grants(client, tid) == []


SUPPORT = "sam-support"


def support_user(sub=SUPPORT, *, totp=True):
    [row] = owner_sql("select identity.dev_ensure_user(:s) as id", s=sub)
    owner_sql(
        "update identity.users set is_support = true, totp_enabled_at = case when :t then now() end where id = :u",
        u=row.id,
        t=totp,
    )
    return row.id


def support_grants(client, sub=SUPPORT):
    return client.get("/api/v1/support/grants", headers=H(sub))


def test_support_under_a_grant_cant_give_revoke_or_list_grants(team):
    client, _, _, tid = team
    support_user()
    g = give(client, tid).json()
    assert give(client, tid, by=SUPPORT).status_code == 404
    assert client.post(url(tid, f"/{g['id']}/revoke"), headers=H(SUPPORT)).status_code == 404
    assert client.get(url(tid), headers=H(SUPPORT)).status_code == 404
    assert [x["status"] for x in grants(client, tid)] == ["active"]
    assert "support.revoke" not in actions(tid)
    # Each request resolved as support under the grant (its view row was recorded first),
    # so the 404s are the permission refusing support, not an unresolved caller.
    views = owner_sql(
        "select support_grant_id, data->>'route_template' as route from platform.audit_log"
        " where business_id = :b and action = 'support.view' order by at, id",
        b=tid,
    )
    assert [(str(v.support_grant_id), v.route) for v in views] == [
        (g["id"], "/b/{business_id}/support-grants"),
        (g["id"], "/b/{business_id}/support-grants/{grant_id}/revoke"),
        (g["id"], "/b/{business_id}/support-grants"),
    ]


def test_support_lists_the_businesses_it_may_open_now(team):
    client, _, _, tid = team
    support_user()
    other = client.post("/api/v1/identity/tenants", json={"name": "Bob Co"}, headers=H("bob")).json()["id"]
    closed = client.post("/api/v1/identity/tenants", json={"name": "Carol Co"}, headers=H("carol")).json()["id"]
    assert support_grants(client).json() == {"grants": []}
    mine = give(client, tid).json()
    ended = give(client, other, by="bob").json()
    client.post(url(other, f"/{ended['id']}/revoke"), headers=H("bob"))
    give(client, closed, by="carol")
    owner_sql("update identity.businesses set status = 'closed' where id = :b", b=closed)
    r = support_grants(client)
    assert r.status_code == 200, r.text
    assert r.json()["grants"] == [
        {"grant_id": mine["id"], "business_id": tid, "business_name": "Alice Co", "expires_at": mine["expires_at"]}
    ]
    owner_sql("update identity.support_grants set expires_at = now() - interval '1 second' where id = :g", g=mine["id"])
    assert support_grants(client).json() == {"grants": []}


@pytest.mark.parametrize("who", ["alice", "support-without-totp"])
def test_support_grants_is_not_found_for_anyone_else(team, who):
    client, _, _, tid = team
    if who != "alice":
        support_user(who, totp=False)
    give(client, tid)
    assert support_grants(client, who).status_code == 404

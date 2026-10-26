import uuid

import pytest
from sqlalchemy import func, select

from app.modules.identity import api as main
from app.modules.identity.models import Business, User

from .conftest import as_user

ALICE, BOB, CAROL = "user-alice", "user-bob", "user-carol"


def make_tenant(client, user, name):
    r = client.post("/api/v1/identity/tenants", json={"name": name}, headers=as_user(user))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_requires_authentication(client):
    assert client.get("/api/v1/identity/tenants").status_code == 401


def test_creator_becomes_owner(client):
    tid = make_tenant(client, ALICE, "Vashi Essentials")
    r = client.get(f"/api/v1/identity/tenants/{tid}", headers=as_user(ALICE))
    assert r.status_code == 200
    assert r.json()["role"] == "owner"


def test_list_only_shows_own_tenants(client):
    make_tenant(client, ALICE, "Alice Co")
    make_tenant(client, BOB, "Bob Co")
    names = [t["name"] for t in client.get("/api/v1/identity/tenants", headers=as_user(ALICE)).json()]
    assert names == ["Alice Co"]


@pytest.mark.parametrize(
    "method,path_suffix,body",
    [
        ("get", "", None),
        ("get", "/members", None),
        ("get", "/audit", None),
        ("post", "/members", {"user_sub": "user-bob", "role": "admin"}),
    ],
)
def test_other_tenant_looks_like_it_does_not_exist(client, method, path_suffix, body):
    alice_tenant = make_tenant(client, ALICE, "Alice Co")
    missing = str(uuid.uuid4())
    kwargs = {"headers": as_user(BOB)}
    if body is not None:
        kwargs["json"] = body
    real = getattr(client, method)(f"/api/v1/identity/tenants/{alice_tenant}{path_suffix}", **kwargs)
    fake = getattr(client, method)(f"/api/v1/identity/tenants/{missing}{path_suffix}", **kwargs)
    assert real.status_code == fake.status_code == 404
    assert real.json() == fake.json()


def test_garbage_tenant_id_is_404(client):
    assert client.get("/api/v1/identity/tenants/not-a-uuid", headers=as_user(ALICE)).status_code == 404


def test_multi_tenant_user_sees_each_tenant_with_its_own_role(client):
    t1 = make_tenant(client, ALICE, "Alice Co")
    t2 = make_tenant(client, BOB, "Bob Co")
    r = client.post(f"/api/v1/identity/tenants/{t2}/members", json={"user_sub": ALICE, "role": "ca"}, headers=as_user(BOB))
    assert r.status_code == 201
    roles = {t["id"]: t["role"] for t in client.get("/api/v1/identity/tenants", headers=as_user(ALICE)).json()}
    assert roles == {t1: "owner", t2: "ca"}


def test_viewer_cannot_add_members_or_read_audit(client):
    tid = make_tenant(client, ALICE, "Alice Co")
    client.post(f"/api/v1/identity/tenants/{tid}/members", json={"user_sub": BOB, "role": "ca"}, headers=as_user(ALICE))
    r = client.post(f"/api/v1/identity/tenants/{tid}/members", json={"user_sub": CAROL, "role": "billing"}, headers=as_user(BOB))
    assert r.status_code == 404
    assert client.get(f"/api/v1/identity/tenants/{tid}/audit", headers=as_user(BOB)).status_code == 404


def test_admin_cannot_create_owner(client):
    tid = make_tenant(client, ALICE, "Alice Co")
    client.post(f"/api/v1/identity/tenants/{tid}/members", json={"user_sub": BOB, "role": "admin"}, headers=as_user(ALICE))
    r = client.post(f"/api/v1/identity/tenants/{tid}/members", json={"user_sub": CAROL, "role": "owner"}, headers=as_user(BOB))
    assert r.status_code == 404


def test_duplicate_member_is_conflict(client):
    tid = make_tenant(client, ALICE, "Alice Co")
    body = {"user_sub": BOB, "role": "billing"}
    assert client.post(f"/api/v1/identity/tenants/{tid}/members", json=body, headers=as_user(ALICE)).status_code == 201
    assert client.post(f"/api/v1/identity/tenants/{tid}/members", json=body, headers=as_user(ALICE)).status_code == 409


def test_sensitive_actions_are_audited(client):
    tid = make_tenant(client, ALICE, "Alice Co")
    client.post(f"/api/v1/identity/tenants/{tid}/members", json={"user_sub": BOB, "role": "billing"}, headers=as_user(ALICE))
    actions = [e["action"] for e in client.get(f"/api/v1/identity/tenants/{tid}/audit", headers=as_user(ALICE)).json()]
    assert sorted(actions) == ["member.added", "tenant.created"]


def test_debug_header_is_ignored_outside_local_and_test(client, monkeypatch):
    monkeypatch.setenv("PLATFORM_ENV", "prod")
    assert client.get("/api/v1/identity/tenants", headers=as_user(ALICE)).status_code == 401


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_verified_caller_without_a_user_row_is_session_invalid_outside_local_and_test(client, monkeypatch, env):
    """In AWS only S1 sign-up creates identity.users rows; the X-Debug-User upsert never runs."""
    monkeypatch.setenv("PLATFORM_ENV", env)
    from app import api as app_api

    event = {"requestContext": {"authorizer": {"jwt": {"claims": {"sub": ALICE}}}}}

    class InjectEvent:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            scope["aws.event"] = event
            await self.app(scope, receive, send)

    from fastapi.testclient import TestClient

    r = TestClient(InjectEvent(app_api.app)).post("/api/v1/identity/tenants", json={"name": "Via JWT"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "session_invalid"
    with main._factory()() as s:
        assert s.scalar(select(func.count()).select_from(User)) == 0
        assert s.scalar(select(func.count()).select_from(Business)) == 0


@pytest.mark.parametrize("env", ["staging", "prod", ""])
def test_debug_user_upsert_refuses_outside_local_and_test(client, monkeypatch, env):
    monkeypatch.setenv("PLATFORM_ENV", env)
    with main._factory()() as s, pytest.raises(RuntimeError, match="local or test"):
        main.debug_user_id(s, ALICE)

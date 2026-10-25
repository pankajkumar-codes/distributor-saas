"""Onboarding and tenant isolation, end to end (TEST_PLAN: tenant isolation)."""

import uuid

from conftest import RUN, new_tenant


def test_health(anon):
    assert anon.get("/api/v1/health").json() == {"status": "ok"}


def test_no_credentials_is_401(anon):
    assert anon.get("/api/v1/identity/tenants").status_code == 401
    assert anon.post("/api/v1/identity/tenants", json={"name": "x"}).status_code == 401


def test_forged_bearer_token_is_rejected(anon):
    r = anon.get("/api/v1/identity/tenants", headers={"authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401


def test_onboarding_creator_is_owner_and_it_is_audited(alice):
    tid = new_tenant(alice, "Onboard")
    assert alice.get(f"/api/v1/identity/tenants/{tid}").json()["role"] == "owner"
    assert tid in [t["id"] for t in alice.get("/api/v1/identity/tenants").json()]
    actions = [e["action"] for e in alice.get(f"/api/v1/identity/tenants/{tid}/audit").json()]
    assert actions == ["tenant.created"]


def test_other_tenant_is_indistinguishable_from_missing(alice, bob):
    tid = new_tenant(alice, "Private")
    missing = str(uuid.uuid4())
    for suffix in ("", "/members", "/audit"):
        real = bob.get(f"/api/v1/identity/tenants/{tid}{suffix}")
        fake = bob.get(f"/api/v1/identity/tenants/{missing}{suffix}")
        assert real.status_code == fake.status_code == 404, suffix
        assert real.json() == fake.json()
    assert tid not in [t["id"] for t in bob.get("/api/v1/identity/tenants").json()]


def test_outsider_cannot_join_by_guessing_the_id(alice, bob):
    tid = new_tenant(alice, "Guarded")
    r = bob.post(f"/api/v1/identity/tenants/{tid}/members", json={"user_sub": bob.sub, "role": "owner"})
    assert r.status_code == 404
    subs = [m["user_sub"] for m in alice.get(f"/api/v1/identity/tenants/{tid}/members").json()]
    assert subs == [alice.sub]


def test_invited_viewer_reads_but_cannot_manage(alice, debug_user):
    tid = new_tenant(alice, "Team")
    viewer = debug_user("viewer")
    assert alice.post(f"/api/v1/identity/tenants/{tid}/members", json={"user_sub": viewer.sub, "role": "viewer"}).status_code == 201
    assert viewer.get(f"/api/v1/identity/tenants/{tid}").json()["role"] == "viewer"
    assert viewer.get(f"/api/v1/identity/tenants/{tid}/audit").status_code == 404
    r = viewer.post(f"/api/v1/identity/tenants/{tid}/members", json={"user_sub": f"e2e-{RUN}-x", "role": "admin"})
    assert r.status_code == 404
    actions = sorted(e["action"] for e in alice.get(f"/api/v1/identity/tenants/{tid}/audit").json())
    assert actions == ["member.added", "tenant.created"]


def test_user_in_two_tenants_gets_each_tenants_role(alice, debug_user):
    dual = debug_user("dual")
    own = new_tenant(dual, "Dual own")
    theirs = new_tenant(alice, "Dual theirs")
    alice.post(f"/api/v1/identity/tenants/{theirs}/members", json={"user_sub": dual.sub, "role": "sales"})
    roles = {t["id"]: t["role"] for t in dual.get("/api/v1/identity/tenants").json()}
    assert roles == {own: "owner", theirs: "sales"}
    assert dual.post(f"/api/v1/identity/tenants/{theirs}/members", json={"user_sub": "x", "role": "viewer"}).status_code == 404


def test_debug_header_is_ignored_when_real_auth_is_on(anon, debug_mode):
    if debug_mode:
        return  # locally the header *is* the sign-in
    assert anon.get("/api/v1/identity/tenants", headers={"x-debug-user": "mallory"}).status_code == 401


def test_errors_do_not_leak_internals(alice):
    for r in (
        alice.get("/api/v1/identity/tenants/not-a-uuid"),
        alice.post("/api/v1/identity/tenants", json={"name": ""}),
        alice.post("/api/v1/identity/tenants", content=b"{not json", headers={"content-type": "application/json"}),
    ):
        assert r.status_code in (404, 422)
        body = r.text.lower()
        for leak in ("traceback", "sqlalchemy", "psycopg", "select ", "password"):
            assert leak not in body, (leak, r.text)

"""Onboarding and tenant isolation, end to end (TEST_PLAN: tenant isolation)."""

import uuid

from conftest import add_member, new_tenant


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
    actions = [e["action"] for e in alice.get(f"/api/v1/b/{tid}/audit-log").json()["items"]]
    assert actions == ["business.create"]


def test_other_tenant_is_indistinguishable_from_missing(alice, bob):
    tid = new_tenant(alice, "Private")
    missing = str(uuid.uuid4())
    for path in ("/api/v1/identity/tenants/{}", "/api/v1/b/{}/members", "/api/v1/b/{}/audit-log"):
        real = bob.get(path.format(tid))
        fake = bob.get(path.format(missing))
        assert real.status_code == fake.status_code == 404, path
        assert real.json() == fake.json()
    assert tid not in [t["id"] for t in bob.get("/api/v1/identity/tenants").json()]


def test_outsider_cannot_invite_into_a_guessed_business(alice, bob):
    tid = new_tenant(alice, "Guarded")
    r = bob.post(
        f"/api/v1/b/{tid}/invitations",
        json={"email": "bob@example.com", "role": "admin"},
        headers={"idempotency-key": str(uuid.uuid4())},
    )
    assert r.status_code == 404
    emails = [m["email"] for m in alice.get(f"/api/v1/b/{tid}/members").json()["members"]]
    assert len(emails) == 1


def test_invited_ca_reads_but_cannot_manage(alice, debug_user):
    tid = new_tenant(alice, "Team")
    ca = debug_user("ca")
    add_member(alice, tid, ca, "ca")
    assert ca.get(f"/api/v1/identity/tenants/{tid}").json()["role"] == "ca"
    assert ca.get(f"/api/v1/b/{tid}/audit-log").status_code == 404
    assert ca.get(f"/api/v1/b/{tid}/members").status_code == 404
    actions = sorted(e["action"] for e in alice.get(f"/api/v1/b/{tid}/audit-log").json()["items"])
    assert actions == ["business.create", "member.accept", "member.invite"]


def test_user_in_two_tenants_gets_each_tenants_role(alice, debug_user):
    dual = debug_user("dual")
    own = new_tenant(dual, "Dual own")
    theirs = new_tenant(alice, "Dual theirs")
    add_member(alice, theirs, dual, "billing")
    roles = {t["id"]: t["role"] for t in dual.get("/api/v1/identity/tenants").json()}
    assert roles == {own: "owner", theirs: "billing"}
    assert dual.get(f"/api/v1/b/{theirs}/members").status_code == 404


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

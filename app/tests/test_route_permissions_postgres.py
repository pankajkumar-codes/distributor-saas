"""Every business route declares one permission, and a role without it is refused (R4-M3, LLD-0 §7).

Two checks over the real app. The first reads the route table: each route under /api/v1/b/{business_id} carries exactly one
`require(Permission.X)`, so a new route cannot ship without choosing who may call it (a short allowlist names the ones
that deliberately have none). The second calls every such route as each role that lacks the permission, and as a signed-in
stranger who is no member, and expects the same 404 an unknown business gets. Nothing about an allowed role is asserted here:
the routes' own tests do that. Skipped unless PG_ADMIN_URL is set.
"""

import uuid

import pytest
from fastapi import APIRouter
from fastapi.routing import APIRoute

from app import api as app_api
from app.modules.identity.tests.conftest import PG_ADMIN_URL, as_user, seed_member
from platform_common.permissions import PERMISSION_ROLES

API = "/api/v1"
# Business routes that deliberately carry no `require(...)`, with the reason. They are still refused to a non-member.
ANY_MEMBER = "readable by every active member of the business: the app's shell needs it for every role"
NO_PERMISSION: dict[tuple[str, str], str] = {
    ("GET", "/b/{business_id}/home"): ANY_MEMBER,
    ("GET", "/b/{business_id}/profile"): ANY_MEMBER,
    ("GET", "/b/{business_id}/filing-profile"): ANY_MEMBER,
    ("GET", "/b/{business_id}/channels"): ANY_MEMBER,
    # Open question for the EM: every other returns route needs returns.prepare; the list is readable by billing too.
    ("GET", "/b/{business_id}/returns"): "readable by every active member today (open question: returns.prepare?)",
}
ROLES = ("owner", "admin", "billing", "ca")


def _permissions(dependant) -> list:
    found = []
    for dep in dependant.dependencies:
        if hasattr(dep.call, "permission"):
            found.append(dep.call.permission)
        found.extend(_permissions(dep))
    return found


def business_routes() -> list[tuple[APIRoute, str]]:
    """(route, method) for every route under /b/{business_id}, read from the routers the app includes (the mounted app wraps
    them, so the original routers are the ones that still show each route's dependencies)."""
    routers = {id(o): o for o in vars(app_api).values() if isinstance(o, APIRouter)}
    out = []
    for router in routers.values():
        for route in router.routes:
            if isinstance(route, APIRoute) and route.path.startswith("/b/{business_id}"):
                for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                    out.append((route, method))
    return out


def test_every_business_route_declares_exactly_one_permission():
    routes = business_routes()
    assert len(routes) > 100  # the table was found, not an empty one
    bad = []
    for route, method in routes:
        perms = _permissions(route.dependant)
        if (method, route.path) in NO_PERMISSION:
            continue
        if len(set(perms)) != 1:
            bad.append((method, route.path, [p.value for p in perms]))
    assert bad == [], f"routes without exactly one permission: {bad}"


def test_the_allowlist_has_no_stale_entries():
    present = {(m, r.path) for r, m in business_routes()}
    assert set(NO_PERMISSION) <= present


pytestmark_pg = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


def fill(path: str, business: str) -> str:
    out = path.replace("{business_id}", business)
    while "{" in out:
        start = out.index("{")
        end = out.index("}", start)
        out = out[:start] + str(uuid.uuid4()) + out[end + 1 :]
    return out


@pytestmark_pg
def test_a_role_without_the_permission_gets_the_same_404_on_every_route(pg_client):
    client, _ = pg_client
    made = client.post("/api/v1/identity/tenants", json={"name": "Perm Co"}, headers=as_user("owner-1"))
    assert made.status_code in (200, 201), made.text
    business = made.json()["id"]
    for sub, role in (("admin-1", "admin"), ("billing-1", "billing"), ("ca-1", "ca")):
        seed_member(business, sub, role)
    subs = {"owner": "owner-1", "admin": "admin-1", "billing": "billing-1", "ca": "ca-1"}
    # a signed-in person who belongs to some other business
    other = client.post("/api/v1/identity/tenants", json={"name": "Other Co"}, headers=as_user("stranger-1"))
    assert other.status_code in (200, 201), other.text

    wrong = []
    checked = 0
    for route, method in business_routes():
        (perm,) = set(_permissions(route.dependant)) or {None}
        url = fill(API + route.path, business)
        denied = [] if perm is None else [r for r in ROLES if r not in {x.value for x in PERMISSION_ROLES[perm]}]
        for who in [*denied, "stranger"]:
            sub = "stranger-1" if who == "stranger" else subs[who]
            headers = {**as_user(sub), "Idempotency-Key": uuid.uuid4().hex, "If-Match": "1"}
            r = client.request(method, url, headers=headers, json={} if method in ("POST", "PUT", "PATCH", "DELETE") else None)
            checked += 1
            if r.status_code != 404:
                wrong.append((who, method, route.path, r.status_code))
    assert checked > 200
    assert wrong == [], f"a role without the permission was not refused with 404: {wrong[:20]}"


@pytestmark_pg
def test_a_request_with_no_sign_in_is_refused_on_every_business_route(pg_client):
    client, _ = pg_client
    business = str(uuid.uuid4())
    wrong = []
    for route, method in business_routes():
        r = client.request(method, fill(API + route.path, business), json={} if method in ("POST", "PUT", "PATCH", "DELETE") else None)
        if r.status_code not in (401, 403):
            wrong.append((method, route.path, r.status_code))
    assert wrong == [], f"signed-out request was not refused: {wrong[:20]}"

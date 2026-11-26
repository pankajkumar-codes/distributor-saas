"""#472: every write route has a per-user, per-business limit or a written reason for having none, and every kind of
limit has its refdata row. A new route that names neither fails here, so it can't ship without a limit by accident."""

from pathlib import Path

import yaml
from fastapi import APIRouter
from fastapi.routing import APIRoute

from app import api as app_api
from app.ratelimits import API, KINDS, LIMITS, NO_LIMIT, key

WRITES = {"POST", "PUT", "PATCH", "DELETE"}
REFDATA = Path(__file__).resolve().parents[2] / "refdata" / "values" / "ratelimit.yaml"


def _routes() -> set[tuple[str, str]]:
    """(method, full path) for every route, read from the routers app.api includes under /api/v1 (newer FastAPI keeps
    them inside the included router rather than copying them onto the app), plus the app's own health check."""
    routers = {id(o): o for o in vars(app_api).values() if isinstance(o, APIRouter)}
    out = {(m, API + r.path) for router in routers.values() for r in router.routes if isinstance(r, APIRoute)
           for m in r.methods - {"HEAD", "OPTIONS"}}
    return out | {("GET", f"{API}/health")}


def test_every_write_route_has_a_limit_or_a_reason():
    writes = {(m, p) for m, p in _routes() if m in WRITES and not p.startswith("/api/v1/dev/")}
    assert len(writes) > 80  # the route table was found
    missing = sorted(writes - LIMITS.keys() - NO_LIMIT.keys())
    assert not missing, f"add these to app/ratelimits.py LIMITS (or NO_LIMIT with a reason): {missing}"


def test_every_listed_route_exists_and_none_is_listed_twice():
    routes = _routes()
    assert not sorted((LIMITS.keys() | NO_LIMIT.keys()) - routes), "a listed route no longer exists"
    assert not LIMITS.keys() & NO_LIMIT.keys()
    assert all(reason.strip() for reason in NO_LIMIT.values())


def test_every_kind_is_used_and_has_its_refdata_row():
    assert set(LIMITS.values()) == set(KINDS)
    rows = {r["key"]: r for r in yaml.safe_load(REFDATA.read_text())}
    for kind in KINDS:
        row = rows[key(kind)]
        assert row["type"] == "integer" and int(row["value"]) > 0 and row["kind"] == "product"


def test_every_router_is_included_with_the_throttle():
    """Each include_router in app.api passes THROTTLE, so every route runs app.ratelimits.throttle before its own
    dependencies (and so before any unit of work opens; the PostgreSQL tests would get a 500 otherwise)."""
    source = Path(app_api.__file__).read_text()
    includes = [line for line in source.splitlines() if "app.include_router(" in line]
    assert len(includes) > 20 and all("dependencies=THROTTLE" in line for line in includes)

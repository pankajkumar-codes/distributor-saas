from fastapi.testclient import TestClient

from app.api import app


def test_health():
    assert TestClient(app).get("/api/v1/health").json() == {"status": "ok"}


def test_every_route_is_under_api_v1():
    paths = [r.path for r in app.routes if getattr(r, "include_in_schema", False)]
    assert paths and all(p.startswith("/api/v1/") for p in paths), paths


def test_refusals_and_errors_use_the_platform_handlers():
    from platform_common.errors import AppError, Deny

    assert Deny in app.exception_handlers and AppError in app.exception_handlers
    assert Exception in app.exception_handlers

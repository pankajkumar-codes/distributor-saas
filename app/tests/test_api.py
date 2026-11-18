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


def test_every_response_carries_the_security_headers():
    client = TestClient(app, raise_server_exceptions=False)
    # an answer, a refusal for a missing token, and a path that does not exist
    for path in ("/api/v1/health", "/api/v1/me", "/api/v1/nothing-here"):
        h = client.get(path).headers
        assert h["x-content-type-options"] == "nosniff", path
        assert h["strict-transport-security"].startswith("max-age="), path
        assert h["x-frame-options"] == "DENY", path
        assert h["referrer-policy"] == "no-referrer", path
        assert "frame-ancestors 'none'" in h["content-security-policy"], path

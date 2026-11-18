from fastapi.testclient import TestClient

from app.api import app, asgi


def test_health():
    assert TestClient(app).get("/api/v1/health").json() == {"status": "ok"}


def test_every_route_is_under_api_v1():
    paths = [r.path for r in app.routes if getattr(r, "include_in_schema", False)]
    assert paths and all(p.startswith("/api/v1/") for p in paths), paths


def test_refusals_and_errors_use_the_platform_handlers():
    from platform_common.errors import AppError, Deny

    assert Deny in app.exception_handlers and AppError in app.exception_handlers
    assert Exception in app.exception_handlers


def _assert_headers(h, path):
    assert h["x-content-type-options"] == "nosniff", path
    assert h["strict-transport-security"].startswith("max-age="), path
    assert h["x-frame-options"] == "DENY", path
    assert h["referrer-policy"] == "no-referrer", path
    assert "frame-ancestors 'none'" in h["content-security-policy"], path


def test_every_response_carries_the_security_headers():
    # `asgi` is what Lambda and uvicorn run: the whole app wrapped, so even the 500 gets them
    client = TestClient(asgi, raise_server_exceptions=False)

    @app.get("/api/v1/_test_boom", include_in_schema=False)
    async def boom():
        raise RuntimeError("test only")

    try:
        # an answer, a refusal for a missing token, a 404, a 422 and a 500
        for path in ("/api/v1/health", "/api/v1/me", "/api/v1/nothing-here", "/api/v1/health?x=" + "a" * 5, "/api/v1/_test_boom"):
            _assert_headers(client.get(path).headers, path)
        assert client.get("/api/v1/_test_boom").status_code == 500
        # a validation error (422): a bad path parameter
        r = client.get("/api/v1/b/not-a-uuid/jobs/also-bad")
        _assert_headers(r.headers, "422 path")
        # HEAD and OPTIONS
        _assert_headers(client.head("/api/v1/health").headers, "HEAD")
        _assert_headers(client.options("/api/v1/health").headers, "OPTIONS")
    finally:
        app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", "") != "/api/v1/_test_boom"]

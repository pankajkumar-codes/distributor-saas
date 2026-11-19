"""#283: who the caller is is checked before what the business id looks like, on every /b/{business_id} route."""

import pytest
from fastapi.testclient import TestClient

from app.api import app

CLIENT = TestClient(app, raise_server_exceptions=False)
ROUTES = [
    (method, path)
    for path, ops in app.openapi()["paths"].items()
    if path.startswith("/api/v1/b/{business_id}")
    for method in ops
    if "{" not in path.replace("{business_id}", "")  # the id is the only path parameter
]


def test_the_walk_finds_many_business_routes():
    assert len(ROUTES) > 20


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_not_signed_in_is_401_even_with_a_malformed_business_id(method, path):
    r = CLIENT.request(method, path.replace("{business_id}", "does-not-exist"))
    assert r.status_code == 401 and r.json()["error"]["code"] == "session_invalid", (method, path, r.text)

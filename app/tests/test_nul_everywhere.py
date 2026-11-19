"""#281: a NUL character in any text input of any route is a 422, never a 500.

Walks the OpenAPI document: every string query parameter, and every string property of every JSON body (one at
a time, nested ones included at their top level), is sent as a NUL on its own. The guard sits in front of routing,
so no sign-in is needed to see the answer.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.api import app

SPEC = app.openapi()
CLIENT = TestClient(app, raise_server_exceptions=False)
ID = str(uuid.uuid4())


def _resolve(schema: dict) -> dict:
    ref = schema.get("$ref")
    if ref:
        return _resolve(SPEC["components"]["schemas"][ref.rsplit("/", 1)[1]])
    for key in ("anyOf", "oneOf", "allOf"):
        for part in schema.get(key, ()):
            got = _resolve(part)
            if got.get("type") in ("string", "object"):
                return got
    return schema


def _string_fields():
    for path, ops in SPEC["paths"].items():
        for method, op in ops.items():
            url = path
            for p in op.get("parameters", []):
                if p["in"] == "path":
                    url = url.replace("{" + p["name"] + "}", ID)
            for p in op.get("parameters", []):
                if p["in"] == "query" and _resolve(p["schema"]).get("type") == "string":
                    yield pytest.param(method, url, "query", p["name"], id=f"{method} {path} ?{p['name']}")
            body = op.get("requestBody", {}).get("content", {}).get("application/json")
            if body:
                for name, prop in _resolve(body["schema"]).get("properties", {}).items():
                    if _resolve(prop).get("type") == "string":
                        yield pytest.param(method, url, "body", name, id=f"{method} {path} {{{name}}}")


FIELDS = list(_string_fields())


def test_the_walk_finds_the_known_text_inputs():
    names = {p.id for p in FIELDS}
    assert "post /api/v1/identity/tenants {name}" in names
    assert "get /api/v1/b/{business_id}/customers ?q" in names
    assert len(FIELDS) > 40


@pytest.mark.parametrize(("method", "url", "where", "name"), FIELDS)
def test_a_nul_is_refused_with_422(method, url, where, name):
    if where == "query":
        r = CLIENT.request(method, url, params={name: "a\x00b"})
    else:
        r = CLIENT.request(method, url, json={name: "a\x00b"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "text_invalid", r.text


def test_no_route_reads_a_body_the_nul_guard_skips():
    """The guard checks JSON and url-encoded bodies. A route that takes multipart (or any other body type)
    would let a NUL reach PostgreSQL as a 500, so adding one has to go through the guard first (#303)."""
    checked = {"application/json", "application/x-www-form-urlencoded"}
    offenders = [
        f"{method.upper()} {path} {kind}"
        for path, operations in app.openapi()["paths"].items()
        for method, operation in operations.items()
        for kind in operation.get("requestBody", {}).get("content", {})
        if kind not in checked
    ]
    assert not offenders, offenders


def test_deeply_nested_json_on_a_real_route_is_422_not_500():
    """The guard walked the body recursively and a long run of brackets became a 500 on every JSON route (#322)."""
    client = TestClient(app, raise_server_exceptions=False)
    for depth in (100, 5_000, 200_000):
        body = b'{"name": ' + b"[" * depth + b"]" * depth + b"}"
        r = client.post("/api/v1/b", content=body, headers={"content-type": "application/json"})
        assert r.status_code == 422 and r.json()["error"]["code"] == "json_too_deep", (depth, r.status_code)

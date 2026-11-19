"""The contract marks Idempotency-Key and If-Match required where the API needs them (#282)."""

from app.api import app

FIRST_BAND = ("put", "/api/v1/b/{business_id}/turnover-bands/{fy}", "If-Match")


def _header_params():
    for path, operations in app.openapi()["paths"].items():
        for method, op in operations.items():
            for p in op.get("parameters", []):
                if p.get("in") == "header" and p["name"].lower() in ("idempotency-key", "if-match"):
                    yield method, path, p


def test_every_such_header_is_required_except_the_documented_optional_ones():
    optional = {(m, path, p["name"]) for m, path, p in _header_params() if not p["required"]}
    assert FIRST_BAND in optional
    assert {k[2].lower() for k in optional - {FIRST_BAND}} == {"idempotency-key"}  # purchase confirm and discard
    assert len(optional) == 3


def test_creating_a_product_declares_the_key_required():
    found = {(m, path): p["required"] for m, path, p in _header_params() if p["name"] == "Idempotency-Key"}
    assert found[("post", "/api/v1/b/{business_id}/products")] is True


def test_the_lowercase_spelling_is_required_too():
    # Team invitations and audit-log exports declare the header in lowercase and answer 400 without it.
    found = {(m, path): p["required"] for m, path, p in _header_params() if p["name"] == "idempotency-key"}
    assert found, "expected handlers that spell the header in lowercase"
    assert found[("post", "/api/v1/b/{business_id}/invitations")] is True
    assert found[("post", "/api/v1/b/{business_id}/audit-log/exports")] is True
    assert all(found.values())

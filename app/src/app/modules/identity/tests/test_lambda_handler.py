"""Calls the real Lambda entry point with the event shape API Gateway (HTTP API,
payload 2.0) sends after its JWT authorizer has accepted a Cognito token."""

import json


def api_event(method, path, sub=None, body=None):
    event = {
        "version": "2.0",
        "routeKey": f"{method} {path}",
        "rawPath": path,
        "rawQueryString": "",
        "headers": {"content-type": "application/json", "host": "example.execute-api.ap-south-1.amazonaws.com"},
        "requestContext": {
            "http": {"method": method, "path": path, "protocol": "HTTP/1.1", "sourceIp": "203.0.113.1", "userAgent": "test"},
            "requestId": "req-1",
            "stage": "$default",
        },
        "isBase64Encoded": False,
    }
    if sub:
        event["requestContext"]["authorizer"] = {"jwt": {"claims": {"sub": sub}, "scopes": None}}
    if body is not None:
        event["body"] = json.dumps(body)
    return event


def test_lambda_entry_point_uses_authorizer_claims(client, monkeypatch):
    monkeypatch.setenv("PLATFORM_ENV", "staging")
    from app.api import handler

    created = handler(api_event("POST", "/api/v1/identity/tenants", sub="cognito-sub-1", body={"name": "Lambda Co"}), None)
    assert created["statusCode"] == 201, created
    tenant_id = json.loads(created["body"])["id"]

    mine = handler(api_event("GET", f"/api/v1/identity/tenants/{tenant_id}", sub="cognito-sub-1"), None)
    assert mine["statusCode"] == 200

    other = handler(api_event("GET", f"/api/v1/identity/tenants/{tenant_id}", sub="cognito-sub-2"), None)
    assert other["statusCode"] == 404


def test_lambda_without_claims_is_rejected(client, monkeypatch):
    monkeypatch.setenv("PLATFORM_ENV", "staging")
    from app.api import handler

    assert handler(api_event("GET", "/api/v1/identity/tenants"), None)["statusCode"] == 401
    assert handler(api_event("GET", "/api/v1/health"), None)["statusCode"] == 200

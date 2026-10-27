"""The local auth provider and the API agree on tokens (LLD-0 §3.11). No database."""

from fastapi.testclient import TestClient
from starlette.requests import Request

from app.modules.identity import providers
from platform_common.auth import current_caller, set_local_verifier


def test_a_token_the_local_provider_issues_is_accepted_by_the_api():
    providers.auth_provider.cache_clear()
    try:
        idp = providers.auth_provider()
        sub = idp.create_user("asha@example.com", "correct horse battery")
        token = idp.initiate_auth("asha@example.com", "correct horse battery").access_token
        request = Request({"type": "http", "headers": [(b"authorization", f"Bearer {token}".encode())]})
        assert current_caller(request).user_sub == sub
    finally:
        providers.auth_provider.cache_clear()
        set_local_verifier(None)


def test_the_api_registers_the_keys_at_startup_before_any_auth_call():
    from app import api

    providers.auth_provider.cache_clear()
    set_local_verifier(None)
    try:
        with TestClient(api.app):  # runs the lifespan, as uvicorn does
            assert providers.auth_provider.cache_info().currsize == 1  # built before any request
            idp = providers.auth_provider()
            sub = idp.create_user("asha@example.com", "correct horse battery")
            token = idp.initiate_auth("asha@example.com", "correct horse battery").access_token
            request = Request({"type": "http", "headers": [(b"authorization", f"Bearer {token}".encode())]})
            assert current_caller(request).user_sub == sub
    finally:
        providers.auth_provider.cache_clear()
        set_local_verifier(None)

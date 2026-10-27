"""The local auth provider and the API agree on tokens (LLD-0 §3.11). No database."""

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

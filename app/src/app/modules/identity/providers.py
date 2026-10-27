"""The auth provider and mailer the auth routes use (LLD-0 §3.11).

Locally and in tests these are FakeAuthProvider and LocalFileMailer, so nothing real
is called or sent. In AWS the mailer is QueueMailer on the SQS mail queue
(MAIL_QUEUE_URL, Lambda only); CognitoAuthProvider (S1-c4) is not built yet, so asking
for an auth provider there raises rather than falling back to a fake.
Tests replace them through FastAPI's dependency_overrides.
"""

import os
from functools import cache

from platform_common.auth import debug_env, on_lambda
from platform_common.authprovider import AuthProvider
from platform_common.mailer import LocalFileMailer, Mailer, QueueMailer


@cache
def auth_provider() -> AuthProvider:
    if not debug_env():
        raise RuntimeError("no AuthProvider for this environment yet (CognitoAuthProvider is S1-d)")
    from platform_common.fake_auth import FakeAuthProvider

    return FakeAuthProvider()


@cache
def mailer() -> Mailer:
    queue_url = os.environ.get("MAIL_QUEUE_URL")
    if queue_url:
        if not on_lambda():
            raise RuntimeError("MAIL_QUEUE_URL is for Lambda only; unset it here")
        from platform_common.aws import SqsQueue

        return QueueMailer(SqsQueue(queue_url))
    if not debug_env():
        raise RuntimeError("MAIL_QUEUE_URL is not set")
    return LocalFileMailer()


def token_issuer_and_client() -> tuple[str, str]:
    """What access tokens are verified against (LLD-1 §7.3): the pool's issuer and the
    app client ID, from AUTH_ISSUER and AUTH_CLIENT_ID (set by Terraform, S0b/S1-d)."""
    issuer, client = os.environ.get("AUTH_ISSUER"), os.environ.get("AUTH_CLIENT_ID")
    if issuer and client:
        return issuer, client
    if not debug_env():
        raise RuntimeError("AUTH_ISSUER and AUTH_CLIENT_ID are not set")
    from platform_common.fake_auth import CLIENT_ID, ISSUER

    return ISSUER, CLIENT_ID

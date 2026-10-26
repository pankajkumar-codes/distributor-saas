"""The auth provider and mailer the auth routes use (LLD-0 §3.11).

Locally and in tests these are FakeAuthProvider and LocalFileMailer, so nothing real
is called or sent. In AWS, CognitoAuthProvider (S1-d) and SqsMailer (S0b) are not
built yet, so asking for either there raises rather than falling back to a fake.
Tests replace them through FastAPI's dependency_overrides.
"""

from functools import cache

from platform_common.auth import debug_env
from platform_common.authprovider import AuthProvider
from platform_common.mailer import LocalFileMailer, Mailer


@cache
def auth_provider() -> AuthProvider:
    if not debug_env():
        raise RuntimeError("no AuthProvider for this environment yet (CognitoAuthProvider is S1-d)")
    from platform_common.fake_auth import FakeAuthProvider

    return FakeAuthProvider()


@cache
def mailer() -> Mailer:
    if not debug_env():
        raise RuntimeError("no Mailer for this environment yet (SqsMailer is S0b)")
    return LocalFileMailer()

"""Black-box end-to-end tests over HTTP against a running deployment.

Local (debug users, PLATFORM_ENV=local):
    E2E_BASE_URL=http://localhost:8000 pytest tests/e2e
Staging (two Cognito access tokens for two different test users):
    E2E_BASE_URL=https://... E2E_TOKEN_A=... E2E_TOKEN_B=... pytest tests/e2e

Every run uses fresh user names and tenant names, so it is safe to repeat against a
database that already has data. Use synthetic data only.
"""

import os
import uuid

import httpx
import pytest

BASE = os.environ.get("E2E_BASE_URL")
RUN = uuid.uuid4().hex[:8]


def pytest_collection_modifyitems(config, items):
    if not BASE:
        skip = pytest.mark.skip(reason="E2E_BASE_URL not set")
        for item in items:
            item.add_marker(skip)


class User:
    def __init__(self, name, token=None):
        self.sub = f"e2e-{RUN}-{name}"
        headers = {"authorization": f"Bearer {token}"} if token else {"x-debug-user": self.sub}
        self.http = httpx.Client(base_url=BASE or "http://unset", headers=headers, timeout=20)

    def __getattr__(self, verb):
        return getattr(self.http, verb)


@pytest.fixture(scope="session")
def debug_mode():
    return not os.environ.get("E2E_TOKEN_A")


@pytest.fixture(scope="session")
def alice():
    return User("alice", os.environ.get("E2E_TOKEN_A"))


@pytest.fixture(scope="session")
def bob():
    return User("bob", os.environ.get("E2E_TOKEN_B"))


@pytest.fixture(scope="session")
def anon():
    return httpx.Client(base_url=BASE or "http://unset", timeout=20)


@pytest.fixture()
def debug_user(debug_mode):
    """A third user. Only possible with debug sign-in; with real tokens we have two."""
    if not debug_mode:
        pytest.skip("needs debug sign-in for extra users")
    return lambda name: User(name)


def new_tenant(user, label="Co"):
    r = user.post("/identity/tenants", json={"name": f"E2E {RUN} {label}"})
    assert r.status_code == 201, r.text
    return r.json()["id"]

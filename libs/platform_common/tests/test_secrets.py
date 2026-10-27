"""HMAC keys: the environment locally, Parameter Store on Lambda only (D-040)."""

import sys
import types

import pytest

from platform_common import secrets


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in ("DEMO_KEY", "DEMO_KEY_PARAM", "AWS_LAMBDA_FUNCTION_NAME"):
        monkeypatch.delenv(name, raising=False)
    secrets._parameter.cache_clear()
    yield
    secrets._parameter.cache_clear()


def test_the_environment_wins_and_nothing_set_is_none(monkeypatch):
    assert secrets.secret("DEMO_KEY") is None
    monkeypatch.setenv("DEMO_KEY", "from-env")
    monkeypatch.setenv("DEMO_KEY_PARAM", "/x/demo")
    assert secrets.secret("DEMO_KEY") == "from-env"


def test_a_parameter_is_refused_off_lambda(monkeypatch):
    monkeypatch.setenv("DEMO_KEY_PARAM", "/distsaas-staging/app/demo")
    with pytest.raises(RuntimeError, match="Lambda only"):
        secrets.secret("DEMO_KEY")


def test_on_lambda_a_parameter_is_read_once(monkeypatch):
    """A stand-in for platform_common.aws, so boto3 is never loaded (D-039)."""
    reads = []
    fake_aws = types.ModuleType("platform_common.aws")
    fake_aws.get_parameter = lambda name: reads.append(name) or "from-ssm"
    monkeypatch.setitem(sys.modules, "platform_common.aws", fake_aws)
    monkeypatch.setattr("platform_common.aws", fake_aws, raising=False)
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "distsaas-staging-api")
    monkeypatch.setenv("DEMO_KEY_PARAM", "/distsaas-staging/app/demo")
    assert secrets.secret("DEMO_KEY") == "from-ssm"
    assert secrets.secret("DEMO_KEY") == "from-ssm"
    assert reads == ["/distsaas-staging/app/demo"]

"""Every client platform_common.aws builds gets the one client_config(): 2 s connect, 5 s
read, standard retries with 3 attempts in all. boto3 and botocore are stand-ins that
record what they were given, so this runs without either installed, as the other
platform_common tests do."""

import sys
import types

import pytest


@pytest.fixture()
def aws(monkeypatch):
    built = []

    class Config:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class Client:
        def get_parameter(self, **kwargs):
            return {"Parameter": {"Value": "v"}}

    boto3 = types.ModuleType("boto3")
    boto3.client = lambda service, **kwargs: built.append((service, kwargs)) or Client()
    botocore = types.ModuleType("botocore")
    botocore_config = types.ModuleType("botocore.config")
    botocore_config.Config = Config
    monkeypatch.setitem(sys.modules, "boto3", boto3)
    monkeypatch.setitem(sys.modules, "botocore", botocore)
    monkeypatch.setitem(sys.modules, "botocore.config", botocore_config)
    monkeypatch.delitem(sys.modules, "platform_common.aws", raising=False)
    import platform_common.aws as module

    yield module, built
    monkeypatch.delitem(sys.modules, "platform_common.aws")


EXPECTED = {"connect_timeout": 2, "read_timeout": 5, "retries": {"mode": "standard", "total_max_attempts": 3}}


def test_every_client_gets_the_shared_config(aws):
    module, built = aws
    module.SqsQueue("https://sqs.example/q")
    module.S3ObjectStore("bucket")
    module.SesSender("no-reply@example.test")
    module.cognito_client()
    assert module.get_parameter("/x") == "v"
    assert [s for s, _ in built] == ["sqs", "s3", "sesv2", "cognito-idp", "ssm"]
    for service, kwargs in built:
        want = {**EXPECTED, "s3": {"addressing_style": "virtual"}} if service == "s3" else EXPECTED
        assert kwargs["config"].kwargs == want, service


def test_a_client_passed_in_is_used_as_is(aws):
    module, built = aws
    client = object()
    assert module.SqsQueue("q", client=client).client is client
    assert module.S3ObjectStore("b", client=client).client is client
    assert module.SesSender("a@example.test", client=client).client is client
    assert built == []


def test_the_module_loads_without_botocore(monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", types.ModuleType("boto3"))
    monkeypatch.setitem(sys.modules, "botocore", None)  # import botocore now raises
    monkeypatch.delitem(sys.modules, "platform_common.aws", raising=False)
    import platform_common.aws  # noqa: F401

    monkeypatch.delitem(sys.modules, "platform_common.aws")

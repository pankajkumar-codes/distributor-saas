"""The S3 store's presigned POST (H-4, #69 review nit 4): an exact key, the size range and
the Content-Type as conditions, and the 5-minute expiry. boto3 is never loaded: a stand-in
module takes its place, and the client records what it was asked to sign."""

import sys
import types
import uuid

from platform_common.storage import POST_EXPIRY_SECONDS, key_for


class _Client:
    def __init__(self):
        self.calls = []

    def generate_presigned_post(self, **kwargs):
        self.calls.append(kwargs)
        return {"url": "https://bucket.example/", "fields": {"key": kwargs["Key"], **kwargs["Fields"]}}


def test_the_post_is_pinned_to_its_key_size_type_and_expiry(monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", types.ModuleType("boto3"))
    monkeypatch.delitem(sys.modules, "platform_common.aws", raising=False)
    from platform_common.aws import S3ObjectStore

    client = _Client()
    business = uuid.uuid4()
    key = key_for(business, "uploads", uuid.uuid4())
    S3ObjectStore("bucket", client=client).presign_post(business, key, max_bytes=1234, content_type="text/csv")
    (call,) = client.calls
    assert call["Key"] == key  # boto3 turns Key into an exact {"key": ...} condition, never starts-with
    assert call["Conditions"] == [["content-length-range", 1, 1234], {"Content-Type": "text/csv"}]
    assert not any(isinstance(c, list) and c[0] == "starts-with" for c in call["Conditions"])
    assert call["Fields"] == {"Content-Type": "text/csv"} and call["ExpiresIn"] == POST_EXPIRY_SECONDS == 300
    monkeypatch.delitem(sys.modules, "platform_common.aws")

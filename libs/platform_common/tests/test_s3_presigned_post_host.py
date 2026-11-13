"""The presigned POST names the bucket's regional host (R1-M3).

boto3's default puts the global bucket.s3.amazonaws.com in the URL; a browser can't follow
the redirect S3 sends for a bucket outside us-east-1, and the CSP (connect-src,
form-action) names only the regional host. Uses the real boto3 with made-up credentials;
nothing is sent. Skipped where boto3 isn't installed.
"""

import uuid

import pytest

pytest.importorskip("boto3")


def test_the_post_url_is_the_regional_virtual_host(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delitem(__import__("sys").modules, "platform_common.aws", raising=False)
    from platform_common import storage
    from platform_common.aws import S3ObjectStore

    business = uuid.uuid4()
    key = storage.key_for(business, "uploads", uuid.uuid4())
    post = S3ObjectStore("test-bucket").presign_post(business, key, max_bytes=10)
    assert post.url == "https://test-bucket.s3.ap-south-1.amazonaws.com/"

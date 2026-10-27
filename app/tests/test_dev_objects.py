"""The local stand-in for S3's presigned POST and GET (dev routes, debug env only)."""

import os
import uuid

os.environ["PLATFORM_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402

from app import api  # noqa: E402
from platform_common.storage import LocalObjectStore, key_for, set_store  # noqa: E402


def test_a_browser_style_upload_and_download_through_the_dev_routes(tmp_path):
    store = LocalObjectStore(tmp_path)
    set_store(store)
    client = TestClient(api.app)
    business = uuid.uuid4()
    key = key_for(business, "uploads", uuid.uuid4())
    p = store.presign_post(business, key, max_bytes=20, content_type="text/csv")

    too_big = client.post(p.url, data=p.fields, files={"file": ("r.csv", b"x" * 21, "text/csv")})
    assert too_big.status_code == 403 and too_big.text == "size"
    other_key = client.post(p.url, data={**p.fields, "key": key_for(business, "uploads", uuid.uuid4())},
                            files={"file": ("r.csv", b"a,b\n", "text/csv")})
    assert other_key.status_code == 403
    assert client.post(p.url, data=p.fields, files={"file": ("r.csv", b"a,b\n", "text/csv")}).status_code == 204
    assert store.get_bytes(business, key) == b"a,b\n"

    r = client.get(store.presign_get(business, key, download_name="r.csv"))
    assert r.status_code == 200 and r.content == b"a,b\n" and "r.csv" in r.headers["content-disposition"]
    assert "/api/v1/dev/objects/upload" not in api.app.openapi()["paths"]

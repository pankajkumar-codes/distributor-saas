"""Storage keys and LocalObjectStore (HLD §6.5 H-4). The fake applies the policy S3 would;
whether S3 itself does is QA's staging check. No AWS here."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from platform_common.clock import FrozenClock
from platform_common.errors import Deny
from platform_common.storage import LocalObjectStore, UploadRefused, check_key, key_for

A, B = uuid.uuid4(), uuid.uuid4()


@pytest.fixture()
def store(tmp_path):
    return LocalObjectStore(tmp_path, clock=FrozenClock(datetime(2026, 10, 27, 10, tzinfo=UTC)))


def test_keys_are_made_under_the_business_prefix_and_checked_against_it():
    obj = uuid.uuid4()
    key = key_for(A, "uploads", obj)
    assert key == f"b/{A}/uploads/{obj}"
    assert key_for(A, "branding", obj, "clean.png").endswith("/clean.png")
    assert check_key(A, key) == key
    for bad in (key_for(B, "uploads", obj), f"b/{A}/uploads/{obj}/../x", f"b/{A}/uploads/{obj}/..", f"b/{A}/uploads/../../{obj}", "", None):
        with pytest.raises(Deny):
            check_key(A, bad)
    with pytest.raises(ValueError):
        key_for(A, "secrets", obj)
    with pytest.raises(ValueError):
        key_for(A, "uploads", obj, "../x")


def post(store, *, size=10, content_type="text/csv", max_bytes=100, **override):
    key = key_for(A, "uploads", uuid.uuid4())
    p = store.presign_post(A, key, max_bytes=max_bytes, content_type=content_type)
    fields = {**p.fields, **override}
    return key, p, fields, b"x" * size


def test_an_upload_within_the_policy_is_stored(store):
    key, p, fields, data = post(store)
    assert p.url == "/api/v1/dev/objects/upload" and fields["key"] == key
    assert p.expires_at == datetime(2026, 10, 27, 10, 5, tzinfo=UTC)  # 5 minutes
    assert store.receive_post(fields, data) == key
    info = store.head(A, key)
    assert (info.size, info.content_type) == (10, "text/csv")
    assert store.get_bytes(A, key) == data


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"size": 101}, "size"),  # the limit + 1 byte
        ({"size": 0}, "size"),
        ({"key": f"b/{A}/uploads/{uuid.uuid4()}"}, "key"),  # a different key than the one signed
        ({"Content-Type": "text/html"}, "content_type"),
        ({"policy": "e30"}, "signature"),  # a policy the client wrote
    ],
)
def test_an_upload_outside_the_policy_is_refused_and_nothing_is_stored(store, kwargs, reason):
    size = kwargs.pop("size", 10)
    key, _, fields, data = post(store, size=size, **kwargs)
    with pytest.raises(UploadRefused) as e:
        store.receive_post(fields, data)
    assert e.value.reason == reason
    assert store.head(A, key) is None


def test_an_upload_at_the_limit_is_accepted_and_after_five_minutes_refused(store):
    key, _, fields, data = post(store, size=100)
    store.receive_post(fields, data)
    key, _, fields, data = post(store)
    store.clock.advance(timedelta(minutes=5))
    with pytest.raises(UploadRefused, match="expired"):
        store.receive_post(fields, data)


def test_a_policy_signed_by_another_process_is_refused(tmp_path, store):
    _, _, fields, data = post(store)
    other = LocalObjectStore(tmp_path, clock=store.clock)
    with pytest.raises(UploadRefused, match="signature"):
        other.receive_post(fields, data)


def test_presigning_or_reading_another_business_key_is_refused(store):
    key = key_for(B, "uploads", uuid.uuid4())
    for call in (lambda: store.presign_post(A, key, max_bytes=10), lambda: store.presign_get(A, key),
                 lambda: store.head(A, key), lambda: store.get_bytes(A, key), lambda: store.delete(A, key),
                 lambda: store.put(A, key, b"x", "text/plain")):
        with pytest.raises(Deny):
            call()


def test_a_download_link_works_for_60_seconds(store):
    key = key_for(A, "documents", uuid.uuid4())
    store.put(A, key, b"%PDF", "application/pdf")
    url = store.presign_get(A, key, download_name="INV-1.pdf")
    token = url.rsplit("/", 1)[1]
    assert store.open_get(token) == (b"%PDF", "application/pdf", "INV-1.pdf")
    store.clock.advance(timedelta(seconds=60))
    with pytest.raises(UploadRefused, match="expired"):
        store.open_get(token)


def test_delete_removes_the_object(store):
    key = key_for(A, "exports", uuid.uuid4())
    store.put(A, key, b"data", "application/zip")
    store.delete(A, key)
    assert store.head(A, key) is None
    with pytest.raises(KeyError):
        store.get_bytes(A, key)

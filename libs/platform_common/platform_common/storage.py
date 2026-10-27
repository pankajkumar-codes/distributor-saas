"""Object storage (HLD §6.5 H-4, §6.9, §6.10; D-036).

Every object's key names its area, then its business, and only the API makes keys:

    key = storage.key_for(business_id, "uploads", upload_id)

Each `ObjectStore` call takes the business as well as the key and refuses a key outside
that business's prefix, so a key from a client or another business can't be signed or
read (HLD §10, cross-tenant ID guessing).

`presign_post` is the H-4 upload: a POST policy pinned to the exact key (no
starts-with), a content-length range from 1 byte to `max_bytes`, an optional exact
content type, and a 5-minute expiry. The bucket's default encryption (SSE-KMS, our key)
applies, so the policy names no encryption fields. Whether S3 itself enforces these is
QA's staging check, not something a fake can prove (HLD §6.5).

Adapters: S3ObjectStore (`platform_common.aws`, AWS only) and LocalObjectStore below,
which keeps files on disk and enforces the same key, size, type and expiry rules on a
POST it receives, so local runs and tests need no AWS.
"""

import base64
import hashlib
import hmac
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

from .clock import Clock
from .errors import Deny

AREAS = frozenset({"uploads", "documents", "exports", "branding"})
POST_EXPIRY_SECONDS = 300  # H-4
GET_EXPIRY_SECONDS = 60  # share-link redirect (HLD §6.9)
# The area comes first so that one S3 lifecycle rule per area can expire it, e.g. raw
# uploads after 90 days (TD-18); the business check below is unchanged by the order.
_KEY = re.compile(
    r"^(?P<area>[a-z]+)/b/(?P<business>[0-9a-f-]{36})/[0-9a-f-]{36}(/[a-z0-9_-]+(\.[a-z0-9]+)*)?$"
)


def key_for(business_id: uuid.UUID, area: str, object_id: uuid.UUID, name: str | None = None) -> str:
    """<area>/b/<business>/<object>[/<name>]. `name` is a fixed suffix such as "clean.png",
    never a user's file name."""
    if area not in AREAS:
        raise ValueError(f"unknown storage area {area!r}")
    key = f"{area}/b/{uuid.UUID(str(business_id))}/{uuid.UUID(str(object_id))}"
    if name is not None:
        key += f"/{name}"
    if not _KEY.match(key):
        raise ValueError(f"bad storage key {key!r}")
    return key


def check_key(business_id: uuid.UUID, key: str) -> str:
    """The key, if it is a well-formed key of this business; otherwise Deny (404)."""
    match = _KEY.match(key) if isinstance(key, str) else None
    if match is None or match["area"] not in AREAS or match["business"] != str(business_id):
        raise Deny("not_found")
    return key


def content_disposition(name: str) -> str:
    """RFC 6266: an ASCII fallback, and the full name (Hindi or Bengali business names
    included) as UTF-8 for browsers that read filename*."""
    clean = "".join(c for c in name if c.isprintable() and c not in '"\\/')
    ascii_name = clean.encode("ascii", "ignore").decode() or "download"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(clean, safe='')}"


@dataclass(frozen=True)
class PresignedPost:
    url: str
    fields: dict[str, str]
    expires_at: datetime


@dataclass(frozen=True)
class ObjectInfo:
    size: int
    content_type: str | None


class ObjectStore(Protocol):
    def presign_post(self, business_id: uuid.UUID, key: str, *, max_bytes: int,
                     content_type: str | None = None) -> PresignedPost: ...

    def presign_get(self, business_id: uuid.UUID, key: str, *, download_name: str | None = None) -> str: ...

    def head(self, business_id: uuid.UUID, key: str) -> ObjectInfo | None: ...

    def get_bytes(self, business_id: uuid.UUID, key: str) -> bytes: ...

    def put(self, business_id: uuid.UUID, key: str, data: bytes, content_type: str) -> None: ...

    def delete(self, business_id: uuid.UUID, key: str) -> None: ...


class UploadRefused(Exception):
    """A POST to the local store that S3 would refuse. `reason` says which rule."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class LocalObjectStore:
    """Files under `root`, for local runs and tests. Signed policies use a per-process
    secret, so a URL is good only while the process that signed it runs."""

    def __init__(self, root: Path, *, base_url: str = "/api/v1/dev/objects", clock: Clock | None = None,
                 secret: bytes | None = None):
        self.root = Path(root)
        self.base_url = base_url.rstrip("/")
        self.clock = clock or Clock()
        self._secret = secret or os.urandom(32)

    # signing -------------------------------------------------------------------------

    def _sign(self, doc: dict) -> tuple[str, str]:
        body = _b64(json.dumps(doc, sort_keys=True).encode())
        return body, _b64(hmac.new(self._secret, body.encode(), hashlib.sha256).digest())

    def _verify(self, body: str, signature: str) -> dict:
        expected = _b64(hmac.new(self._secret, body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, signature or ""):
            raise UploadRefused("signature")
        doc = json.loads(_unb64(body))
        if datetime.fromisoformat(doc["expires_at"]) <= self.clock.now():
            raise UploadRefused("expired")
        return doc

    def _path(self, key: str) -> Path:
        return self.root / key

    # ObjectStore ---------------------------------------------------------------------

    def presign_post(self, business_id, key, *, max_bytes, content_type=None) -> PresignedPost:
        check_key(business_id, key)
        if max_bytes < 1:
            raise ValueError("max_bytes must be at least 1")
        expires_at = self.clock.now() + timedelta(seconds=POST_EXPIRY_SECONDS)
        policy, signature = self._sign(
            {"key": key, "max_bytes": max_bytes, "content_type": content_type, "expires_at": expires_at.isoformat()}
        )
        fields = {"key": key, "policy": policy, "signature": signature}
        if content_type is not None:
            fields["Content-Type"] = content_type
        return PresignedPost(f"{self.base_url}/upload", fields, expires_at)

    def receive_post(self, fields: dict[str, str], data: bytes) -> str:
        """What the dev upload route calls with the form it got. Applies the policy the
        way S3 would: exact key, size range, exact content type, expiry. Returns the key."""
        doc = self._verify(fields.get("policy", ""), fields.get("signature", ""))
        if fields.get("key") != doc["key"]:
            raise UploadRefused("key")
        if not 1 <= len(data) <= doc["max_bytes"]:
            raise UploadRefused("size")
        if doc["content_type"] is not None and fields.get("Content-Type") != doc["content_type"]:
            raise UploadRefused("content_type")
        self._write(doc["key"], data, fields.get("Content-Type"))
        return doc["key"]

    def presign_get(self, business_id, key, *, download_name=None) -> str:
        check_key(business_id, key)
        expires_at = self.clock.now() + timedelta(seconds=GET_EXPIRY_SECONDS)
        body, signature = self._sign({"key": key, "name": download_name, "expires_at": expires_at.isoformat()})
        return f"{self.base_url}/get/{body}.{signature}"

    def open_get(self, token: str) -> tuple[bytes, str | None, str | None]:
        """What the dev download route calls: (bytes, content type, download name)."""
        body, _, signature = token.partition(".")
        doc = self._verify(body, signature)
        info = self._info(doc["key"])
        if info is None:
            raise UploadRefused("missing")
        return self._path(doc["key"]).read_bytes(), info.content_type, doc["name"]

    def head(self, business_id, key) -> ObjectInfo | None:
        return self._info(check_key(business_id, key))

    def get_bytes(self, business_id, key) -> bytes:
        check_key(business_id, key)
        if self._info(key) is None:
            raise KeyError(key)
        return self._path(key).read_bytes()

    def put(self, business_id, key, data, content_type) -> None:
        self._write(check_key(business_id, key), data, content_type)

    def delete(self, business_id, key) -> None:
        check_key(business_id, key)
        for p in (self._path(key), self._meta(key)):
            p.unlink(missing_ok=True)

    # files ---------------------------------------------------------------------------

    def _meta(self, key: str) -> Path:
        return self._path(key).with_name(self._path(key).name + ".meta.json")

    def _write(self, key: str, data: bytes, content_type: str | None) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self._meta(key).write_text(json.dumps({"content_type": content_type}))

    def _info(self, key: str) -> ObjectInfo | None:
        path = self._path(key)
        if not path.is_file():
            return None
        meta = json.loads(self._meta(key).read_text()) if self._meta(key).is_file() else {}
        return ObjectInfo(path.stat().st_size, meta.get("content_type"))


_store: ObjectStore | None = None


def set_store(store: ObjectStore | None) -> None:
    global _store
    _store = store


def get_store() -> ObjectStore:
    if _store is None:
        raise RuntimeError("no object store configured; the app sets one at start-up (set_store)")
    return _store

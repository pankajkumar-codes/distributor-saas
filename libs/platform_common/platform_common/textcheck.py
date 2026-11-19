"""One shared text-input guard: no NUL character (U+0000) anywhere in a request's query string, JSON body or
url-encoded form body.

PostgreSQL text cannot hold NUL, so one that reached the database became a 500 (#281). Checking every request
here, before routing, covers each current and future text field without annotating it. A request that carries
one is refused with 422 `text_invalid`, the code the catalog already uses for hidden characters.
"""

import json
from urllib.parse import unquote_to_bytes

from platform_common.errors import Invalid

# Bytes. The API Gateway payload limit is 10 MB, so no request the API can receive is larger than this.
MAX_CHECKED_BODY = 10_000_000

# No route takes multipart/form-data today (uploads go to the object store with a signed URL), and
# test_no_route_reads_a_body_the_nul_guard_skips fails if one starts to, so a file part never has to be parsed here.

_REFUSAL = Invalid("text_invalid", "Remove hidden characters from the text and try again").body()


def has_nul(value) -> bool:
    if isinstance(value, str):
        return "\x00" in value
    if isinstance(value, dict):
        return any(has_nul(k) or has_nul(v) for k, v in value.items())
    if isinstance(value, list):
        return any(has_nul(v) for v in value)
    return False


class RejectNul:
    """Pure ASGI middleware; reads a JSON body once and replays it to the app."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        bad = b"\x00" in unquote_to_bytes(scope.get("query_string", b""))
        replay = None
        kind = _body_kind(scope)
        if not bad and kind:
            replay, bad = await _buffer(receive, kind)
        if bad:
            return await _respond(send)
        return await self.app(scope, replay or receive, send)


def _body_kind(scope) -> str | None:
    for name, value in scope.get("headers", ()):
        if name == b"content-type":
            media = value.split(b";")[0].strip().lower()
            if media == b"application/json":
                return "json"
            if media == b"application/x-www-form-urlencoded":
                return "form"
    return None


async def _buffer(receive, kind):
    chunks, size = [], 0
    while True:
        message = await receive()
        if message["type"] != "http.request":
            return receive, False
        chunks.append(message.get("body", b""))
        size += len(chunks[-1])
        if not message.get("more_body"):
            break
    body = b"".join(chunks)

    async def replay():
        nonlocal body
        sent, body = body, b""
        return {"type": "http.request", "body": sent, "more_body": False}

    if size > MAX_CHECKED_BODY:
        return replay, False
    if kind == "form":
        # Fields are percent-encoded and a plus is a space; a NUL can only be %00 (or a raw byte).
        return replay, b"\x00" in unquote_to_bytes(body.replace(b"+", b" "))
    try:
        return replay, has_nul(json.loads(body))
    except ValueError:
        return replay, False  # not JSON: the route's own validation answers


async def _respond(send):
    payload = json.dumps(_REFUSAL).encode()
    await send({"type": "http.response.start", "status": 422,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode())]})
    await send({"type": "http.response.body", "body": payload})

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

# No request body here nests more than a handful of levels. A body that nests deeper is refused, so a long run of
# brackets can neither exhaust the recursion limit (a 500) nor reach the handlers (#322).
MAX_JSON_DEPTH = 64

_REFUSAL = Invalid("text_invalid", "Remove hidden characters from the text and try again").body()
_TOO_DEEP = Invalid("json_too_deep", "The request is nested too deeply").body()


def has_nul(value) -> bool:
    """Whether any string, or any key, in a parsed JSON value holds a NUL. Walks with its own stack, so depth is no limit."""
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            if "\x00" in item:
                return True
        elif isinstance(item, dict):
            for k, v in item.items():
                stack.append(k)
                stack.append(v)
        elif isinstance(item, list):
            stack.extend(item)
    return False


def too_deep(value, limit: int = MAX_JSON_DEPTH) -> bool:
    stack = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        if isinstance(item, (dict, list)):
            if depth > limit:
                return True
            children = item.values() if isinstance(item, dict) else item
            stack.extend((child, depth + 1) for child in children if isinstance(child, (dict, list)))
    return False


class RejectNul:
    """Pure ASGI middleware; reads a JSON body once and replays it to the app."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        refusal = _REFUSAL if b"\x00" in unquote_to_bytes(scope.get("query_string", b"")) else None
        replay = None
        kind = _body_kind(scope)
        if not refusal and kind:
            replay, refusal = await _buffer(receive, kind)
        if refusal:
            return await _respond(send, refusal)
        return await self.app(scope, replay or receive, send)


def _body_kind(scope) -> str | None:
    for name, value in scope.get("headers", ()):
        if name == b"content-type":
            media = value.split(b";")[0].strip().lower()
            # FastAPI parses application/json and any application/*+json (for example vnd.api+json) as JSON.
            if media == b"application/json" or (media.startswith(b"application/") and media.endswith(b"+json")):
                return "json"
            if media == b"application/x-www-form-urlencoded":
                return "form"
    return None


async def _buffer(receive, kind):
    chunks, size = [], 0
    while True:
        message = await receive()
        if message["type"] != "http.request":
            return receive, None
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
        return replay, None
    if kind == "form":
        # Fields are percent-encoded and a plus is a space; a NUL can only be %00 (or a raw byte).
        return replay, _REFUSAL if b"\x00" in unquote_to_bytes(body.replace(b"+", b" ")) else None
    try:
        value = json.loads(body)
    except RecursionError:
        return replay, _TOO_DEEP  # the parser's own limit: far deeper than any request here
    except ValueError:
        return replay, None  # not JSON: the route's own validation answers
    if too_deep(value):
        return replay, _TOO_DEEP
    return replay, _REFUSAL if has_nul(value) else None


async def _respond(send, refusal):
    payload = json.dumps(refusal).encode()
    await send({"type": "http.response.start", "status": 422,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode())]})
    await send({"type": "http.response.body", "body": payload})

"""Asking the PDF renderer for a document (D-042, TD-9).

The worker writes what is to be rendered as JSON under render-input/b/<business>/<render>/
and sends only that S3 key to the `render` queue; the renderer Lambda reads it, writes
the PDF to documents/b/<business>/<render>/document.pdf (renderer/renderer/inputs.py
holds the same key rules). Nothing deletes the input: the bucket's lifecycle rule expires
it, about two days at most (D-042). The message never carries the document itself. If
the renderer's last try fails, it writes failed.json next to where the PDF would be, so
`has_failed` can say so instead of the caller waiting forever.

    document_key = render.request(business_id, render_id, {"template": "invoice-draft", ...})

`request` is safe to repeat with the same render ID (a retried job): the input is
overwritten with the same bytes and the renderer writes the same document key, so a
second message at most renders the same PDF again.

The queue is chosen at start-up (`set_render_queue`): SQS on Lambda (RENDER_QUEUE_URL),
a recording FakeQueue locally and in tests. Nothing renders outside AWS; a local run
can see what would have been sent.
"""

import json
import uuid

from .queue import Queue
from .storage import get_store, key_for

TEMPLATES = frozenset({"invoice-draft"})
INPUT_VERSION = 1
INPUT_NAME = "input.json"
DOCUMENT_NAME = "document.pdf"
FAILED_NAME = "failed.json"  # the renderer's mark that its last try failed (no data in it)
MAX_INPUT_BYTES = 1024 * 1024  # a 200-line draft is about 60 KB; the renderer refuses more

_queue: Queue | None = None


def set_render_queue(queue: Queue | None) -> None:
    global _queue
    _queue = queue


def get_render_queue() -> Queue:
    if _queue is None:
        raise RuntimeError("no render queue configured; the app sets one at start-up (set_render_queue)")
    return _queue


def input_key(business_id: uuid.UUID, render_id: uuid.UUID) -> str:
    return key_for(business_id, "render-input", render_id, INPUT_NAME)


def document_key(business_id: uuid.UUID, render_id: uuid.UUID) -> str:
    return key_for(business_id, "documents", render_id, DOCUMENT_NAME)


def request(business_id: uuid.UUID, render_id: uuid.UUID, document: dict) -> str:
    """Writes the render input and queues it. Returns the key the PDF will be written to.

    `document` is plain JSON data: strings, numbers as strings, lists and objects. It is
    never HTML; the renderer escapes every value it prints."""
    if document.get("template") not in TEMPLATES:
        raise ValueError(f"unknown render template {document.get('template')!r}")
    body = json.dumps({**document, "v": INPUT_VERSION}, ensure_ascii=False, sort_keys=True).encode()
    if len(body) > MAX_INPUT_BYTES:
        raise ValueError(f"render input of {len(body)} bytes is over {MAX_INPUT_BYTES}")
    key = input_key(business_id, render_id)
    get_store().put(business_id, key, body, "application/json")
    get_render_queue().send({"key": key})
    return document_key(business_id, render_id)


def is_rendered(business_id: uuid.UUID, render_id: uuid.UUID) -> bool:
    return get_store().head(business_id, document_key(business_id, render_id)) is not None


def failure_key(business_id: uuid.UUID, render_id: uuid.UUID) -> str:
    return key_for(business_id, "documents", render_id, FAILED_NAME)


def has_failed(business_id: uuid.UUID, render_id: uuid.UUID) -> bool:
    """The renderer gave up: its last try failed and the message went to the DLQ. A PDF
    from a later redrive still wins (check is_rendered first)."""
    return get_store().head(business_id, failure_key(business_id, render_id)) is not None

"""The render input: what the worker writes under render-input/b/ for one render, and
whose S3 key the `render` queue message carries (D-042). platform_common.render writes
it; the key rules here must match that module's (render-input/b/<business>/<render>/
input.json in, documents/b/<business>/<render>/document.pdf out), which a platform_common
test checks.

Inputs are never deleted (EM, D-042): the bucket's lifecycle rule expires each one a
day after it is written, and its old version a day after that, so an input lives about
two days at most, under SSE-KMS and readable only by the renderer. A redelivered message
renders again to the same document key.

This module imports neither boto3 nor WeasyPrint.
"""

import re

AREA = "render-input"
# Same shape as platform_common.storage keys: render-input/b/<business>/<object>[/<name>].
_KEY = re.compile(
    r"^render-input/b/(?P<business>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
    r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(/[a-z0-9_-]+(\.[a-z0-9]+)*)?$"
)


def check_input_key(key: object) -> str:
    """The key, if it is a render-input key; otherwise ValueError. A message from the
    queue is not trusted to name only render inputs."""
    if not isinstance(key, str) or not _KEY.match(key):
        raise ValueError(f"not a render-input key: {key!r}")
    return key


def business_of(key: str) -> str:
    """The business a render-input key belongs to, so the PDF lands under the same one."""
    return _KEY.match(check_input_key(key))["business"]


INPUT_NAME = "input.json"
DOCUMENT_NAME = "document.pdf"
FAILED_NAME = "failed.json"  # written instead of the PDF when the last try fails
_INPUT = re.compile(r"^render-input/(b/[0-9a-f-]{36}/[0-9a-f-]{36})/input\.json$")


def document_key(key: str) -> str:
    """Where the PDF for this input goes: the same business and render ID under
    documents/. Only an input named input.json is ever rendered."""
    match = _INPUT.match(check_input_key(key))
    if match is None:
        raise ValueError(f"not a render input: {key!r}")
    return f"documents/{match[1]}/{DOCUMENT_NAME}"



def failure_key(key: str) -> str:
    """Where the renderer records that this input's last try failed, next to the PDF it
    could not write. platform_common.render.has_failed reads it."""
    return document_key(key).removesuffix(DOCUMENT_NAME) + FAILED_NAME

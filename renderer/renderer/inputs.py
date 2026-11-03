"""The render input: what the worker writes under render-input/b/ for one render, and
whose S3 key the `render` queue message carries (D-042).

The renderer calls `delete_after_render` once the PDF is safely written under
documents/b/, and only then: until that point a retried message must still find its
input. A delete is idempotent, so a retry after the delete (SQS is at-least-once) is
harmless, and the bucket's lifecycle rule removes any input that is never rendered
(a message that ends in the DLQ) after a day.

The bucket is versioned, so a delete leaves a noncurrent version, which the same rule
expires a day later. The renderer's role needs `s3:DeleteObject` on render-input/b/* for
this; S4 (BH-6) adds it with the first real render, alongside its documents/b/* write.

This module imports neither boto3 nor WeasyPrint: the caller passes its S3 client.
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


def delete_after_render(s3, bucket: str, key: str) -> None:
    """Deletes one render input. Refuses any key outside render-input/b/, so a bad
    message can never make the renderer delete a document or an upload."""
    s3.delete_object(Bucket=bucket, Key=check_input_key(key))

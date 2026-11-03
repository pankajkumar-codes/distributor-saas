"""Entity tags for optimistic concurrency (LLD-3 L3-9): one rule for every route that
takes If-Match (business profile, products, customers, sales drafts).

A resource's tag is its integer `version`, sent as a strong ETag: `ETag: "7"`.

If-Match on PUT, PATCH and DELETE is read by `if_match_version`:
- missing: None, so the service answers 422 if_match_required;
- `"7"` (the ETag as sent), or a bare `7`: version 7;
- anything else is never a real version and reads as stale (-1), so the service answers
  409 stale_record and nothing is written. That includes:
  - a weak tag `W/"7"`: If-Match uses the strong comparison (RFC 9110 §13.1.1), and a
    weak tag never matches;
  - `*`: we need the version the user edited, not "any version", so a blind write can't
    overwrite someone else's change;
  - a list (`"6", "7"`), a non-number, or a negative or zero version.

Clients send the `version` from the response body, not the ETag header: a proxy that
compresses a response (CloudFront can, if compression is on for /api/*) may turn the strong tag into a
weak `W/"7"`, which this rule refuses.
"""

import re

from fastapi import Response

STALE = -1  # never a real version (versions start at 1)
_TAG = re.compile(r'^(?:"([1-9][0-9]{0,9})"|([1-9][0-9]{0,9}))$')


def if_match_version(raw: str | None) -> int | None:
    """The version an If-Match header names, None when it is missing, or STALE."""
    if raw is None:
        return None
    m = _TAG.match(raw.strip())
    if m is None:
        return STALE
    return int(m.group(1) or m.group(2))


def set_etag(response: Response, version: int) -> None:
    """`ETag: "<version>"` on a GET, or on a write's reply (the tag to send next)."""
    response.headers["ETag"] = f'"{version}"'

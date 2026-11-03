"""platform_common.etag: one If-Match rule for every route (LLD-3 L3-9)."""

import pytest
from fastapi import Response

from platform_common.etag import STALE, if_match_version, set_etag


@pytest.mark.parametrize(
    ("raw", "version"),
    [
        (None, None),  # missing: the service answers 422 if_match_required
        ('"7"', 7),  # the ETag as sent
        ("7", 7),  # bare
        ('  "12" ', 12),
        ('W/"7"', STALE),  # strong comparison: a weak tag never matches
        ("*", STALE),  # we need the version the user edited
        ('"6", "7"', STALE),  # one tag only
        ('"0"', STALE),
        ('"-1"', STALE),
        ('"07"', STALE),
        ("abc", STALE),
        ("", STALE),
        ('"12345678901"', STALE),  # more digits than any version
    ],
)
def test_if_match_version(raw, version):
    assert if_match_version(raw) == version


def test_set_etag_is_a_strong_quoted_tag():
    r = Response()
    set_etag(r, 3)
    assert r.headers["ETag"] == '"3"'

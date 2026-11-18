"""Shared text-input guard: PostgreSQL text cannot hold a NUL character (U+0000).

Without this a NUL reaches the database and surfaces as a 500. As an annotated type it is a
422 validation error at the edge, the same status the catalog uses for ``text_invalid``.
"""

from pydantic import AfterValidator


def reject_nul[T: (str, None)](value: T) -> T:
    if value is not None and "\x00" in value:
        raise ValueError("must not contain a NUL character")
    return value


NoNul = AfterValidator(reject_nul)

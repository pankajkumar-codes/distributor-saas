"""Identity's 404 helpers, kept until LLD-1 rewrites identity onto `business_uow`.

New routes use `platform_common.uow` (`business_uow`, `parse_id`) and `Deny`, which
replaced #9's `bind_tenant`. These two answer 404 both for a malformed ID and for one
the caller may not see, so another tenant's IDs reveal nothing.
"""

import uuid

from fastapi import HTTPException, status


def parse_tenant_id(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except (ValueError, TypeError, AttributeError):
        raise not_found()


def not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "not found")

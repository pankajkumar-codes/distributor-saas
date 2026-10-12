"""Tenant identifiers arrive from the client and are never trusted on their own.

Services resolve a tenant only together with the caller's active membership, and
answer 404 both when the tenant does not exist and when the caller is not a member,
so another tenant's ids reveal nothing.
"""

import uuid

from fastapi import HTTPException, status


def parse_tenant_id(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except (ValueError, TypeError):
        raise not_found()


def not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "not found")

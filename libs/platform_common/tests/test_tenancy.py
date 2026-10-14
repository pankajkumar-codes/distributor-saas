import uuid

import pytest
from fastapi import HTTPException

from platform_common.tenancy import not_found, parse_tenant_id


def test_valid_uuid_parses():
    tid = uuid.uuid4()
    assert parse_tenant_id(str(tid)) == tid


@pytest.mark.parametrize("raw", ["", "1", "not-a-uuid", "' or 1=1 --", "../../etc/passwd", None, "0" * 100])
def test_bad_ids_look_exactly_like_missing_tenants(raw):
    with pytest.raises(HTTPException) as bad:
        parse_tenant_id(raw)
    missing = not_found()
    assert (bad.value.status_code, bad.value.detail) == (missing.status_code, missing.detail) == (404, "not found")

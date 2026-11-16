"""A password never reaches a log line, an audit row, a stored code row or a mail (D-061, SECURITY.md).

Every route that takes a password is driven here with its own marker string, a refused one and an accepted one each,
and then the logs, the audit log, the identity tables and the mails are searched for every marker.
"""

import logging

import pytest
from sqlalchemy import text

from platform_common.auth import set_local_verifier
from platform_common.fake_auth import CLIENT_ID, ISSUER

from .auth_env import EMAIL, ORIGIN, PASSWORD, auth_env, last, verify
from .conftest import PG_ADMIN_URL

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")

SIGNUP_WEAK = "marker-signup-weak-aaa"  # refused: no upper case, digit or special
SIGNUP_OK = "Marker-Signup-Ok-1!"
CHANGE_WEAK = "marker-change-weak-bbb"
CHANGE_OK = "Marker-Change-Ok-2!"
RESET_WEAK = "marker-reset-weak-ccc"
RESET_OK = "Marker-Reset-Ok-3!"
MARKERS = [SIGNUP_WEAK, SIGNUP_OK, CHANGE_WEAK, CHANGE_OK, RESET_WEAK, RESET_OK]


@pytest.fixture()
def env():
    with auth_env() as e:
        client, idp, _, _ = e
        set_local_verifier(idp.jwks(), issuer=ISSUER, client_id=CLIENT_ID)
        yield e
        set_local_verifier(None)


def test_no_password_reaches_a_log_an_audit_row_a_stored_code_or_a_mail(env, caplog):
    client, idp, mail, admin = env
    caplog.set_level(logging.DEBUG)

    refused = client.post("/api/v1/auth/signup", json={"email": EMAIL, "password": SIGNUP_WEAK})
    assert refused.status_code == 422 and SIGNUP_WEAK not in refused.text
    code = sign_up_with(client, mail, SIGNUP_OK)
    done = verify(client, code, SIGNUP_OK)
    assert done.status_code == 200, done.text
    token = {"authorization": f"Bearer {done.json()['access_token']}"}

    weak = client.post("/api/v1/me/password", json={"current_password": SIGNUP_OK, "new_password": CHANGE_WEAK}, headers=token)
    assert weak.status_code == 422 and CHANGE_WEAK not in weak.text
    ok = client.post("/api/v1/me/password", json={"current_password": SIGNUP_OK, "new_password": CHANGE_OK}, headers=token)
    assert ok.status_code == 204, ok.text

    assert client.post("/api/v1/auth/reset", json={"email": EMAIL}).status_code == 202
    reset_code = last(mail).params["code"]
    body = {"email": EMAIL, "code": reset_code}
    bad = client.post("/api/v1/auth/reset/verify", json={**body, "new_password": RESET_WEAK})
    assert bad.status_code == 422 and RESET_WEAK not in bad.text
    good = client.post("/api/v1/auth/reset/verify", json={**body, "new_password": RESET_OK})
    assert good.status_code == 200, good.text
    signin = client.post("/api/v1/auth/signin", json={"email": EMAIL, "password": RESET_OK}, headers=ORIGIN)
    assert signin.status_code == 200

    stored = {
        "log": caplog.text + " ".join(str(r.__dict__) for r in caplog.records),
        "mails": repr(mail.sent),
    }
    with admin.connect() as c:
        for schema_table in ("platform.audit_log", "identity.users", "identity.sessions", "identity.pending_signups"):
            stored[schema_table] = c.execute(text(f"select coalesce(string_agg(t::text, ' '), '') from {schema_table} t")).scalar()
        stored["codes"] = c.execute(
            text("select coalesce(string_agg(t::text, ' '), '') from identity.auth_codes t")
        ).scalar() if _has_table(c, "identity", "auth_codes") else ""
    for where, haystack in stored.items():
        for marker in MARKERS:
            assert marker not in haystack, f"{marker} found in {where}"
    assert PASSWORD not in stored["log"]


def sign_up_with(client, mail, password):
    r = client.post("/api/v1/auth/signup", json={"email": EMAIL, "password": password})
    assert r.status_code == 202, r.text
    return last(mail).params["code"]


def _has_table(conn, schema, table) -> bool:
    return bool(
        conn.execute(
            text("select 1 from information_schema.tables where table_schema = :s and table_name = :t"),
            {"s": schema, "t": table},
        ).first()
    )

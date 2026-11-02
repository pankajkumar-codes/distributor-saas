"""GET and PATCH /me and POST /me/password on PostgreSQL, as app_rw (LLD-1 §5.9).

Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import uuid

import pytest
from sqlalchemy import text

from platform_common.auth import set_local_verifier
from platform_common.fake_auth import CLIENT_ID, ISSUER
from platform_common.permissions import Permission

from .auth_env import EMAIL, ORIGIN, PASSWORD, auth_env, last, one, sign_up, verify
from .conftest import PG_ADMIN_URL

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")

NEW = "a brand new passphrase"
WRONG = "not my password at all"
BUSINESS = {
    "registration": {"kind": "gstin", "gstin": "19AAPFU0939F1ZS"},
    "legal_name": "Vashi Essentials LLP",
    "trade_name": "Vashi Essentials",
    "address": {"line1": "12 Park St", "city": "Kolkata", "pin": "700016", "state_code": "19"},
    "turnover_band": "up_to_threshold",
    "einvoice_history": "no",
}


@pytest.fixture()
def env():
    with auth_env() as e:
        client, idp, mail, _ = e
        assert verify(client, sign_up(client, mail).params["code"]).status_code == 200
        set_local_verifier(idp.jwks(), issuer=ISSUER, client_id=CLIENT_ID)
        yield e
        set_local_verifier(None)


def signin(client, password=PASSWORD, email=EMAIL):
    return client.post("/api/v1/auth/signin", json={"email": email, "password": password}, headers=ORIGIN)


def bearer(client, password=PASSWORD, email=EMAIL):
    return {"authorization": f"Bearer {signin(client, password, email).json()['access_token']}"}


def change(client, headers, current=PASSWORD, new=NEW):
    return client.post("/api/v1/me/password", json={"current_password": current, "new_password": new}, headers=headers)


def live(admin):
    return one(admin, "select count(*) from identity.sessions where revoked_at is null")


def test_get_me_lists_the_user_and_each_role_s_permissions(env):
    client, _, _, _ = env
    me = bearer(client)
    r = client.get("/api/v1/me", headers=me)
    assert r.status_code == 200, r.text
    user = r.json()["user"]
    assert (user["email"], user["name"], user["totp_enabled"], r.json()["memberships"]) == (EMAIL, None, False, [])
    made = client.post("/api/v1/b", json=BUSINESS, headers={**me, "Idempotency-Key": uuid.uuid4().hex})
    assert made.status_code == 201, made.text
    assert client.get("/api/v1/me", headers=me).json()["memberships"] == [
        {
            "business_id": made.json()["business_id"],
            "display_name": "Vashi Essentials",
            "gstin": "19AAPFU0939F1ZS",
            "role": "owner",
            "permissions": [p.value for p in Permission],  # the owner may do everything
        }
    ]


def test_patch_me_sets_only_the_callers_name(env):
    client, _, mail, admin = env
    ravi = verify(client, sign_up(client, mail, email="ravi@example.com").params["code"], email="ravi@example.com")
    assert ravi.status_code == 200
    me = bearer(client)
    r = client.patch("/api/v1/me", json={"name": "  Asha Rao "}, headers=me)
    assert (r.status_code, r.json()["user"]["name"]) == (200, "Asha Rao")
    assert one(admin, "select count(*) from identity.users where name is not null") == 1  # Ravi's is untouched
    assert client.patch("/api/v1/me", json={"name": "   "}, headers=me).json()["user"]["name"] is None
    assert client.patch("/api/v1/me", json={"name": "x" * 101}, headers=me).status_code == 422
    for bad in ("Asha\nRao", "Asha\x00", "Asha\u202eoaR"):  # a line break, a NUL, a direction override
        assert client.patch("/api/v1/me", json={"name": bad}, headers=me).status_code == 422, repr(bad)
    assert client.patch("/api/v1/me", json={"name": "आशा राव"}, headers=me).json()["user"]["name"] == "आशा राव"


def test_changing_the_password_ends_every_session(env):
    client, idp, mail, admin = env
    me = bearer(client)
    assert live(admin) == 2
    r = change(client, me)
    assert r.status_code == 204, r.text
    assert "Max-Age=0" in r.headers["set-cookie"]
    assert live(admin) == 0
    assert one(admin, "select count(*) from identity.sessions where revoke_reason = 'password_change'") == 2
    assert all(t.revoked for t in idp._refresh.values())  # the provider's global sign-out ran after commit
    assert (last(mail).template, last(mail).to) == ("password_changed", EMAIL)
    assert signin(client).status_code == 401 and signin(client, NEW).status_code == 200
    assert client.get("/api/v1/me", headers=me).status_code == 401
    with admin.connect() as c:
        rows = c.execute(
            text(
                "select a.target_kind, a.business_id, a.user_id = u.id from platform.audit_log a"
                " join identity.users u on u.email = :e where a.action = 'auth.password_change'"
            ),
            {"e": EMAIL},
        ).all()
    assert [tuple(r) for r in rows] == [("user", None, True)]


def test_a_wrong_current_or_weak_new_password_changes_nothing(env):
    client, idp, mail, admin = env
    me, sent = bearer(client), len(mail.sent)
    r = change(client, me, current=WRONG)
    assert (r.status_code, r.json()["error"]["code"]) == (422, "current_password_wrong")
    r = change(client, me, new="password")
    assert (r.status_code, r.json()["error"]["code"]) == (422, "password_weak")
    assert idp.user(EMAIL).password == PASSWORD and live(admin) == 2 and len(mail.sent) == sent
    assert one(admin, "select count(*) from platform.audit_log where action = 'auth.password_change'") == 0


def test_change_password_shares_the_sign_in_per_email_bucket(env):  # §5.9
    client, _, _, _ = env
    me = bearer(client)  # one of the ten
    for _ in range(9):
        assert change(client, me, current=WRONG).status_code == 422
    r = change(client, me)  # even the right password
    assert r.status_code == 429 and "retry-after" in r.headers


def test_change_password_needs_a_bearer_token(env):
    client, idp, _, _ = env
    r = change(client, {"x-debug-user": idp.user(EMAIL).sub})  # no access token to hand the provider
    assert r.status_code == 401
    assert change(client, {}).status_code == 401
    assert idp.user(EMAIL).password == PASSWORD


def test_the_same_password_is_refused_before_the_provider(env):  # Staff 2, #55
    client, idp, _, _ = env
    r = change(client, bearer(client), new=PASSWORD)
    assert (r.status_code, r.json()["error"]["code"]) == (422, "password_unchanged")
    assert idp.user(EMAIL).password == PASSWORD


@pytest.mark.parametrize(
    "refusal, status, code",
    [
        ("token_invalid", 401, "session_invalid"),  # expired or revoked at the provider
        ("password_rejected", 422, "password_weak"),
        ("rate_limited", 429, "rate_limited"),
        ("not_authorized", 422, "current_password_wrong"),
    ],
)
def test_each_provider_refusal_gets_its_own_reply(env, monkeypatch, refusal, status, code):  # Staff 2, #55
    from platform_common.authprovider import AuthRefused

    client, idp, _, admin = env
    me = bearer(client)

    def refuse(*_):
        raise AuthRefused(refusal)

    monkeypatch.setattr(idp, "change_password", refuse)
    r = change(client, me)
    assert (r.status_code, r.json()["error"]["code"]) == (status, code)
    assert live(admin) == 2


def test_a_failed_tx_b_still_signs_out_at_the_provider(env, monkeypatch, caplog):  # Staff 2, #55
    from app.modules.identity.service import account

    client, idp, mail, admin = env
    me, sent = bearer(client), len(mail.sent)

    def broken(*_, **__):
        raise RuntimeError("audit write failed")

    monkeypatch.setattr(account.audit, "record", broken)
    r = change(client, me)
    assert r.status_code == 500
    assert idp.user(EMAIL).password == NEW  # the provider had already changed it
    assert all(t.revoked for t in idp._refresh.values())  # so every provider token is ended
    assert live(admin) == 2 and len(mail.sent) == sent  # tx B rolled back: no rows revoked, no mail
    assert any(r.levelname == "ERROR" and "tx B failed" in r.getMessage() for r in caplog.records)

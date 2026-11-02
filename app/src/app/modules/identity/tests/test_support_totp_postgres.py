"""TOTP recovery by support: POST /support/totp-recovery and /confirm on PostgreSQL, as
app_rw, with the fake provider and FakeMailer (LLD-2 §6.3, L2-6; AC2-11, AC2-14, AC2-16).

Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import uuid

import pytest
from sqlalchemy import exc, text

from platform_common.auth import set_local_verifier
from platform_common.fake_auth import CLIENT_ID, ISSUER

from .auth_env import ORIGIN, PASSWORD, auth_env, one, sign_up, verify
from .conftest import PG_ADMIN_URL

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")

USER = "asha@example.com"
SUPPORT = "sam@support.example.com"
START = "/api/v1/support/totp-recovery"
CONFIRM = "/api/v1/support/totp-recovery/confirm"
BUSINESS = {  # as business's own tests create one (identity may not import business)
    "registration": {"kind": "gstin", "gstin": "19aapfu0939f1zs"},
    "legal_name": "Vashi Essentials LLP",
    "trade_name": "Vashi Essentials",
    "address": {"line1": "12 Park St", "city": "Kolkata", "pin": "700016", "state_code": "19"},
    "turnover_band": "up_to_threshold",
    "einvoice_history": "no",
}


def signin(client, email):
    return client.post("/api/v1/auth/signin", json={"email": email, "password": PASSWORD}, headers=ORIGIN)


def account(client, mail, idp, email, *, totp=True):
    """A signed-up account, its bearer header, and TOTP on if asked."""
    assert verify(client, sign_up(client, mail, email).params["code"], email=email).status_code == 200
    me = {"authorization": f"Bearer {signin(client, email).json()['access_token']}"}
    if totp:
        secret = client.post("/api/v1/me/totp/setup", headers=me).json()["secret"]
        assert (
            client.post("/api/v1/me/totp/confirm", json={"code": idp.totp_code(secret)}, headers=me).status_code == 204
        )
    return me


def make_support(admin, email):
    with admin.begin() as c:
        c.execute(text("update identity.users set is_support = true where email = :e"), {"e": email})


@pytest.fixture()
def env():
    with auth_env() as (client, idp, mail, admin):
        set_local_verifier(idp.jwks(), issuer=ISSUER, client_id=CLIENT_ID)
        user = account(client, mail, idp, USER)
        sam = account(client, mail, idp, SUPPORT)
        make_support(admin, SUPPORT)
        yield client, idp, mail, admin, user, sam
        set_local_verifier(None)


def sent_to(mail, template, to):
    return [p for t, a, p in mail.sent if t == template and a == to]


def start(client, sam, email=USER):
    return client.post(START, json={"email": email}, headers=sam)


def confirm(client, sam, code, email=USER):
    return client.post(CONFIRM, json={"email": email, "code": code}, headers=sam)


def removed_rows(admin):
    with admin.connect() as c:
        return c.execute(
            text(
                "select business_id, user_id, target_kind, target_id, data from platform.audit_log"
                " where action = 'auth.totp_removed_by_support'"
            )
        ).all()


def test_the_right_code_removes_totp_ends_sessions_audits_and_mails(env):  # AC2-11, AC2-16
    client, idp, mail, admin, user, sam = env
    r = start(client, sam)
    assert (r.status_code, r.json()["code_ttl_minutes"], r.json()["code_max_tries"]) == (202, 10, 5)
    [params] = sent_to(mail, "totp_recovery_code", USER)
    assert sent_to(mail, "totp_recovery_code", SUPPORT) == []  # the code goes to the account only

    r = confirm(client, sam, params["code"])
    assert r.status_code == 204, r.text
    asha = one(admin, "select id from identity.users where email = :e", e=USER)
    sam_id = one(admin, "select id from identity.users where email = :e", e=SUPPORT)
    assert one(admin, "select totp_enabled_at from identity.users where id = :u", u=asha) is None
    assert not idp.user(USER).totp_enabled
    assert one(admin, "select count(*) from identity.sessions where user_id = :u and revoked_at is null", u=asha) == 0
    assert (
        one(admin, "select count(*) from identity.sessions where user_id = :u and revoke_reason = 'support'", u=asha)
        >= 1
    )
    assert removed_rows(admin) == [(None, asha, "user", asha, {"support_user_id": str(sam_id)})]
    assert sent_to(mail, "totp_off_by_support", USER) == [{}]
    assert client.get("/api/v1/me", headers=user).status_code == 401  # signed out everywhere
    assert "access_token" in signin(client, USER).json()  # no TOTP step any more
    # Support's own account is untouched.
    assert one(admin, "select totp_enabled_at is not null from identity.users where id = :u", u=sam_id)
    # The code is spent.
    assert confirm(client, sam, params["code"]).status_code == 400


def test_five_wrong_codes_void_the_code(env):  # AC2-11
    client, idp, mail, admin, _, sam = env
    start(client, sam)
    [params] = sent_to(mail, "totp_recovery_code", USER)
    wrong = "000000" if params["code"] != "000000" else "111111"
    for _ in range(5):
        r = confirm(client, sam, wrong)
        assert (r.status_code, r.json()["error"]["code"]) == (400, "code_not_accepted")
    assert confirm(client, sam, params["code"]).status_code == 400  # voided on the fifth
    assert idp.user(USER).totp_enabled and removed_rows(admin) == []
    assert one(admin, "select totp_enabled_at is not null from identity.users where email = :e", e=USER)


def test_only_support_with_totp_reaches_the_routes(env):  # AC2-11
    client, idp, mail, admin, user, sam = env
    for headers in (user, {}):  # a member, and nobody
        r = start(client, headers, SUPPORT)
        assert r.status_code == (404 if headers else 401)
        assert confirm(client, headers, "123456", SUPPORT).status_code == (404 if headers else 401)
    with admin.begin() as c:  # support without TOTP
        c.execute(text("update identity.users set totp_enabled_at = null where email = :e"), {"e": SUPPORT})
    assert start(client, sam).status_code == 404
    assert confirm(client, sam, "123456").status_code == 404
    assert sent_to(mail, "totp_recovery_code", USER) == []


@pytest.mark.parametrize("who", ["unknown", "no_totp", "support"])
def test_the_reply_is_the_same_and_no_code_goes_out(env, who):  # AC2-11
    client, idp, mail, admin, _, sam = env
    if who == "unknown":
        email = "nobody@example.com"
    elif who == "no_totp":
        email = "ravi@example.com"
        account(client, mail, idp, email, totp=False)
    else:  # support can't recover another support account
        email = "sue@support.example.com"
        account(client, mail, idp, email)
        make_support(admin, email)
    sent = len(mail.sent)
    r = start(client, sam, email)
    assert (r.status_code, r.json()) == (202, start(client, sam, USER).json())
    assert [t for t, a, _ in mail.sent[sent:] if a == email] == []
    assert (
        one(
            admin,
            "select count(*) from identity.verification_codes where email = :e and purpose = 'totp_recovery'",
            e=email,
        )
        == 0
    )


def test_the_per_email_limit_holds_across_support_users(env):
    client, _, mail, admin, _, sam = env
    for _ in range(3):  # support.totp_recovery_per_email_per_day
        assert start(client, sam).status_code == 202
    r = start(client, sam)
    assert r.status_code == 429 and "retry-after" in r.headers


def test_audit_auth_insert_admits_only_the_recovery_row_about_its_own_user(env):
    """Staff 2 (4): widening audit_auth_insert lets this one action through and nothing
    else. Written as identity_auth itself, with and without a live support caller bound."""
    _, _, _, admin, _, _ = env
    asha = one(admin, "select id from identity.users where email = :e", e=USER)
    sam = one(admin, "select id from identity.users where email = :e", e=SUPPORT)
    sam_sub = one(admin, "select cognito_sub from identity.users where id = :u", u=sam)
    biz = uuid.uuid4()

    def insert(
        *,
        bind=sam,
        action="auth.totp_removed_by_support",
        business=None,
        grant=None,
        user=asha,
        target=asha,
        kind="user",
        support=None,
    ):
        support = str(sam) if support is None else support
        with admin.connect() as c, c.begin():
            if bind is not None:
                sub = one(admin, "select cognito_sub from identity.users where id = :u", u=bind)
                c.execute(
                    text("select set_config('app.user_sub', :s, true), set_config('app.user_id', :u, true)"),
                    {"s": sub, "u": str(bind)},
                )
            c.execute(text("set local role identity_auth"))
            c.execute(
                text(
                    "insert into platform.audit_log (id, business_id, user_id, support_grant_id, action, target_kind,"
                    " target_id, data, request_id) values (gen_random_uuid(), :b, :u, :g, :a, :k, :t,"
                    " jsonb_build_object('support_user_id', cast(:s as text)), 't')"
                ),
                {"b": business, "u": user, "g": grant, "a": action, "k": kind, "t": target, "s": support},
            )

    insert()  # the one shape that passes
    refused = [
        dict(bind=None),  # no caller bound
        dict(bind=asha),  # bound caller isn't support
        dict(support=str(asha)),  # names someone else as the support user
        dict(action="auth.totp_off"),  # any other action
        dict(action="auth.signin"),
        dict(business=biz),  # a business row
        dict(grant=uuid.uuid4()),  # under a grant
        dict(target=sam),  # about another user than the row's own
        dict(kind="business"),
    ]
    for case in refused:
        with pytest.raises(exc.ProgrammingError, match="row-level security"):
            insert(**case)
    assert len(removed_rows(admin)) == 1
    assert sam_sub  # the support user is real


def test_a_support_user_cant_be_a_member_and_a_member_cant_become_support(env):  # AC2-14
    client, _, _, admin, user, _ = env
    r = client.post("/api/v1/b", json=BUSINESS, headers={**user, "Idempotency-Key": "k1"})
    assert r.status_code == 201, r.text
    business = r.json()["business_id"]
    with pytest.raises(exc.DBAPIError, match="can't be made a support user"):
        make_support(admin, USER)
    sam = one(admin, "select id from identity.users where email = :e", e=SUPPORT)
    with pytest.raises(exc.DBAPIError, match="can't be a member"), admin.begin() as c:
        c.execute(
            text(
                "insert into identity.memberships (id, business_id, user_id, role, status)"
                " values (gen_random_uuid(), :b, :u, 'admin', 'active')"
            ),
            {"b": business, "u": sam},
        )

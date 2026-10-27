"""POST /auth/reset, /auth/reset/verify and /me/sessions/revoke-all on PostgreSQL, as
app_rw (LLD-1 §5.7, §5.8, AC-2, AC-6).

Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import pytest
from sqlalchemy import text

from platform_common.auth import set_local_verifier
from platform_common.fake_auth import CLIENT_ID, ISSUER

from .auth_env import EMAIL, ORIGIN, PASSWORD, auth_env, last, one, sign_up, verify
from .conftest import PG_ADMIN_URL

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")

NEW = "a brand new passphrase"


@pytest.fixture()
def env():
    with auth_env() as e:
        client, idp, mail, _ = e
        assert verify(client, sign_up(client, mail).params["code"]).status_code == 200
        set_local_verifier(idp.jwks(), issuer=ISSUER, client_id=CLIENT_ID)
        yield e
        set_local_verifier(None)


def ask(client, email=EMAIL):
    return client.post("/api/v1/auth/reset", json={"email": email})


def reset(client, code, password=NEW, email=EMAIL):
    return client.post("/api/v1/auth/reset/verify", json={"email": email, "code": code, "new_password": password})


def signin(client, password):
    return client.post("/api/v1/auth/signin", json={"email": EMAIL, "password": password}, headers=ORIGIN)


def live(admin):
    return one(admin, "select count(*) from identity.sessions where revoked_at is null")


def test_reset_sets_the_password_and_ends_every_session(env):  # AC-6
    client, idp, mail, admin = env
    old = signin(client, PASSWORD).json()["access_token"]
    assert live(admin) == 2
    r = ask(client)
    assert (r.status_code, r.json()) == (202, {"status": "code_sent", "code_ttl_minutes": 10, "code_max_tries": 5})
    msg = last(mail)
    assert (msg.template, msg.to) == ("reset_code", EMAIL)
    r = reset(client, msg.params["code"])
    assert (r.status_code, r.json()) == (200, {"status": "password_set"}) and "set-cookie" not in r.headers
    assert live(admin) == 0
    assert one(admin, "select count(*) from identity.sessions where revoke_reason = 'password_reset'") == 2
    assert all(t.revoked for t in idp._refresh.values())  # the provider's global sign-out ran after commit
    assert last(mail).template == "password_changed"
    assert signin(client, PASSWORD).status_code == 401 and signin(client, NEW).status_code == 200
    assert client.get("/api/v1/me/businesses", headers={"authorization": f"Bearer {old}"}).status_code == 401
    with admin.connect() as c:
        rows = c.execute(
            text(
                "select a.target_kind, a.business_id, a.user_id = u.id from platform.audit_log a"
                " join identity.users u on u.email = :e where a.action = 'auth.password_reset'"
            ),
            {"e": EMAIL},
        ).all()
    assert [tuple(r) for r in rows] == [("user", None, True)]


def test_reset_for_an_unknown_email_looks_the_same_and_sends_a_notice(env):  # AC-2
    client, _, mail, admin = env
    sent = len(mail.sent)
    known, unknown = ask(client), ask(client, "nobody@example.com")
    assert (known.status_code, known.json()) == (unknown.status_code, unknown.json())
    assert [(t, to) for t, to, _ in mail.sent[sent:]] == [
        ("reset_code", EMAIL),
        ("reset_no_account", "nobody@example.com"),
    ]
    assert mail.sent[-1][2] == {}  # the notice carries no code
    assert one(admin, "select count(*) from identity.verification_codes where email = 'nobody@example.com'") == 0


def test_both_reset_branches_queue_exactly_one_after_commit_mail(env, monkeypatch):  # Staff 2, #48
    client, _, _, _ = env
    from app.modules.identity.service import reset as reset_mod

    real, queued = reset_mod.send_after_commit, []

    def counting(uow, mailer, template, to, params):
        queued.append(template)
        real(uow, mailer, template, to, params)

    monkeypatch.setattr(reset_mod, "send_after_commit", counting)
    for email in (EMAIL, "nobody@example.com"):
        queued.clear()
        assert ask(client, email).status_code == 202
        assert len(queued) == 1, (email, queued)


def test_a_wrong_or_signup_code_is_not_accepted_and_changes_nothing(env):
    client, idp, mail, admin = env
    ask(client)
    code = last(mail).params["code"]
    wrong = "000000" if code != "000000" else "111111"
    r = reset(client, wrong)
    assert (r.status_code, r.json()["error"]["code"]) == (400, "code_not_accepted")
    sign_up(client, mail, email="new@example.com")  # a sign-up code can't reset anything
    r = reset(client, last(mail).params["code"], email="new@example.com")
    assert (r.status_code, r.json()["error"]["code"]) == (400, "code_not_accepted")
    assert idp.user(EMAIL).password == PASSWORD and live(admin) == 1


def test_a_weak_password_spends_no_try(env):
    client, _, mail, admin = env
    ask(client)
    r = reset(client, last(mail).params["code"], password="password")
    assert (r.status_code, r.json()["error"]["code"]) == (422, "password_weak")
    assert one(admin, "select tries from identity.verification_codes where purpose = 'reset'") == 0
    assert reset(client, last(mail).params["code"]).status_code == 200


def test_reset_shares_the_per_email_bucket_with_sign_up(env):  # §5.8
    client, _, mail, _ = env
    # The fixture's sign-up already spent one of the five.
    for _ in range(4):
        assert ask(client).status_code == 202
    assert ask(client).status_code == 429


def test_revoke_all_ends_every_session_of_the_caller_only(env):  # §5.7
    client, idp, mail, admin = env
    a1 = signin(client, PASSWORD).json()["access_token"]
    signin(client, PASSWORD)
    ravi = verify(client, sign_up(client, mail, email="ravi@example.com").params["code"], email="ravi@example.com")
    assert ravi.status_code == 200
    r = client.post("/api/v1/me/sessions/revoke-all", headers={"authorization": f"Bearer {a1}"})
    assert r.status_code == 204 and "Max-Age=0" in r.headers["set-cookie"]
    assert one(admin, "select count(*) from identity.sessions where revoke_reason = 'signout_all'") == 3
    assert live(admin) == 1  # Ravi's
    assert all(t.revoked for t in idp._refresh.values() if t.sub == idp.user(EMAIL).sub)
    assert not any(t.revoked for t in idp._refresh.values() if t.sub == idp.user("ravi@example.com").sub)
    assert one(admin, "select data from platform.audit_log where action = 'auth.signout_all'") == {"sessions": 3}
    assert client.post("/api/v1/me/sessions/revoke-all", headers={"authorization": f"Bearer {a1}"}).status_code == 401

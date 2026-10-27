"""LLD-2 part A on PostgreSQL, as app_rw with FORCE row-level security: invites, members
and the audit log through the API (LLD-2 §12, AC2-1 to AC2-8, AC2-12, AC2-16, AC2-18,
AC2-19). Callers are X-Debug-User users, whose email is `<sub>@debug.invalid`.

Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import threading
import uuid

import pytest
from sqlalchemy import text

from app import api as app_api
from app.modules.identity import api_team, providers
from platform_common.mailer import FakeMailer
from platform_common.permissions import PERMISSION_ROLES, Permission

from .conftest import PG_ADMIN_URL, PG_OWNER, seed_member

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


def H(sub: str) -> dict:
    return {"x-debug-user": sub}


def email(sub: str) -> str:
    return f"{sub}@debug.invalid"


@pytest.fixture()
def team(pg_client):
    client, svc = pg_client
    mail = FakeMailer()
    app_api.app.dependency_overrides[providers.mailer] = lambda: mail
    tid = client.post("/api/v1/identity/tenants", json={"name": "Alice Co"}, headers=H("alice")).json()["id"]
    yield client, svc, mail, tid
    app_api.app.dependency_overrides.pop(providers.mailer, None)


def owner_sql(sql: str, **params):
    with PG_OWNER["engine"].begin() as c:
        result = c.execute(text(sql), params)
        return result.all() if result.returns_rows else []


def invite(client, tid, sub_or_email, role="billing", by="alice", key=None):
    to = sub_or_email if "@" in sub_or_email else email(sub_or_email)
    return client.post(
        f"/api/v1/b/{tid}/invitations",
        json={"email": to, "role": role},
        headers={**H(by), "idempotency-key": key or str(uuid.uuid4())},
    )


def token(mail, sub: str) -> str:
    return mail.last("invitation", email(sub))["link"].rsplit("/", 1)[1]


def join(client, mail, tid, sub, role="billing"):
    assert invite(client, tid, sub, role).status_code == 201
    r = client.post(f"/api/v1/me/invitations/{token(mail, sub)}/accept", headers=H(sub))
    assert r.status_code == 200, r.text


def actions(tid) -> list[str]:
    return [r.action for r in owner_sql("select action from platform.audit_log where business_id = :b order by at, id", b=tid)]


def members(client, tid, by="alice") -> dict:
    r = client.get(f"/api/v1/b/{tid}/members", headers=H(by))
    assert r.status_code == 200, r.text
    return {m["email"]: m for m in r.json()["members"]}


def not_found(client, tid):
    return client.get(f"/api/v1/b/{uuid.uuid4()}/members", headers=H("alice")).json()


# --- Invites and accepting (§4.1-4.4) -------------------------------------------


def test_invite_preview_and_accept(team):
    client, _, mail, tid = team
    key = str(uuid.uuid4())
    r = invite(client, tid, "Bob@Debug.Invalid ", "billing", key=key)
    assert r.status_code == 201, r.text
    assert r.json()["email"] == "bob@debug.invalid" and r.json()["status"] == "pending"
    # The same Idempotency-Key replays the answer: one invite, one mail, one audit row.
    assert invite(client, tid, "Bob@Debug.Invalid ", "billing", key=key).json() == r.json()
    assert [m[1] for m in mail.sent] == ["bob@debug.invalid"]
    params = mail.last("invitation", "bob@debug.invalid")
    assert params["business_name"] == "Alice Co" and params["role_label"] == "Billing"
    assert params["link"].startswith("http://localhost:5173/invite/")
    tok = token(mail, "bob")
    # The token is stored only as its hash.
    assert owner_sql("select count(*) from identity.invitations where token_hash = :t", t=tok)[0][0] == 0

    preview = client.get(f"/api/v1/me/invitations/{tok}", headers=H("bob"))
    assert preview.status_code == 200 and preview.json()["business_name"] == "Alice Co"
    # AC2-7: a forwarded link opened by another account looks like an unknown token.
    unknown = client.get(f"/api/v1/me/invitations/{'x' * 43}", headers=H("bob"))
    forwarded = client.get(f"/api/v1/me/invitations/{tok}", headers=H("eve"))
    assert forwarded.status_code == unknown.status_code == 404 and forwarded.json() == unknown.json()
    assert client.post(f"/api/v1/me/invitations/{tok}/accept", headers=H("eve")).status_code == 404

    r = client.post(f"/api/v1/me/invitations/{tok}/accept", headers=H("bob"))
    assert r.status_code == 200 and r.json() == {"business_id": tid}
    # A retry by the same user answers the same and writes nothing more.
    assert client.post(f"/api/v1/me/invitations/{tok}/accept", headers=H("bob")).json() == {"business_id": tid}
    assert client.get(f"/api/v1/identity/tenants/{tid}", headers=H("bob")).json()["role"] == "billing"
    assert actions(tid) == ["business.create", "member.invite", "member.accept"]
    team_list = client.get(f"/api/v1/b/{tid}/members", headers=H("alice")).json()
    assert team_list["invites"] == []
    assert {m["email"]: m["role"] for m in team_list["members"]} == {
        "alice@debug.invalid": "owner",
        "bob@debug.invalid": "billing",
    }
    # No email, token or code in any audit row's data.
    assert all("@" not in str(d) for (d,) in owner_sql("select data from platform.audit_log"))


def test_resent_cancelled_and_expired_tokens_cannot_be_accepted(team):
    client, _, mail, tid = team
    inv = invite(client, tid, "bob").json()
    old = token(mail, "bob")
    r = client.post(f"/api/v1/b/{tid}/invitations/{inv['id']}/resend", headers=H("alice"))
    assert r.status_code == 200, r.text
    new = token(mail, "bob")
    assert new != old
    assert client.post(f"/api/v1/me/invitations/{old}/accept", headers=H("bob")).status_code == 404

    assert client.post(f"/api/v1/b/{tid}/invitations/{inv['id']}/cancel", headers=H("alice")).json()["status"] == "cancelled"
    assert client.post(f"/api/v1/b/{tid}/invitations/{inv['id']}/cancel", headers=H("alice")).status_code == 200
    assert client.post(f"/api/v1/me/invitations/{new}/accept", headers=H("bob")).status_code == 404
    assert actions(tid).count("member.invite_cancel") == 1

    invite(client, tid, "carol")
    owner_sql("update identity.invitations set expires_at = now() - interval '1 second' where email = :e", e=email("carol"))
    assert client.get(f"/api/v1/me/invitations/{token(mail, 'carol')}", headers=H("carol")).status_code == 404
    assert client.post(f"/api/v1/me/invitations/{token(mail, 'carol')}/accept", headers=H("carol")).status_code == 404
    listed = client.get(f"/api/v1/b/{tid}/members", headers=H("alice")).json()["invites"]
    assert [(i["email"], i["status"]) for i in listed] == [(email("carol"), "expired")]
    # A lapsed invite doesn't block a new one.
    assert invite(client, tid, "carol").status_code == 201


def test_app_rw_cannot_accept_or_revive_an_invite_directly(team):
    """Staff 2 on #39: with the route checks bypassed, app_rw bound as the owner still can't
    accept, revive or re-extend an invite; only the routes' own moves go through."""
    client, svc, mail, tid = team
    bob = invite(client, tid, "bob").json()["id"]
    join(client, mail, tid, "carol")

    def as_owner(sql, **params):
        with svc.begin() as c:
            c.execute(
                text("select set_config('app.user_id', :u, true), set_config('app.tenant_id', :t, true)"),
                {"u": uid("alice"), "t": str(tid)},
            )
            return c.execute(text(sql), params).rowcount

    def refused(sql, sqlstate="23514", **params):
        with pytest.raises(Exception) as e:
            as_owner(sql, **params)
        assert getattr(e.value.orig, "sqlstate", None) == sqlstate, e.value

    me = uid("alice")
    # The acceptance columns aren't granted at all; status is, and the trigger stops the move.
    refused("update identity.invitations set accepted_by_user = :u, accepted_at = now() where id = :i",
            sqlstate="42501", u=me, i=bob)
    refused("update identity.invitations set status = 'accepted' where id = :i", i=bob)
    refused("update identity.invitations set delivery = 'sent' where id = :i", sqlstate="42501", i=bob)
    refused("update identity.invitations set status = 'expired' where id = :i", i=bob)  # not lapsed yet

    assert client.post(f"/api/v1/b/{tid}/invitations/{bob}/cancel", headers=H("alice")).status_code == 200
    refused("update identity.invitations set status = 'pending', cancelled_at = null, cancelled_by = null"
            " where id = :i", i=bob)
    refused("update identity.invitations set expires_at = now() + interval '7 days' where id = :i", i=bob)
    carol = "select id from identity.invitations where email = :e"
    refused(f"update identity.invitations set status = 'cancelled', cancelled_at = now(), cancelled_by = :u"
            f" where id = ({carol})", u=me, e=email("carol"))
    refused(f"update identity.invitations set email = :x where id = ({carol})", sqlstate="42501", e=email("carol"), x=email("eve"))
    assert [s for (s,) in owner_sql("select status from identity.invitations order by email")] == ["cancelled", "accepted"]


def test_the_invite_snapshots_the_business_name_and_resend_refreshes_it(team):
    """EM after #39: the mail and preview show the profile's display name as it was when
    the invite went out; a rename shows only after a resend."""
    client, _, mail, tid = team
    owner_sql(
        "insert into business.profiles (business_id, registration_kind, enrolment_number, state_code, trade_name,"
        " updated_by) values (:b, 'enrolment', 'E', '19', 'Alice Traders', :u)",
        b=tid, u=uid("alice"),
    )
    inv = invite(client, tid, "bob").json()["id"]
    assert mail.last("invitation", email("bob"))["business_name"] == "Alice Traders"
    owner_sql("update business.profiles set trade_name = 'Alice Exports' where business_id = :b", b=tid)

    def preview_name():
        r = client.get(f"/api/v1/me/invitations/{token(mail, 'bob')}", headers=H("bob"))
        assert r.status_code == 200, r.text
        return r.json()["business_name"]

    assert preview_name() == "Alice Traders"
    assert client.post(f"/api/v1/b/{tid}/invitations/{inv}/resend", headers=H("alice")).status_code == 200
    assert mail.last("invitation", email("bob"))["business_name"] == "Alice Exports"
    assert preview_name() == "Alice Exports"


def test_app_rw_cannot_insert_an_invite_already_accepted(team):
    """Staff 2 on #39: the insert side of the status guard."""
    client, svc, _, tid = team
    with pytest.raises(Exception) as e, svc.begin() as c:
        c.execute(
            text("select set_config('app.user_id', :u, true), set_config('app.tenant_id', :t, true)"),
            {"u": uid("alice"), "t": str(tid)},
        )
        c.execute(
            text(
                "insert into identity.invitations (id, business_id, email, role, status, token_hash, invited_by_user,"
                " expires_at, accepted_by_user, accepted_at)"
                " values (gen_random_uuid(), :b, :e, 'admin', 'accepted', repeat('a', 64), :u, now(), :u, now())"
            ),
            {"b": tid, "e": email("mallory"), "u": uid("alice")},
        )
    assert getattr(e.value.orig, "sqlstate", None) == "23514", e.value
    assert owner_sql("select count(*) from identity.invitations")[0][0] == 0


def test_two_concurrent_accepts_make_one_membership(team):
    """AC2-8, on two connections: the second waits on the invite's row lock."""
    client, svc, mail, tid = team
    invite(client, tid, "bob")
    h = __import__("hashlib").sha256(token(mail, "bob").encode()).hexdigest()
    bob = owner_sql("select identity.dev_ensure_user('bob')")[0][0]
    results = []

    def accept(conn):
        conn.execute(text("select set_config('app.user_id', :u, true)"), {"u": str(bob)})
        results.append(
            conn.execute(
                text("select identity.auth_accept_invitation(:h, gen_random_uuid(), gen_random_uuid())"), {"h": h}
            ).scalar()
        )

    with svc.connect() as c1, svc.connect() as c2:
        t1 = c1.begin()
        accept(c1)
        t2 = c2.begin()
        worker = threading.Thread(target=accept, args=(c2,))
        worker.start()
        worker.join(0.5)
        assert worker.is_alive()  # blocked on the lock
        t1.commit()
        worker.join(5)
        t2.commit()
    assert [str(r) for r in results] == [tid, tid]
    assert owner_sql("select count(*) from identity.memberships where business_id = :b", b=tid)[0][0] == 2
    assert actions(tid).count("member.accept") == 1


def test_invite_refusals(team):
    client, _, mail, tid = team
    join(client, mail, tid, "bob")
    r = invite(client, tid, "bob")
    assert r.status_code == 422 and r.json()["error"]["code"] == "already_member"
    invite(client, tid, "carol")
    r = invite(client, tid, "carol")
    assert r.status_code == 409 and r.json()["error"]["code"] == "invite_pending"
    bob = owner_sql("select identity.dev_ensure_user('bob')")[0][0]
    owner_sql("update identity.memberships set status = 'deactivated' where user_id = :u", u=bob)
    r = invite(client, tid, "bob")
    assert r.status_code == 409 and r.json()["error"]["code"] == "member_deactivated"
    # An owner can't be invited (owners come from role changes only).
    assert invite(client, tid, "dan", "owner").status_code == 422


def test_the_21st_invite_mail_in_a_day_is_refused(team):
    """AC2-19. Invites and resends both count; 2 are sent here, 18 seeded."""
    client, _, mail, tid = team
    alice = owner_sql("select identity.dev_ensure_user('alice')")[0][0]
    inv = invite(client, tid, "bob").json()
    client.post(f"/api/v1/b/{tid}/invitations/{inv['id']}/resend", headers=H("alice"))
    for _ in range(18):
        owner_sql(
            "insert into platform.audit_log (id, business_id, user_id, action, target_kind, request_id)"
            " values (gen_random_uuid(), :b, :u, 'member.invite', 'invitation', 'seed')",
            b=tid, u=alice,
        )
    r = invite(client, tid, "carol")
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0
    assert client.post(f"/api/v1/b/{tid}/invitations/{inv['id']}/resend", headers=H("alice")).status_code == 429
    assert len(mail.sent) == 2


# --- Roles (AC2-1) ----------------------------------------------------------------


@pytest.mark.parametrize("role", ["owner", "admin", "billing", "ca"])
def test_every_role_cell_for_the_team_routes(team, role):
    client, _, mail, tid = team
    if role != "owner":
        seed_member(tid, "pat", role)
        who = "pat"
    else:
        who = "alice"
    cells = {
        Permission.MEMBERS_MANAGE: lambda: client.get(f"/api/v1/b/{tid}/members", headers=H(who)),
        Permission.AUDIT_VIEW: lambda: client.get(f"/api/v1/b/{tid}/audit-log", headers=H(who)),
    }
    for permission, call in cells.items():
        r = call()
        if role in {r.value for r in PERMISSION_ROLES[permission]}:
            assert r.status_code == 200, (permission, r.text)
        else:
            assert r.status_code == 404 and r.json() == not_found(client, tid), permission
    r = invite(client, tid, "zed", by=who)
    assert r.status_code == (201 if role in ("owner", "admin") else 404)


def test_outsiders_and_bad_ids_get_the_unknown_business_answer(team):
    client, _, _, tid = team
    for path in ("members", "audit-log"):
        assert client.get(f"/api/v1/b/{tid}/{path}", headers=H("eve")).json() == not_found(client, tid)
    assert client.get("/api/v1/b/not-a-uuid/members", headers=H("alice")).status_code == 404
    r = client.post(f"/api/v1/b/{tid}/members/not-a-uuid/deactivate", json={"reason": "x"}, headers=H("alice"))
    assert r.status_code == 404


# --- Members (§4.6) ---------------------------------------------------------------


def uid(sub):
    return str(owner_sql("select identity.dev_ensure_user(:s)", s=sub)[0][0])


def act(client, tid, sub, action, by="alice", **body):
    path = f"/api/v1/b/{tid}/members/{uid(sub)}"
    if action == "role":
        return client.patch(path, json=body, headers=H(by))
    return client.post(f"{path}/{action}", json=body, headers=H(by))


def test_owner_rules(team):
    """AC2-2 and AC2-3."""
    client, _, _, tid = team
    seed_member(tid, "erin", "admin")
    seed_member(tid, "sam", "billing")
    for action, body in (("deactivate", {"reason": "x"}), ("role", {"role": "admin"})):
        r = act(client, tid, "alice", action, by="erin", **body)
        assert r.status_code == 409 and r.json()["error"]["code"] == "owner_rule"
    r = act(client, tid, "sam", "role", by="erin", role="owner")
    assert r.status_code == 409 and r.json()["error"]["message"] == "Only an owner can change an owner"
    # The last active owner, even acting on themselves.
    for action, body in (("deactivate", {"reason": "x"}), ("role", {"role": "admin"})):
        r = act(client, tid, "alice", action, **body)
        assert r.status_code == 409 and r.json()["error"]["message"] == "A business needs at least one owner"
    # With a second owner, an owner can demote the other.
    assert act(client, tid, "sam", "role", role="owner").json()["role"] == "owner"
    assert act(client, tid, "sam", "role", role="admin").json()["role"] == "admin"
    assert actions(tid).count("member.role_change") == 2
    # Admin vs non-owner: allowed.
    assert act(client, tid, "sam", "deactivate", by="erin", reason="left").json()["status"] == "deactivated"


def test_the_trigger_refuses_when_the_route_check_is_bypassed(team, monkeypatch):
    client, _, _, tid = team
    seed_member(tid, "carol", "owner")
    seed_member(tid, "erin", "admin")
    monkeypatch.setattr(api_team, "_caller_is_owner", lambda uow: True)
    r = act(client, tid, "alice", "deactivate", by="erin", reason="x")
    assert r.status_code == 409 and r.json()["error"]["code"] == "owner_rule"
    assert members(client, tid)["alice@debug.invalid"]["status"] == "active"
    assert "members.deactivate" not in actions(tid)


def test_only_the_owner_trigger_reads_as_owner_rule(team):
    """Staff on #39: T-013 raises IDO01; any other refusal (RLS's 42501) stays an error."""
    client, svc, _, tid = team
    seed_member(tid, "erin", "admin")

    def as_erin(sql):
        with pytest.raises(Exception) as e, svc.begin() as c:
            c.execute(
                text("select set_config('app.user_id', :u, true), set_config('app.tenant_id', :t, true)"),
                {"u": uid("erin"), "t": str(tid)},
            )
            c.execute(text(sql), {"b": tid, "u": uid("alice")})
        return getattr(e.value.orig, "sqlstate", None)

    assert as_erin("update identity.memberships set status = 'deactivated' where business_id = :b and user_id = :u") == api_team.OWNER_RULE_SQLSTATE
    assert api_team.OWNER_RULE_SQLSTATE != "42501"


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_a_blank_reason_changes_nothing(team, reason):
    """AC2-4."""
    client, _, _, tid = team
    seed_member(tid, "sam", "billing")
    for action in ("deactivate", "reactivate"):
        r = act(client, tid, "sam", action, reason=reason)
        assert r.status_code == 422 and r.json()["error"]["code"] == "reason_required"
    assert members(client, tid)["sam@debug.invalid"]["status"] == "active"
    assert actions(tid) == ["business.create"]


def test_deactivation_takes_effect_on_the_next_request_in_that_business_only(team):
    """AC2-5 and the API half of AC2-6; reactivation gives back the previous role."""
    client, _, _, tid = team
    other = client.post("/api/v1/identity/tenants", json={"name": "Other Co"}, headers=H("olga")).json()["id"]
    seed_member(tid, "bob", "admin")
    seed_member(other, "bob", "ca")
    assert client.get(f"/api/v1/b/{tid}/members", headers=H("bob")).status_code == 200
    r = act(client, tid, "bob", "deactivate", reason=" left the firm ")
    assert r.json()["deactivation_reason"] == "left the firm" and r.json()["deactivated_by_name"] == "alice@debug.invalid"
    assert client.get(f"/api/v1/b/{tid}/members", headers=H("bob")).status_code == 404
    assert client.get(f"/api/v1/identity/tenants/{tid}", headers=H("bob")).status_code == 404
    assert client.get(f"/api/v1/identity/tenants/{other}", headers=H("bob")).json()["role"] == "ca"
    # A retry answers the same and writes one audit row.
    assert act(client, tid, "bob", "deactivate", reason="again").json()["status"] == "deactivated"
    assert act(client, tid, "bob", "reactivate", reason="back").json()["role"] == "admin"
    assert actions(tid).count("members.deactivate") == 1
    assert owner_sql(
        "select reason from platform.audit_log where action = 'members.deactivate' and business_id = :b", b=tid
    ) == [("left the firm",)]


def test_a_cas_role_changes_only_through_a_new_invite(team):
    client, _, _, tid = team
    seed_member(tid, "cathy", "ca")
    seed_member(tid, "sam", "billing")
    for sub, role in (("cathy", "admin"), ("sam", "ca")):
        r = act(client, tid, sub, "role", role=role)
        assert r.status_code == 409 and r.json()["error"]["code"] == "ca_needs_invite"


def test_an_accepted_invite_reactivates_a_deactivated_member_with_the_invited_role(team):
    client, _, mail, tid = team
    seed_member(tid, "bob", "admin")
    act(client, tid, "bob", "deactivate", reason="x")
    owner_sql(
        "insert into identity.invitations (id, business_id, email, role, token_hash, invited_by_user, expires_at)"
        " values (gen_random_uuid(), :b, :e, 'ca', encode(sha256('tok'), 'hex'), :u, now() + interval '1 day')",
        b=tid, e=email("bob"), u=uid("alice"),
    )
    assert client.post("/api/v1/me/invitations/tok/accept", headers=H("bob")).status_code == 200
    assert members(client, tid)["bob@debug.invalid"]["role"] == "ca"


# --- member_profiles (AC2-18) -----------------------------------------------------


def test_member_profiles_show_only_the_bound_business(team):
    client, svc, _, tid = team
    other = client.post("/api/v1/identity/tenants", json={"name": "B Co"}, headers=H("olga")).json()["id"]
    seed_member(other, "alice", "admin")  # alice shares B with olga
    ids = [uid("alice"), uid("olga")]

    def profiles(sub, tenant):
        with svc.begin() as c:
            c.execute(
                text("select set_config('app.user_id', :u, true), set_config('app.tenant_id', :t, true)"),
                {"u": uid(sub), "t": str(tenant)},
            )
            return {r.email for r in c.execute(text("select * from identity.member_profiles(cast(:ids as uuid[]))"), {"ids": ids})}

    assert profiles("alice", tid) == {"alice@debug.invalid"}
    assert profiles("alice", other) == {"alice@debug.invalid", "olga@debug.invalid"}
    assert profiles("olga", tid) == set()  # not a member of A
    owner_sql("update identity.memberships set status = 'deactivated' where business_id = :b and user_id = :u", b=other, u=uid("alice"))
    assert profiles("alice", other) == set()


# --- Audit log (§7, AC2-12 without the CSV export) ----------------------------


def test_audit_log_view_filters_and_pages(team):
    client, _, mail, tid = team
    seed_member(tid, "erin", "admin")
    join(client, mail, tid, "bob", "billing")
    act(client, tid, "bob", "deactivate", reason="left")
    alice = uid("alice")
    for _ in range(55):
        owner_sql(
            "insert into platform.audit_log (id, business_id, user_id, action, target_kind, request_id)"
            " values (gen_random_uuid(), :b, :u, 'returns.unlock', 'return_instance', 'seed')",
            b=tid, u=alice,
        )
    first = client.get(f"/api/v1/b/{tid}/audit-log", headers=H("erin")).json()
    assert len(first["items"]) == 50 and first["next_cursor"]
    second = client.get(f"/api/v1/b/{tid}/audit-log", params={"cursor": first["next_cursor"]}, headers=H("erin")).json()
    total = first["items"] + second["items"]
    assert second["next_cursor"] is None and len(total) == 55 + 4
    # Newest first, nothing repeated or skipped across the page boundary (each row here
    # was committed on its own, so their times differ).
    ats = [i["at"] for i in total]
    assert ats == sorted(ats, reverse=True) and len(set(ats)) == len(ats)

    team_rows = client.get(f"/api/v1/b/{tid}/audit-log", params={"kind": "team_settings"}, headers=H("alice")).json()["items"]
    assert [i["action"] for i in team_rows] == ["members.deactivate", "member.accept", "member.invite", "business.create"]
    gone = team_rows[0]
    assert gone["reason"] == "left" and gone["action_label"] == "Deactivated a member"
    assert gone["actor"] == {"kind": "member", "name": "alice@debug.invalid", "user_id": alice}
    assert gone["target"]["href"] == f"/b/{tid}/settings/team"
    assert team_rows[2]["details"] == {"role": "billing"}
    by_bob = client.get(f"/api/v1/b/{tid}/audit-log", params={"actor": uid("bob")}, headers=H("alice")).json()["items"]
    assert [i["action"] for i in by_bob] == ["member.accept"]
    assert client.get(f"/api/v1/b/{tid}/audit-log", params={"cursor": "junk"}, headers=H("alice")).status_code == 400
    # Another business's rows never show, whatever the filter.
    other = client.post("/api/v1/identity/tenants", json={"name": "O"}, headers=H("olga")).json()["id"]
    assert [i["action"] for i in client.get(f"/api/v1/b/{other}/audit-log", headers=H("olga")).json()["items"]] == [
        "business.create"
    ]

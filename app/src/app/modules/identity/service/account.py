"""The signed-in user's own account (LLD-1 §5.9): change password, GET and PATCH /me.

Change password can't take me_uow as a dependency, because rate.hit must commit before
the first unit of work opens (as in service/signup.py):
  policy check -> tx A resolve the caller as me_uow does, read the email
  -> rate.hit (the sign-in per-email bucket) -> provider ChangePassword with the
  caller's access token -> tx B revoke every session of the caller (this one too),
  audit -> after commit: provider global sign-out, mail password_changed.
tx B binds the user directly rather than resolving the session again: the provider
has already changed the password, so the sessions are revoked even if this one ended
in between.
"""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import text

from platform_common import audit, rate
from platform_common.auth import Caller
from platform_common.authprovider import AuthProvider, AuthRefused
from platform_common.errors import AppError, Deny
from platform_common.mailer import Mailer, send_after_commit
from platform_common.permissions import Permission, has_permission
from platform_common.uow import Principal, UnitOfWork, unit_of_work

from ..interface import list_my_businesses, resolve_principal
from . import limits
from .passwords import check_password

QUARTER_HOUR = timedelta(minutes=15)


class CurrentPasswordWrong(AppError):
    status = 422
    code = "current_password_wrong"

    def __init__(self):
        super().__init__(message="the current password is wrong", field="current_password")


def change_password(
    caller: Caller,
    access_token: str,
    current: str,
    new: str,
    request_id: str,
    idp: AuthProvider,
    mail: Mailer,
    today: date,
) -> None:
    """§5.9. Raises Invalid("password_weak"), Deny("session_invalid"), RateLimited or
    CurrentPasswordWrong."""
    check_password(new)  # before anything else, so a weak password spends no try
    with unit_of_work(Principal(user_sub=caller.user_sub, request_id=request_id)) as uow:  # tx A
        me = resolve_principal(uow.tx, caller, None, request_id)
        email = uow.tx.execute(text("select email from identity.auth_user_by_sub(:s)"), {"s": me.user_sub}).scalar()
    if email is None:  # the resolver found the user by this sub, so only drift gets here
        raise Deny("session_invalid")
    per_email = limits.read(("auth.signin_per_email_per_15min",), today, request_id)["auth.signin_per_email_per_15min"]
    rate.hit(rate.bucket("signin:email", email), per_email, QUARTER_HOUR)
    try:
        idp.change_password(access_token, current, new)
    except AuthRefused:
        raise CurrentPasswordWrong() from None

    with unit_of_work(Principal(user_sub=None, request_id=request_id)) as uow:  # tx B
        uow.become_user(me.user_id, me.user_sub)
        uow.tx.execute(text("select * from identity.auth_revoke_my_sessions('password_change')")).all()
        audit.record(uow, "auth.password_change", "user", me.user_id, user_level=True)
        sub = me.user_sub
        uow.after_commit(lambda: idp.global_sign_out(sub))  # a failure is logged; the rows are revoked
        send_after_commit(uow, mail, "password_changed", email, {})


@dataclass(frozen=True)
class MyMembership:
    business_id: uuid.UUID
    display_name: str
    gstin: str | None
    role: str
    permissions: list[str]  # in the matrix's order, so the SPA can hide what the role can't do


@dataclass(frozen=True)
class Me:
    user_id: uuid.UUID
    email: str
    name: str | None
    totp_enabled: bool
    memberships: list[MyMembership]


def _user(uow: UnitOfWork):
    # users_self: app_rw sees only the bound user's row.
    return uow.tx.execute(text("select id, email, name, totp_enabled_at is not null as totp from identity.users")).one()


def get_me(uow: UnitOfWork) -> Me:
    """GET /me on the caller's me_uow."""
    u = _user(uow)
    uow.become_read_only()  # list_my_businesses reads through app_ro policies
    cards = list_my_businesses(uow.tx, uow.principal.user_id)
    return Me(
        u.id,
        u.email,
        u.name,
        u.totp,
        [
            MyMembership(
                c.business_id,
                c.display_name,
                c.gstin,
                c.role,
                [p.value for p in Permission if has_permission(c.role, p)],
            )
            for c in cards
        ],
    )


def set_name(uow: UnitOfWork, name: str | None) -> Me:
    """PATCH /me. app_rw may update only `name`, and users_self_update only its own row."""
    uow.tx.execute(text("update identity.users set name = :n where id = :i"), {"n": name, "i": uow.principal.user_id})
    return get_me(uow)

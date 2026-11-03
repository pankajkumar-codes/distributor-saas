"""TOTP enrolment on the caller's me_uow (LLD-1 §5.9).

  setup and confirm are refused with 409 totp_already_on while TOTP is on.
  setup:   provider AssociateSoftwareToken with the caller's access token -> the secret,
           which goes back to the SPA for the QR code and is never logged or stored here.
  confirm: provider VerifySoftwareToken (and turns TOTP on) -> users.totp_enabled_at,
           audit auth.totp_on, mail totp_on after commit.
  remove:  refused with 409 totp_already_off when it's off (no audit row, no mail); then
           step-up: the token's auth_time must be within auth.stepup_minutes,
           else 409 reauth_required -> provider removes TOTP -> clear totp_enabled_at,
           audit auth.totp_off, mail totp_off after commit.
The provider decides whether sign-in asks for a code; totp_enabled_at only mirrors it
for GET /me. users.totp_enabled_at is set through identity.auth_set_my_totp, which
acts for the bound caller only.
"""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text

from app.modules.refdata import value_on
from platform_common import audit
from platform_common.auth import Caller
from platform_common.authprovider import AuthProvider, AuthRefused
from platform_common.errors import AppError, Conflict, Deny, RateLimited
from platform_common.mailer import Mailer, send_after_commit
from platform_common.uow import UnitOfWork


class TotpCodeWrong(AppError):
    status = 422
    code = "totp_not_accepted"

    def __init__(self):
        super().__init__(message="the code is wrong; try the current one", field="code")


def setup(uow: UnitOfWork, access_token: str, idp: AuthProvider) -> str:
    _refuse_if_on(uow)
    try:
        return idp.associate_totp(access_token)
    except AuthRefused as e:
        raise _refusal(e) from None


def confirm(uow: UnitOfWork, access_token: str, code: str, idp: AuthProvider, mail: Mailer) -> None:
    _refuse_if_on(uow)
    try:
        accepted = idp.verify_totp(access_token, code)
    except AuthRefused as e:
        raise _refusal(e) from None
    if not accepted:
        raise TotpCodeWrong()
    _record(uow, mail, on=True)


def remove(uow: UnitOfWork, caller: Caller, idp: AuthProvider, mail: Mailer, now: datetime, today: date) -> None:
    if not _is_on(uow):
        raise Conflict("totp_already_off", "two-step sign-in is already off")
    minutes = value_on(uow.tx, "auth.stepup_minutes", today)
    try:  # API Gateway passes claims as strings
        signed_in_at = datetime.fromtimestamp(int(caller.claims["auth_time"]), UTC)
    except (KeyError, TypeError, ValueError):
        signed_in_at = None
    if signed_in_at is None or now - signed_in_at > timedelta(minutes=minutes):
        raise Conflict("reauth_required", "sign in again to turn off two-step sign-in")
    try:
        idp.remove_totp(uow.principal.user_sub)
    except AuthRefused as e:
        raise _refusal(e) from None
    _record(uow, mail, on=False)


def _refusal(e: AuthRefused) -> Exception:
    """As account._refusal: an access token the provider no longer accepts is 401."""
    if e.code == "token_invalid":
        return Deny("session_invalid")
    if e.code == "rate_limited":
        return RateLimited(retry_after=60)
    return RuntimeError(f"totp: unexpected provider refusal {e.code}")  # a 500, never a guess


def _refuse_if_on(uow: UnitOfWork) -> None:
    """A session without a fresh step-up must not replace the factor: changing it means
    turning TOTP off (which needs the step-up), then enrolling again (Staff 2, #60)."""
    if _is_on(uow):
        raise Conflict("totp_already_on", "two-step sign-in is already on; turn it off first to change it")


def _is_on(uow: UnitOfWork) -> bool:
    return uow.tx.execute(
        text("select totp_enabled_at is not null from identity.users where id = :me"), {"me": uow.principal.user_id}
    ).scalar_one()


def _record(uow: UnitOfWork, mail: Mailer, *, on: bool) -> None:
    if not uow.tx.execute(text("select identity.auth_set_my_totp(:on)"), {"on": on}).scalar():
        raise RuntimeError("auth_set_my_totp found no bound user under me_uow")
    audit.record(uow, "auth.totp_on" if on else "auth.totp_off", "user", uow.principal.user_id, user_level=True)
    # users_self also limits app_rw to the caller's row; the filter says so here too.
    email = uow.tx.execute(
        text("select email from identity.users where id = :me"), {"me": uow.principal.user_id}
    ).scalar_one()
    send_after_commit(uow, mail, "totp_on" if on else "totp_off", email, {})

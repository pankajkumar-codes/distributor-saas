"""Local demo only: prints the two-step code where the sign-up codes are printed.

The fake sign-in provider's two-step code is not what a phone's authenticator app shows, so a person trying the
demo could never turn two-step sign-in on or pass it. The code is written to the local mail file (the demo's
terminal prints it). This does nothing unless the environment is a debug one AND the provider is the fake one, so
it cannot run in AWS, where the provider is Cognito and the mailer is the queue.
"""

import logging

from platform_common.auth import debug_env
from platform_common.authprovider import AuthProvider
from platform_common.mailer import Mailer

log = logging.getLogger(__name__)


def print_two_step_code(
    idp: AuthProvider, mail: Mailer, *, access_token: str | None = None, email: str | None = None
) -> None:
    if not debug_env():
        return
    find = getattr(idp, "demo_two_step", None)
    if find is None:
        return
    found = find(access_token=access_token, email=email)
    if found is None:
        return
    try:
        mail.send("demo_totp_code", found[0], {"code": found[1]})
    except Exception:  # the demo's hint must never break the request
        log.exception("demo two-step code was not written")

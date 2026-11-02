"""CognitoAuthProvider: the AuthProvider for AWS (LLD-1 §7.2, L1-5).

It takes a cognito-idp client rather than building one, because boto3 may only be
imported in platform_common/aws.py (D-039); providers.py builds it with
aws.cognito_client() on Lambda. Tests drive it with botocore's Stubber.

Every Cognito error maps to one of our AuthRefused codes in `_refusal`. The error's
message is read only to tell a bad access token from a wrong password (both are
NotAuthorizedException) and is never logged, because it can echo input. An error we
don't know is a RuntimeError (a 500) with Cognito's request ID logged.

Usernames: the pool signs in by email (username_attributes = email), so Cognito's
username is the user's sub, and every Admin* call accepts either the email or the sub.
"""

import json
import logging
import urllib.request
from collections.abc import Callable

from platform_common.authprovider import AuthRefused, AuthResult

log = logging.getLogger(__name__)

# Cognito error code -> our code. NotAuthorizedException depends on the call (_refusal).
_CODES = {
    "UsernameExistsException": "user_exists",
    "UserNotFoundException": "not_authorized",
    "UserNotConfirmedException": "not_authorized",
    "PasswordResetRequiredException": "not_authorized",
    "InvalidPasswordException": "password_rejected",
    "PasswordHistoryPolicyViolationException": "password_rejected",
    "CodeMismatchException": "totp_not_accepted",
    "ExpiredCodeException": "totp_not_accepted",  # a code already used once
    "EnableSoftwareTokenMFAException": "totp_not_accepted",
    "TooManyRequestsException": "rate_limited",
    "LimitExceededException": "rate_limited",
    "TooManyFailedAttemptsException": "rate_limited",
}


def _fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as r:  # the pool issuer URL, https
        return json.load(r)


class CognitoAuthProvider:
    def __init__(
        self,
        client,
        user_pool_id: str,
        client_id: str,
        issuer: str,
        *,
        fetch_json: Callable[[str], dict] = _fetch_json,
    ):
        self._c = client
        self._pool = user_pool_id
        self._client_id = client_id
        self._issuer = issuer
        self._fetch_json = fetch_json
        self._jwks: dict | None = None

    def _call(self, operation: str, *, not_authorized: str = "not_authorized", **params) -> dict:
        try:
            return getattr(self._c, operation)(**params)
        except self._c.exceptions.ClientError as e:
            raise _refusal(operation, e, not_authorized) from None

    # -- AuthProvider ---------------------------------------------------------
    def create_user(self, email: str, password: str) -> str:
        user = self._call(
            "admin_create_user",
            UserPoolId=self._pool,
            Username=email,
            # Our API verified the email with its own code (§5.1), so no Cognito mail.
            UserAttributes=[{"Name": "email", "Value": email}, {"Name": "email_verified", "Value": "true"}],
            MessageAction="SUPPRESS",
        )["User"]
        sub = _attribute(user["Attributes"], "sub")
        self.set_password(sub, password)
        return sub

    def get_sub(self, email: str) -> str | None:
        try:
            user = self._c.admin_get_user(UserPoolId=self._pool, Username=email)
        except self._c.exceptions.ClientError as e:
            if _code(e) == "UserNotFoundException":
                return None
            raise _refusal("admin_get_user", e, "not_authorized") from None
        return _attribute(user["UserAttributes"], "sub")

    def initiate_auth(self, email: str, password: str) -> AuthResult:
        r = self._call(
            "admin_initiate_auth",
            UserPoolId=self._pool,
            ClientId=self._client_id,
            AuthFlow="ADMIN_USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": email, "PASSWORD": password},
        )
        if r.get("ChallengeName") == "SOFTWARE_TOKEN_MFA":
            return AuthResult(challenge=r["Session"])
        if "AuthenticationResult" not in r:  # a challenge this pool shouldn't send (e.g. NEW_PASSWORD_REQUIRED)
            log.error("cognito: unexpected challenge %s", r.get("ChallengeName"))
            raise AuthRefused("not_authorized")
        return _tokens(r["AuthenticationResult"])

    def respond_totp(self, email: str, challenge: str, code: str) -> AuthResult:
        r = self._call(
            "admin_respond_to_auth_challenge",
            not_authorized="challenge_expired",  # an expired session, or another user's
            UserPoolId=self._pool,
            ClientId=self._client_id,
            ChallengeName="SOFTWARE_TOKEN_MFA",
            Session=challenge,
            ChallengeResponses={"USERNAME": email, "SOFTWARE_TOKEN_MFA_CODE": code},
        )
        return _tokens(r["AuthenticationResult"])

    def refresh(self, refresh_token: str) -> AuthResult:
        r = self._call(
            "admin_initiate_auth",
            UserPoolId=self._pool,
            ClientId=self._client_id,
            AuthFlow="REFRESH_TOKEN_AUTH",
            AuthParameters={"REFRESH_TOKEN": refresh_token},
        )
        return _tokens(r["AuthenticationResult"])

    def revoke_refresh(self, refresh_token: str) -> None:
        self._call("revoke_token", Token=refresh_token, ClientId=self._client_id)

    def set_password(self, sub: str, password: str) -> None:
        self._call("admin_set_user_password", UserPoolId=self._pool, Username=sub, Password=password, Permanent=True)

    def change_password(self, access_token: str, old: str, new: str) -> None:
        self._call("change_password", PreviousPassword=old, ProposedPassword=new, AccessToken=access_token)

    def global_sign_out(self, sub: str) -> None:
        self._call("admin_user_global_sign_out", UserPoolId=self._pool, Username=sub)

    def associate_totp(self, access_token: str) -> str:
        return self._call("associate_software_token", AccessToken=access_token)["SecretCode"]

    def verify_totp(self, access_token: str, code: str) -> bool:
        try:
            r = self._call("verify_software_token", AccessToken=access_token, UserCode=code)
        except AuthRefused as e:
            if e.code == "totp_not_accepted":
                return False
            raise
        if r.get("Status") != "SUCCESS":
            return False
        self._call(
            "set_user_mfa_preference",
            AccessToken=access_token,
            SoftwareTokenMfaSettings={"Enabled": True, "PreferredMfa": True},
        )
        return True

    def remove_totp(self, sub: str) -> None:
        self._call(
            "admin_set_user_mfa_preference",
            UserPoolId=self._pool,
            Username=sub,
            SoftwareTokenMfaSettings={"Enabled": False, "PreferredMfa": False},
        )
        # So a later enrolment starts from a new secret (LLD-1 §5.9, S0b C4).
        self._call("admin_delete_software_token", UserPoolId=self._pool, Username=sub)

    def jwks(self) -> dict:
        """The pool's signing keys, fetched once per cold start (§7.3)."""
        if self._jwks is None:
            self._jwks = self._fetch_json(f"{self._issuer}/.well-known/jwks.json")
        return self._jwks


def _code(e) -> str:
    return e.response.get("Error", {}).get("Code", "")


def _refusal(operation: str, e, not_authorized: str) -> Exception:
    code = _code(e)
    if code == "NotAuthorizedException":
        # The message is read, never logged: an access token Cognito no longer accepts
        # ("Access Token has expired", "... has been revoked", "Invalid Access Token")
        # is not a wrong password.
        message = e.response.get("Error", {}).get("Message", "")
        return AuthRefused("token_invalid" if "access token" in message.lower() else not_authorized)
    if code in _CODES:
        return AuthRefused(_CODES[code])
    request_id = e.response.get("ResponseMetadata", {}).get("RequestId")
    log.error("cognito: %s failed with %s (request %s)", operation, code or "an unknown error", request_id)
    return RuntimeError(f"cognito {operation} failed: {code}")


def _attribute(attributes: list[dict], name: str) -> str:
    return next(a["Value"] for a in attributes if a["Name"] == name)


def _tokens(result: dict) -> AuthResult:
    return AuthResult(
        access_token=result["AccessToken"],
        refresh_token=result.get("RefreshToken"),  # absent on refresh: rotation is off
        expires_in=result["ExpiresIn"],
    )

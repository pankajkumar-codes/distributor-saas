"""The identity provider behind sign-up and sign-in (LLD-0 §3.11, LLD-1 §7.2).

CognitoAuthProvider (identity module, LLD-1) and FakeAuthProvider (local, CI) both
implement this. Our API is the only caller: the browser never talks to the provider.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AuthResult:
    """Tokens after a successful step, or a TOTP challenge to answer.

    `challenge` is the provider's opaque session string for the TOTP step (L1-7); it is
    on the redaction list and never stored.
    """

    access_token: str | None = None
    refresh_token: str | None = None  # absent on refresh: rotation is off (L1-5)
    expires_in: int = 0
    challenge: str | None = None

    @property
    def needs_totp(self) -> bool:
        return self.challenge is not None


class AuthRefused(Exception):
    """The provider said no. `code` is ours, never the provider's message text.

    Codes: not_authorized (wrong password, unknown user, revoked or bad refresh token),
    user_exists, totp_not_accepted (`challenge` may carry a new session string),
    challenge_expired, password_rejected.
    """

    def __init__(self, code: str, *, challenge: str | None = None):
        super().__init__(code)
        self.code = code
        self.challenge = challenge


class AuthProvider(Protocol):
    def create_user(self, email: str, password: str) -> str:
        """Create a confirmed user with a permanent password; returns the `sub`.
        Raises AuthRefused("user_exists")."""

    def get_sub(self, email: str) -> str | None:
        """The `sub` of an existing user (recovery after a half-finished verify)."""

    def initiate_auth(self, email: str, password: str) -> AuthResult: ...

    def respond_totp(self, challenge: str, code: str) -> AuthResult: ...

    def refresh(self, refresh_token: str) -> AuthResult: ...

    def revoke_refresh(self, refresh_token: str) -> None: ...

    def set_password(self, sub: str, password: str) -> None: ...

    def change_password(self, access_token: str, old: str, new: str) -> None:
        """Raises AuthRefused("not_authorized") when `old` is wrong."""

    def global_sign_out(self, sub: str) -> None: ...

    def associate_totp(self, access_token: str) -> str:
        """Start TOTP enrolment; returns the shared secret (never logged or stored)."""

    def verify_totp(self, access_token: str, code: str) -> bool:
        """Finish enrolment and make TOTP the preferred second step."""

    def remove_totp(self, sub: str) -> None: ...

    def jwks(self) -> dict:
        """The public keys that sign access tokens."""

"""An in-memory AuthProvider for local runs and CI (LLD-0 §3.11).

It behaves like the Cognito app client LLD-1 §7.1 configures: email is the username,
access tokens live 5 minutes and carry `origin_jti` (the session key, L1-6), which
survives refresh; refresh tokens are opaque and not rotated; TOTP adds a challenge
step. Tokens are RS256 JWTs signed with a key made at start-up and published by
`jwks()`, so verification follows the same path as for Cognito's tokens.

Never used outside PLATFORM_ENV local or test: nothing here is persisted or secret.
"""

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from .auth import debug_env
from .authprovider import AuthRefused, AuthResult
from .clock import Clock

ISSUER = "https://fake-idp.local/pool"
CLIENT_ID = "fake-client"
ACCESS_SECONDS = 300
CHALLENGE_SECONDS = 180


@dataclass
class _User:
    sub: str
    email: str
    password: str
    totp_secret: str | None = None
    totp_enabled: bool = False


@dataclass
class _Refresh:
    sub: str
    origin_jti: str
    auth_time: int
    revoked: bool = False


class FakeAuthProvider:
    def __init__(self, clock: Clock | None = None):
        if not debug_env():
            raise RuntimeError("FakeAuthProvider is for local and test only")
        self._clock = clock or Clock()
        self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self._kid = uuid.uuid4().hex
        self._users: dict[str, _User] = {}  # by normalised email
        self._refresh: dict[str, _Refresh] = {}
        self._challenges: dict[str, tuple[str, datetime]] = {}  # challenge -> (email, expires)

    # -- helpers for tests --------------------------------------------------
    @staticmethod
    def totp_code(secret: str) -> str:
        """The code an authenticator app would show for `secret` (fixed, for tests)."""
        return f"{int(hmac.new(secret.encode(), b'totp', hashlib.sha256).hexdigest(), 16) % 10**6:06d}"

    def user(self, email: str) -> _User | None:
        return self._users.get(email.strip().lower())

    # -- AuthProvider ---------------------------------------------------------
    def create_user(self, email: str, password: str) -> str:
        email = email.strip().lower()
        if email in self._users:
            raise AuthRefused("user_exists")
        sub = str(uuid.uuid4())
        self._users[email] = _User(sub, email, password)
        return sub

    def get_sub(self, email: str) -> str | None:
        u = self.user(email)
        return u.sub if u else None

    def initiate_auth(self, email: str, password: str) -> AuthResult:
        u = self.user(email)
        if u is None or not hmac.compare_digest(u.password, password):
            raise AuthRefused("not_authorized")
        if u.totp_enabled:
            challenge = secrets.token_urlsafe(32)
            self._challenges[challenge] = (u.email, self._clock.now() + timedelta(seconds=CHALLENGE_SECONDS))
            return AuthResult(challenge=challenge)
        return self._sign_in(u)

    def respond_totp(self, challenge: str, code: str) -> AuthResult:
        # Unlimited tries on one challenge. The attempt limit is ours (rate.hit), so
        # LLD-1's limit tests must exercise rate.hit, not rely on the provider.
        email, expires = self._challenges.get(challenge, (None, None))
        if email is None or self._clock.now() >= expires:
            self._challenges.pop(challenge, None)
            raise AuthRefused("challenge_expired")
        u = self._users[email]
        if not hmac.compare_digest(self.totp_code(u.totp_secret), code):
            raise AuthRefused("totp_not_accepted", challenge=challenge)
        del self._challenges[challenge]
        return self._sign_in(u)

    def refresh(self, refresh_token: str) -> AuthResult:
        r = self._refresh.get(refresh_token)
        if r is None or r.revoked:
            raise AuthRefused("not_authorized")
        return AuthResult(access_token=self._access(r.sub, r.origin_jti, r.auth_time), expires_in=ACCESS_SECONDS)

    def revoke_refresh(self, refresh_token: str) -> None:
        if refresh_token in self._refresh:
            self._refresh[refresh_token].revoked = True

    def set_password(self, sub: str, password: str) -> None:
        self._by_sub(sub).password = password

    def change_password(self, access_token: str, old: str, new: str) -> None:
        u = self._by_sub(self._sub_of(access_token))
        if not hmac.compare_digest(u.password, old):
            raise AuthRefused("not_authorized")
        u.password = new

    def global_sign_out(self, sub: str) -> None:
        for r in self._refresh.values():
            if r.sub == sub:
                r.revoked = True

    def associate_totp(self, access_token: str) -> str:
        u = self._by_sub(self._sub_of(access_token))
        u.totp_secret = secrets.token_hex(20)
        return u.totp_secret

    def verify_totp(self, access_token: str, code: str) -> bool:
        u = self._by_sub(self._sub_of(access_token))
        if u.totp_secret is None or not hmac.compare_digest(self.totp_code(u.totp_secret), code):
            return False
        u.totp_enabled = True
        return True

    def remove_totp(self, sub: str) -> None:
        u = self._by_sub(sub)
        u.totp_secret, u.totp_enabled = None, False

    def jwks(self) -> dict:
        public = jwt.algorithms.RSAAlgorithm.to_jwk(self._key.public_key(), as_dict=True)
        return {"keys": [{**public, "kid": self._kid, "alg": "RS256", "use": "sig"}]}

    # -- internals ------------------------------------------------------------
    def _by_sub(self, sub: str) -> _User:
        u = next((u for u in self._users.values() if u.sub == sub), None)
        if u is None:
            raise AuthRefused("not_authorized")
        return u

    def _sub_of(self, access_token: str) -> str:
        try:
            # Expiry is the API's check (verify_access_token), not the provider's.
            return jwt.decode(
                access_token,
                self._key.public_key(),
                algorithms=["RS256"],
                issuer=ISSUER,
                options={"verify_exp": False},
            )["sub"]
        except jwt.PyJWTError as e:
            raise AuthRefused("not_authorized") from e

    def _sign_in(self, u: _User) -> AuthResult:
        origin_jti, auth_time = str(uuid.uuid4()), int(self._clock.now().timestamp())
        token = secrets.token_urlsafe(48)
        self._refresh[token] = _Refresh(u.sub, origin_jti, auth_time)
        return AuthResult(
            access_token=self._access(u.sub, origin_jti, auth_time), refresh_token=token, expires_in=ACCESS_SECONDS
        )

    def _access(self, sub: str, origin_jti: str, auth_time: int) -> str:
        iat = int(self._clock.now().timestamp())
        claims = {
            "sub": sub,
            "iss": ISSUER,
            "client_id": CLIENT_ID,
            "token_use": "access",
            "origin_jti": origin_jti,
            "jti": str(uuid.uuid4()),
            "auth_time": auth_time,
            "iat": iat,
            "exp": iat + ACCESS_SECONDS,
            "username": sub,
        }
        return jwt.encode(claims, self._key, algorithm="RS256", headers={"kid": self._kid})

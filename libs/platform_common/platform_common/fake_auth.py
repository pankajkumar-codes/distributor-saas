"""An in-memory AuthProvider for local runs and CI (LLD-0 §3.11).

It behaves like the Cognito app client LLD-1 §7.1 configures: email is the username,
access tokens live 5 minutes and carry `origin_jti` (the session key, L1-6), which
survives refresh; refresh tokens are opaque and not rotated; TOTP adds a challenge
step. Tokens are RS256 JWTs signed with a key made at start-up and published by
`jwks()`, so verification follows the same path as for Cognito's tokens.

Never used outside PLATFORM_ENV local or test: nothing here is secret. With `state_path` (the
local demo sets DEMO_AUTH_STATE_FILE) the users, refresh tokens and signing key are also kept in
that file, so restarting the API process does not sign everyone out or forget their accounts.
Otherwise nothing is persisted.
"""

import base64
import functools
import json
import logging
import os
import tempfile
import threading

import hashlib
import hmac
import secrets
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from datetime import datetime, timedelta

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from .auth import debug_env
from .authprovider import AuthRefused, AuthResult
from .clock import Clock

log = logging.getLogger(__name__)

ISSUER = "https://fake-idp.local/pool"
CLIENT_ID = "fake-client"
ACCESS_SECONDS = 300
CHALLENGE_SECONDS = 180


def _same(a: str, b: str) -> bool:
    """Constant-time equality for text. compare_digest on two str raises TypeError for a non-ASCII one, which a
    caller-supplied code or password can be, so compare the UTF-8 bytes (a lone surrogate, which JSON can carry, included)."""
    return hmac.compare_digest(a.encode("utf-8", "surrogatepass"), b.encode("utf-8", "surrogatepass"))


def _locked(method):
    """Run a method holding the provider's lock: a change and the save of it are one step, even with
    several requests in flight on the API's thread pool."""

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


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
    def __init__(self, clock: Clock | None = None, state_path: str | os.PathLike | None = None):
        if not debug_env():
            raise RuntimeError("FakeAuthProvider is for local and test only")
        self._clock = clock or Clock()
        self._state_path = Path(state_path) if state_path else None
        self._lock = threading.RLock()  # the API serves requests on a thread pool; changes and saves go one at a time
        self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self._kid = uuid.uuid4().hex
        self._users: dict[str, _User] = {}  # by normalised email
        self._refresh: dict[str, _Refresh] = {}
        self._challenges: dict[str, tuple[str, datetime]] = {}  # challenge -> (email, expires)
        if self._state_path is not None and self._state_path.exists():
            try:
                self._load()
            except Exception:
                # A half-written or unreadable file must not stop the API from starting (a restart policy would
                # loop it): keep the file for a look, and start empty.
                aside = self._state_path.with_name(self._state_path.name + ".bad")
                log.exception("auth state file %s is unreadable; moved to %s and starting empty", self._state_path, aside)
                os.replace(self._state_path, aside)
                self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
                self._kid = uuid.uuid4().hex
                self._users, self._refresh, self._challenges = {}, {}, {}
                self._save()
        else:
            self._save()

    # -- optional state file (the local demo) ---------------------------------
    def _save(self) -> None:
        if self._state_path is None:
            return
        pem = self._key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
        state = {
            "key": base64.b64encode(pem).decode(),
            "kid": self._kid,
            "users": {k: asdict(u) for k, u in self._users.items()},
            "refresh": {k: asdict(r) for k, r in self._refresh.items()},
            "challenges": {k: [e, x.isoformat()] for k, (e, x) in self._challenges.items()},
        }
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        # A temp file of its own (mkstemp makes it 0600: the signing key and the demo passwords are in it),
        # then one rename, so a reader never sees half a file.
        fd, tmp = tempfile.mkstemp(dir=self._state_path.parent, prefix=self._state_path.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(json.dumps(state))
            os.replace(tmp, self._state_path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def _load(self) -> None:
        state = json.loads(self._state_path.read_text())
        key = serialization.load_pem_private_key(base64.b64decode(state["key"]), password=None)
        assert isinstance(key, rsa.RSAPrivateKey)
        self._key, self._kid = key, state["kid"]
        self._users = {k: _User(**u) for k, u in state["users"].items()}
        self._refresh = {k: _Refresh(**r) for k, r in state["refresh"].items()}
        self._challenges = {k: (e, datetime.fromisoformat(x)) for k, (e, x) in state["challenges"].items()}

    # -- helpers for tests --------------------------------------------------
    @staticmethod
    def totp_code(secret: str) -> str:
        """The code an authenticator app would show for `secret` (fixed, for tests)."""
        return f"{int(hmac.new(secret.encode(), b'totp', hashlib.sha256).hexdigest(), 16) % 10**6:06d}"

    def user(self, email: str) -> _User | None:
        return self._users.get(email.strip().lower())

    def demo_two_step(self, *, access_token: str | None = None, email: str | None = None) -> tuple[str, str] | None:
        """(email, code) the local demo prints for a person who has started two-step sign-in, found by access token
        or by email. None when there is no secret yet."""
        try:
            u = self._by_sub(self._sub_of(access_token)) if access_token else self.user(email or "")
        except Exception:  # a bad token is the caller's problem, not the demo's
            return None
        if u is None or u.totp_secret is None:
            return None
        return u.email, self.totp_code(u.totp_secret)

    # -- AuthProvider ---------------------------------------------------------
    @_locked
    def create_user(self, email: str, password: str) -> str:
        email = email.strip().lower()
        if email in self._users:
            raise AuthRefused("user_exists")
        sub = str(uuid.uuid4())
        self._users[email] = _User(sub, email, password)
        self._save()
        return sub

    def get_sub(self, email: str) -> str | None:
        u = self.user(email)
        return u.sub if u else None

    @_locked
    def initiate_auth(self, email: str, password: str) -> AuthResult:
        u = self.user(email)
        if u is None or not _same(u.password, password):
            raise AuthRefused("not_authorized")
        if u.totp_enabled:
            challenge = secrets.token_urlsafe(32)
            self._challenges[challenge] = (u.email, self._clock.now() + timedelta(seconds=CHALLENGE_SECONDS))
            self._save()
            return AuthResult(challenge=challenge)
        return self._sign_in(u)

    @_locked
    def respond_totp(self, email: str, challenge: str, code: str) -> AuthResult:
        # Unlimited tries on one challenge. The attempt limit is ours (rate.hit), so
        # LLD-1's limit tests must exercise rate.hit, not rely on the provider.
        owner, expires = self._challenges.get(challenge, (None, None))
        if owner is None or owner != email.strip().lower():
            raise AuthRefused("challenge_expired")  # like Cognito: not this user's session
        if self._clock.now() >= expires:
            self._challenges.pop(challenge, None)
            self._save()
            raise AuthRefused("challenge_expired")
        u = self._users[owner]
        if not _same(self.totp_code(u.totp_secret), code):
            raise AuthRefused("totp_not_accepted", challenge=challenge)
        del self._challenges[challenge]
        self._save()
        return self._sign_in(u)

    @_locked
    def refresh(self, refresh_token: str) -> AuthResult:
        r = self._refresh.get(refresh_token)
        if r is None or r.revoked:
            raise AuthRefused("not_authorized")
        return AuthResult(access_token=self._access(r.sub, r.origin_jti, r.auth_time), expires_in=ACCESS_SECONDS)

    @_locked
    def revoke_refresh(self, refresh_token: str) -> None:
        if refresh_token in self._refresh:
            self._refresh[refresh_token].revoked = True
            self._save()

    @_locked
    def set_password(self, sub: str, password: str) -> None:
        self._by_sub(sub).password = password
        self._save()

    @_locked
    def change_password(self, access_token: str, old: str, new: str) -> None:
        u = self._by_sub(self._sub_of(access_token))
        if not _same(u.password, old):
            raise AuthRefused("not_authorized")
        u.password = new
        self._save()

    @_locked
    def global_sign_out(self, sub: str) -> None:
        for r in self._refresh.values():
            if r.sub == sub:
                r.revoked = True
        self._save()

    @_locked
    def associate_totp(self, access_token: str) -> str:
        u = self._by_sub(self._sub_of(access_token))
        u.totp_secret = secrets.token_hex(20)
        self._save()
        return u.totp_secret

    @_locked
    def verify_totp(self, access_token: str, code: str) -> bool:
        u = self._by_sub(self._sub_of(access_token))
        if u.totp_secret is None or not _same(self.totp_code(u.totp_secret), code):
            return False
        u.totp_enabled = True
        self._save()
        return True

    @_locked
    def remove_totp(self, sub: str) -> None:
        u = self._by_sub(sub)
        u.totp_secret, u.totp_enabled = None, False
        self._save()

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
            raise AuthRefused("token_invalid") from e

    @_locked
    def _sign_in(self, u: _User) -> AuthResult:
        origin_jti, auth_time = str(uuid.uuid4()), int(self._clock.now().timestamp())
        token = secrets.token_urlsafe(48)
        self._refresh[token] = _Refresh(u.sub, origin_jti, auth_time)
        self._save()
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

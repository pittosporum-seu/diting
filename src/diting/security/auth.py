"""Single-owner token verification and persistent signed sessions."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta

from ..infra.errors import AuthenticationError, AuthNotConfiguredError, AuthorizationError
from ..ports import Clock, DurableStore
from ..schema import OwnerSession

_HASH_NAME = "pbkdf2_sha256"
_DEFAULT_ITERATIONS = 600_000


@dataclass(frozen=True)
class IssuedSession:
    cookie_value: str
    csrf_token: str
    session: OwnerSession


def hash_owner_token(
    token: str,
    *,
    salt: bytes | None = None,
    iterations: int = _DEFAULT_ITERATIONS,
) -> str:
    """Create the environment-safe encoded owner-token hash used by v0.8."""

    if len(token) < 16:
        raise ValueError("owner token must contain at least 16 characters")
    if iterations < 200_000:
        raise ValueError("PBKDF2 iterations must be at least 200000")
    actual_salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", token.encode(), actual_salt, iterations)
    return "$".join(
        (
            _HASH_NAME,
            str(iterations),
            _encode(actual_salt),
            _encode(digest),
        )
    )


class AuthService:
    """Verify the owner token and manage revocable server-side sessions."""

    def __init__(
        self,
        store: DurableStore,
        clock: Clock,
        *,
        owner_token_hash: str,
        session_secret: str,
        session_hours: int = 12,
    ) -> None:
        self._store = store
        self._clock = clock
        self._owner_token_hash = owner_token_hash
        self._session_secret = session_secret.encode()
        self._session_hours = session_hours

    @property
    def configured(self) -> bool:
        return bool(self._owner_token_hash and self._session_secret)

    def issue(self, token: str) -> IssuedSession:
        self._require_configured()
        if not self.verify_owner_token(token):
            raise AuthenticationError("owner token 无效")
        now = self._clock.now()
        csrf_token = secrets.token_urlsafe(32)
        session = OwnerSession(
            session_id=secrets.token_urlsafe(32),
            csrf_hash=_csrf_hash(csrf_token),
            created_at=now,
            expires_at=now + timedelta(hours=self._session_hours),
        )
        self._store.create_owner_session(session)
        expires = int(session.expires_at.timestamp())
        payload = f"v1.{session.session_id}.{expires}"
        cookie = f"{payload}.{self._signature(payload)}"
        return IssuedSession(cookie, csrf_token, session)

    def verify_owner_token(self, token: str) -> bool:
        self._require_configured()
        try:
            algorithm, iteration_text, salt_text, digest_text = self._owner_token_hash.split("$")
            if algorithm != _HASH_NAME:
                return False
            iterations = int(iteration_text)
            if iterations < 200_000:
                return False
            salt = _decode(salt_text)
            expected = _decode(digest_text)
        except (TypeError, ValueError):
            return False
        actual = hashlib.pbkdf2_hmac("sha256", token.encode(), salt, iterations)
        return hmac.compare_digest(actual, expected)

    def authenticate(self, cookie_value: str | None) -> OwnerSession:
        self._require_configured()
        if not cookie_value:
            raise AuthenticationError()
        try:
            version, session_id, expires_text, signature = cookie_value.split(".")
            expires = int(expires_text)
        except (TypeError, ValueError):
            raise AuthenticationError("owner session 无效") from None
        payload = f"{version}.{session_id}.{expires}"
        if version != "v1" or not hmac.compare_digest(signature, self._signature(payload)):
            raise AuthenticationError("owner session 无效")
        now = self._clock.now()
        if expires <= int(now.timestamp()):
            raise AuthenticationError("owner session 已过期")
        session = self._store.get_owner_session(session_id)
        if session is None or session.revoked_at is not None:
            raise AuthenticationError("owner session 无效")
        if int(session.expires_at.timestamp()) != expires or session.expires_at <= now:
            raise AuthenticationError("owner session 已过期")
        return session

    def validate_csrf(self, session: OwnerSession, csrf_token: str | None) -> None:
        if not csrf_token or not hmac.compare_digest(session.csrf_hash, _csrf_hash(csrf_token)):
            raise AuthorizationError("CSRF 校验失败", error_code="CSRF_INVALID")

    def revoke(self, session: OwnerSession) -> None:
        self._store.revoke_owner_session(session.session_id, self._clock.now())

    def _signature(self, payload: str) -> str:
        return _encode(hmac.new(self._session_secret, payload.encode(), hashlib.sha256).digest())

    def _require_configured(self) -> None:
        if not self.configured:
            raise AuthNotConfiguredError()


def _csrf_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

"""Owner token, session cookie, Origin and CSRF security tests."""

from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pydantic import SecretStr

from src.diting.config import AppConfig, RuntimeConfig, SecurityConfig
from src.diting.infra.errors import AnalysisError, AuthenticationError
from src.diting.persistence.migrations import migrate_databases
from src.diting.persistence.store_v080 import SQLiteDurableStore
from src.diting.schema import OwnerSession
from src.diting.security.auth import AuthService, hash_owner_token
from src.diting.web.security import CSRF_HEADER, SESSION_COOKIE, OwnerSecurity, build_auth_router

NOW = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)
OWNER_TOKEN = "correct-owner-token-0123456789"


class FakeClock:
    def __init__(self) -> None:
        self.current = NOW

    def now(self) -> datetime:
        return self.current

    def today(self) -> date:
        return self.current.date()

    def monotonic(self) -> float:
        return time.monotonic()


def _build(tmp_path: Path, *, production: bool = False):
    business = tmp_path / "diting.db"
    migrate_databases(business, tmp_path / "cache.db")
    store = SQLiteDurableStore(business)
    clock = FakeClock()
    settings = AppConfig(
        runtime=RuntimeConfig(environment="production" if production else "test"),
        security=SecurityConfig(
            owner_token_hash=SecretStr(
                hash_owner_token(OWNER_TOKEN, salt=b"0123456789abcdef", iterations=200_000)
            ),
            session_secret=SecretStr("session-secret-with-at-least-32-bytes"),
            allowed_origins=("http://testserver",),
            session_hours=12,
        ),
    )
    auth = AuthService(
        store,
        clock,
        owner_token_hash=settings.security.owner_token_hash.get_secret_value(),
        session_secret=settings.security.session_secret.get_secret_value(),
        session_hours=12,
    )
    security = OwnerSecurity(auth, settings)
    app = FastAPI()

    @app.exception_handler(AnalysisError)
    async def handle(_request: Request, exc: AnalysisError):
        return JSONResponse(
            {"error_code": exc.error_code, "message": str(exc)},
            status_code=exc.http_status_code,
        )

    app.include_router(build_auth_router(auth, settings))

    @app.post("/api/v1/protected")
    async def protected(_session: OwnerSession = Depends(security.require_owner_write)):
        return {"ok": True}

    return TestClient(app), auth, store, clock


def _login(client: TestClient):
    return client.post(
        "/api/v1/auth/session",
        headers={"Origin": "http://testserver"},
        json={"token": OWNER_TOKEN},
    )


def test_owner_hash_is_salted_strong_and_verifiable(tmp_path: Path) -> None:
    encoded = hash_owner_token(OWNER_TOKEN, salt=b"0123456789abcdef", iterations=200_000)
    client, auth, _, _ = _build(tmp_path)

    assert encoded.startswith("pbkdf2_sha256$200000$")
    assert OWNER_TOKEN not in encoded
    assert auth.verify_owner_token(OWNER_TOKEN) is True
    assert auth.verify_owner_token("incorrect-token-value") is False
    with pytest.raises(ValueError, match="at least 16"):
        hash_owner_token("too-short")
    client.close()


def test_login_sets_strict_http_only_cookie_without_echoing_secrets(tmp_path: Path) -> None:
    client, _, _, _ = _build(tmp_path)
    try:
        response = _login(client)
        cookie = response.headers["set-cookie"]

        assert response.status_code == 200
        assert response.json()["data"]["authenticated"] is True
        assert response.json()["data"]["csrf_token"]
        assert OWNER_TOKEN not in response.text
        assert "session-secret" not in response.text
        assert "HttpOnly" in cookie
        assert "SameSite=strict" in cookie
        assert "Secure" not in cookie
        assert SESSION_COOKIE in client.cookies
    finally:
        client.close()


def test_production_cookie_is_secure(tmp_path: Path) -> None:
    client, _, _, _ = _build(tmp_path, production=True)
    try:
        response = _login(client)
        assert "Secure" in response.headers["set-cookie"]
    finally:
        client.close()


def test_write_requires_owner_origin_and_csrf(tmp_path: Path) -> None:
    client, _, _, _ = _build(tmp_path)
    try:
        assert client.post("/api/v1/protected").status_code == 401
        login = _login(client)
        csrf = login.json()["data"]["csrf_token"]

        missing_origin = client.post("/api/v1/protected", headers={CSRF_HEADER: csrf})
        foreign_origin = client.post(
            "/api/v1/protected",
            headers={"Origin": "https://evil.example", CSRF_HEADER: csrf},
        )
        missing_csrf = client.post("/api/v1/protected", headers={"Origin": "http://testserver"})
        accepted = client.post(
            "/api/v1/protected",
            headers={"Origin": "http://testserver", CSRF_HEADER: csrf},
        )

        assert missing_origin.json()["error_code"] == "ORIGIN_REQUIRED"
        assert foreign_origin.json()["error_code"] == "ORIGIN_FORBIDDEN"
        assert missing_csrf.json()["error_code"] == "CSRF_INVALID"
        assert accepted.status_code == 200
    finally:
        client.close()


def test_logout_revokes_server_session_and_clears_cookie(tmp_path: Path) -> None:
    client, auth, _, _ = _build(tmp_path)
    try:
        login = _login(client)
        csrf = login.json()["data"]["csrf_token"]
        cookie_value = client.cookies[SESSION_COOKIE]
        response = client.delete(
            "/api/v1/auth/session",
            headers={"Origin": "http://testserver", CSRF_HEADER: csrf},
        )

        assert response.status_code == 200
        assert SESSION_COOKIE not in client.cookies
        with pytest.raises(AuthenticationError):
            auth.authenticate(cookie_value)
    finally:
        client.close()


def test_expired_session_is_rejected(tmp_path: Path) -> None:
    client, auth, _, clock = _build(tmp_path)
    try:
        _login(client)
        cookie_value = client.cookies[SESSION_COOKIE]
        clock.current = NOW + timedelta(hours=13)

        with pytest.raises(AuthenticationError, match="过期"):
            auth.authenticate(cookie_value)
    finally:
        client.close()


def test_login_rejects_wrong_token_and_missing_origin(tmp_path: Path) -> None:
    client, _, _, _ = _build(tmp_path)
    try:
        wrong = client.post(
            "/api/v1/auth/session",
            headers={"Origin": "http://testserver"},
            json={"token": "wrong-owner-token-0123456789"},
        )
        no_origin = client.post(
            "/api/v1/auth/session",
            json={"token": OWNER_TOKEN},
        )

        assert wrong.status_code == 401
        assert wrong.json()["error_code"] == "AUTH_REQUIRED"
        assert no_origin.status_code == 403
        assert no_origin.json()["error_code"] == "ORIGIN_REQUIRED"
    finally:
        client.close()

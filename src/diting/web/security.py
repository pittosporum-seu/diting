"""FastAPI owner-session routes and reusable write-request guards."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ..config import AppConfig
from ..infra.errors import AuthenticationError, AuthorizationError
from ..schema import OwnerSession
from ..security.auth import AuthService
from .contracts_v1 import ApiEnvelope, AuthSessionData, success_envelope
from .rate_limit import SlidingWindowRateLimiter

SESSION_COOKIE = "diting_owner_session"
CSRF_HEADER = "X-CSRF-Token"


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    token: str = Field(min_length=1, max_length=4096)


@dataclass(frozen=True)
class OwnerSecurity:
    auth: AuthService
    settings: AppConfig

    def require_owner(self, request: Request) -> OwnerSession:
        return self.auth.authenticate(request.cookies.get(SESSION_COOKIE))

    def require_owner_write(self, request: Request) -> OwnerSession:
        session = self.require_owner(request)
        validate_origin(request, self.settings.security.allowed_origins)
        self.auth.validate_csrf(session, request.headers.get(CSRF_HEADER))
        return session

    def require_read_access(self, request: Request) -> OwnerSession | None:
        if self.settings.runtime.public_readonly:
            return None
        return self.require_owner(request)


def build_auth_router(
    auth: AuthService,
    settings: AppConfig,
    limiter: SlidingWindowRateLimiter | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
    security = OwnerSecurity(auth, settings)

    @router.post("/session", response_model=ApiEnvelope[AuthSessionData])
    async def login(request: Request, credentials: LoginRequest) -> JSONResponse:
        if limiter is not None:
            limiter.check_login(request)
        validate_origin(request, settings.security.allowed_origins)
        issued = auth.issue(credentials.token)
        envelope = success_envelope(
            request,
            AuthSessionData(
                authenticated=True,
                csrf_token=issued.csrf_token,
                expires_at=issued.session.expires_at,
            ),
        )
        response = JSONResponse(envelope.model_dump(mode="json"))
        response.set_cookie(
            SESSION_COOKIE,
            issued.cookie_value,
            max_age=settings.security.session_hours * 60 * 60,
            httponly=True,
            secure=settings.runtime.environment == "production",
            samesite="strict",
            path="/",
        )
        return response

    @router.get("/session", response_model=ApiEnvelope[AuthSessionData])
    async def session_status(request: Request):
        try:
            session = security.require_owner(request)
        except AuthenticationError:
            return success_envelope(
                request,
                AuthSessionData(authenticated=False, configured=auth.configured),
            )
        return success_envelope(
            request,
            AuthSessionData(
                authenticated=True,
                configured=True,
                expires_at=session.expires_at,
            ),
        )

    @router.delete("/session", response_model=ApiEnvelope[AuthSessionData])
    async def logout(request: Request) -> JSONResponse:
        session = security.require_owner_write(request)
        auth.revoke(session)
        envelope = success_envelope(request, AuthSessionData(authenticated=False))
        response = JSONResponse(envelope.model_dump(mode="json"))
        response.delete_cookie(
            SESSION_COOKIE,
            path="/",
            secure=settings.runtime.environment == "production",
            httponly=True,
            samesite="strict",
        )
        return response

    return router


def validate_origin(request: Request, allowed_origins: tuple[str, ...]) -> None:
    origin = request.headers.get("Origin")
    if not origin:
        raise AuthorizationError("Origin 头缺失", error_code="ORIGIN_REQUIRED")
    allowed = set(allowed_origins)
    if not allowed:
        allowed.add(f"{request.url.scheme}://{request.url.netloc}")
    if origin.rstrip("/") not in {item.rstrip("/") for item in allowed}:
        raise AuthorizationError("Origin 不受信任", error_code="ORIGIN_FORBIDDEN")

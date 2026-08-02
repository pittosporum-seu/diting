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


def build_auth_router(auth: AuthService, settings: AppConfig) -> APIRouter:
    router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
    security = OwnerSecurity(auth, settings)

    @router.post("/session")
    async def login(request: Request, credentials: LoginRequest) -> JSONResponse:
        validate_origin(request, settings.security.allowed_origins)
        issued = auth.issue(credentials.token)
        response = JSONResponse(
            {
                "authenticated": True,
                "csrf_token": issued.csrf_token,
                "expires_at": issued.session.expires_at.isoformat(),
            }
        )
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

    @router.get("/session")
    async def session_status(request: Request) -> dict[str, object]:
        try:
            session = security.require_owner(request)
        except AuthenticationError:
            return {"authenticated": False, "configured": auth.configured}
        return {
            "authenticated": True,
            "configured": True,
            "expires_at": session.expires_at.isoformat(),
        }

    @router.delete("/session")
    async def logout(request: Request) -> JSONResponse:
        session = security.require_owner_write(request)
        auth.revoke(session)
        response = JSONResponse({"authenticated": False})
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

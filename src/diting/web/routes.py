"""Route assembly for the v0.8 API and dependency-free SPA."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

from ..bootstrap import ApplicationContainer
from .contracts_v1 import error_envelope
from .rate_limit import SlidingWindowRateLimiter
from .security import build_auth_router
from .v1 import build_v1_router
from .v1_owner import build_owner_v1_router

_ALL_METHODS = ("DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT")
_ASSET_PREFIXES = ("css/", "data/", "js/")


def build_router(
    container: ApplicationContainer,
    *,
    frontend_dir: Path,
    rate_limiter: SlidingWindowRateLimiter | None = None,
) -> APIRouter:
    """Build the only production route graph without legacy service construction."""

    if container.auth is None:
        raise RuntimeError("owner authentication is required by the HTTP application")

    router = APIRouter()
    limiter = rate_limiter or SlidingWindowRateLimiter()
    router.include_router(build_auth_router(container.auth, container.settings, limiter))
    router.include_router(build_v1_router(container, limiter))
    router.include_router(build_owner_v1_router(container, limiter))

    @router.api_route("/api/v1", methods=_ALL_METHODS, include_in_schema=False)
    @router.api_route("/api/v1/{path:path}", methods=_ALL_METHODS, include_in_schema=False)
    async def missing_v1_route(request: Request, path: str = "") -> JSONResponse:
        return _api_error(request, 404, "NOT_FOUND", "v1 API endpoint not found")

    @router.api_route("/api", methods=_ALL_METHODS, include_in_schema=False)
    @router.api_route("/api/{path:path}", methods=_ALL_METHODS, include_in_schema=False)
    async def removed_legacy_api(request: Request, path: str = "") -> JSONResponse:
        return _api_error(
            request,
            410,
            "API_VERSION_REMOVED",
            "The unversioned API was removed in Diting 0.8; use /api/v1.",
        )

    @router.get("/{path:path}", include_in_schema=False)
    async def spa(path: str = ""):
        return _spa_response(frontend_dir, path)

    return router


def _api_error(
    request: Request,
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    envelope = error_envelope(request, code=code, message=message)
    return JSONResponse(status_code=status_code, content=envelope.model_dump(mode="json"))


def _spa_response(frontend_dir: Path, path: str) -> FileResponse:
    root = frontend_dir.resolve()
    requested = (root / path).resolve()
    if requested.is_relative_to(root) and requested.is_file():
        return FileResponse(requested)
    if path.startswith(_ASSET_PREFIXES) or Path(path).suffix:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Frontend asset not found")
    return FileResponse(root / "index.html")

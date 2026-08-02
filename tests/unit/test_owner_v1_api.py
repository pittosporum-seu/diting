"""Owner v1 analysis, task, preference, watchlist and admin API tests."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from src.diting.bootstrap import ApplicationDependencies, create_container
from src.diting.config import AppConfig, RuntimeConfig, SecurityConfig
from src.diting.enums import JobType, RunStatus
from src.diting.infra.errors import AnalysisError
from src.diting.persistence.migrations import migrate_databases
from src.diting.persistence.store_v080 import SQLiteDurableStore
from src.diting.schema import JobRecord
from src.diting.security.auth import AuthService, hash_owner_token
from src.diting.web.contracts_v1 import error_envelope
from src.diting.web.rate_limit import SlidingWindowRateLimiter
from src.diting.web.security import CSRF_HEADER, build_auth_router
from src.diting.web.v1_owner import build_owner_v1_router

NOW = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)
OWNER_TOKEN = "owner-token-0123456789"


class FakeClock:
    def now(self) -> datetime:
        return NOW

    def today(self) -> date:
        return NOW.date()

    def monotonic(self) -> float:
        return 1.0


class FakeJobs:
    def __init__(self) -> None:
        self.jobs: dict[str, JobRecord] = {}
        self.requests = []

    def submit_analysis(self, _orchestrator, request):
        self.requests.append(request)
        job = JobRecord(
            job_id=f"job_{len(self.jobs) + 1}",
            job_type=JobType.ANALYSIS,
            status=RunStatus.QUEUED,
            progress=0,
            request_json="{}",
            created_at=NOW,
            deadline_at=request.deadline,
        )
        self.jobs[job.job_id] = job
        return job

    def get(self, job_id):
        return self.jobs.get(job_id)

    def cancel(self, job_id):
        job = self.jobs.get(job_id)
        if job is None:
            return None
        cancelled = replace(job, cancel_requested=True)
        self.jobs[job_id] = cancelled
        return cancelled


class FakeCache:
    def __init__(self) -> None:
        self.prefixes: list[str | None] = []

    def clear(self, prefix=None):
        self.prefixes.append(prefix)
        return 7


def _build(tmp_path: Path):
    business = tmp_path / "diting.db"
    migrate_databases(business, tmp_path / "cache.db")
    store = SQLiteDurableStore(business)
    clock = FakeClock()
    settings = AppConfig(
        runtime=RuntimeConfig(environment="test", public_readonly=True),
        security=SecurityConfig(allowed_origins=("http://testserver",)),
    )
    auth = AuthService(
        store,
        clock,
        owner_token_hash=hash_owner_token(
            OWNER_TOKEN,
            salt=b"0123456789abcdef",
            iterations=200_000,
        ),
        session_secret="session-secret-with-at-least-32-bytes",
    )
    jobs = FakeJobs()
    cache = FakeCache()
    container = create_container(
        settings,
        ApplicationDependencies(
            clock=clock,
            cache_store=cache,
            durable_store=store,
            analysis=object(),
            jobs=jobs,
            auth=auth,
        ),
    )
    limiter = SlidingWindowRateLimiter(clock.monotonic)
    app = FastAPI()

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request.state.request_id = f"req_{uuid4().hex}"
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(AnalysisError)
    async def analysis_error(request: Request, exc: AnalysisError):
        envelope = error_envelope(
            request,
            code=exc.error_code,
            message=str(exc),
            retryable=exc.http_status_code >= 500,
        )
        return JSONResponse(envelope.model_dump(mode="json"), status_code=exc.http_status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, _exc: RequestValidationError):
        envelope = error_envelope(
            request,
            code="VALIDATION_ERROR",
            message="请求参数校验失败",
        )
        return JSONResponse(envelope.model_dump(mode="json"), status_code=422)

    app.include_router(build_auth_router(auth, settings, limiter))
    app.include_router(build_owner_v1_router(container, limiter))
    return TestClient(app), store, jobs, cache, business


def _login(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/session",
        headers={"Origin": "http://testserver"},
        json={"token": OWNER_TOKEN},
    )
    assert response.status_code == 200
    return response.json()["data"]["csrf_token"]


def _write_headers(csrf: str) -> dict[str, str]:
    return {"Origin": "http://testserver", CSRF_HEADER: csrf}


def test_all_owner_operations_reject_anonymous_requests(tmp_path: Path) -> None:
    client, _, _, _, _ = _build(tmp_path)
    try:
        requests = (
            client.post("/api/v1/analyses", json={"symbol": "002475"}),
            client.get("/api/v1/jobs/job_missing"),
            client.get("/api/v1/watchlist"),
            client.get("/api/v1/preferences"),
            client.post("/api/v1/scans"),
            client.post("/api/v1/admin/cache/clear", json={}),
            client.get("/api/v1/admin/strategy"),
            client.get("/api/v1/admin/diagnostics"),
        )

        assert all(response.status_code == 401 for response in requests)
        assert all(response.json()["error"]["code"] == "AUTH_REQUIRED" for response in requests)
    finally:
        client.close()


def test_analysis_job_flow_requires_csrf_and_returns_accepted_job(tmp_path: Path) -> None:
    client, _, jobs, _, _ = _build(tmp_path)
    try:
        csrf = _login(client)
        missing_csrf = client.post(
            "/api/v1/analyses",
            headers={"Origin": "http://testserver"},
            json={"symbol": "002475"},
        )
        created = client.post(
            "/api/v1/analyses",
            headers=_write_headers(csrf),
            json={"symbol": "002475", "profile": "deep", "force_refresh": True},
        )
        job_id = created.json()["data"]["job_id"]
        fetched = client.get(f"/api/v1/jobs/{job_id}")
        cancelled = client.delete(f"/api/v1/jobs/{job_id}", headers=_write_headers(csrf))

        assert missing_csrf.status_code == 403
        assert missing_csrf.json()["error"]["code"] == "CSRF_INVALID"
        assert created.status_code == 202
        assert created.json()["meta"]["result_status"] == "queued"
        assert jobs.requests[0].profile.value == "deep"
        assert jobs.requests[0].force_refresh is True
        assert jobs.requests[0].request_id == created.headers["X-Request-ID"]
        assert fetched.status_code == 200
        assert cancelled.json()["data"]["cancel_requested"] is True
    finally:
        client.close()


def test_watchlist_preferences_admin_and_audit_are_persistent(tmp_path: Path) -> None:
    client, store, _, cache, business = _build(tmp_path)
    try:
        csrf = _login(client)
        headers = _write_headers(csrf)
        added = client.post(
            "/api/v1/watchlist",
            headers=headers,
            json={
                "symbol": "002475",
                "name": "立讯精密",
                "market": "SZ",
                "tags": ["核心"],
            },
        )
        listed = client.get("/api/v1/watchlist")
        persisted_symbol = store.list_watchlist("owner")[0].symbol
        preference = client.put(
            "/api/v1/preferences",
            headers=headers,
            json={"key": "page_size", "value": 30},
        )
        invalid_preference = client.put(
            "/api/v1/preferences",
            headers=headers,
            json={"key": "theme", "value": "neon"},
        )
        preferences = client.get("/api/v1/preferences")
        cleared = client.post(
            "/api/v1/admin/cache/clear",
            headers=headers,
            json={"prefix": "quote:"},
        )
        strategy = client.get("/api/v1/admin/strategy")
        diagnostics = client.get("/api/v1/admin/diagnostics")
        scan = client.post("/api/v1/scans", headers=headers)
        deleted = client.delete("/api/v1/watchlist/002475", headers=headers)

        assert added.status_code == 200
        assert listed.json()["data"]["items"][0]["tags"] == ["核心"]
        assert persisted_symbol == "002475"
        assert preference.json()["data"]["value"] == 30
        assert invalid_preference.status_code == 400
        assert invalid_preference.json()["error"]["code"] == "INVALID_PREFERENCE"
        assert preferences.json()["data"]["items"][0]["key"] == "page_size"
        assert cleared.json()["data"] == {"cleared": 7, "prefix": "quote:"}
        assert cache.prefixes == ["quote:"]
        assert strategy.json()["data"]["active"] is False
        assert diagnostics.json()["data"]["owner_auth_configured"] is True
        assert "session_secret" not in diagnostics.text
        assert scan.status_code == 409
        assert scan.json()["error"]["code"] == "NO_ACTIVE_STRATEGY"
        assert deleted.json()["data"]["total"] == 0

        with sqlite3.connect(business) as connection:
            audits = connection.execute(
                "SELECT actor, action, request_id FROM audit_log ORDER BY audit_id"
            ).fetchall()
        assert {row[1] for row in audits} >= {
            "watchlist.upsert",
            "preference.update",
            "cache.clear",
            "watchlist.delete",
        }
        assert all(row[0].startswith("owner:") and OWNER_TOKEN not in row[0] for row in audits)
        assert all(row[2].startswith("req_") for row in audits)
    finally:
        client.close()


def test_analysis_and_scan_business_limits_return_stable_codes(tmp_path: Path) -> None:
    client, _, _, _, _ = _build(tmp_path)
    try:
        csrf = _login(client)
        headers = _write_headers(csrf)
        for index in range(10):
            response = client.post(
                "/api/v1/analyses",
                headers=headers,
                json={"symbol": f"{index:06d}"},
            )
            assert response.status_code == 202
        analysis_limited = client.post(
            "/api/v1/analyses",
            headers=headers,
            json={"symbol": "999999"},
        )
        first_scan = client.post("/api/v1/scans", headers=headers)
        second_scan = client.post("/api/v1/scans", headers=headers)
        scan_limited = client.post("/api/v1/scans", headers=headers)

        assert analysis_limited.status_code == 429
        assert analysis_limited.json()["error"]["code"] == "ANALYSIS_RATE_LIMITED"
        assert first_scan.status_code == second_scan.status_code == 409
        assert scan_limited.status_code == 429
        assert scan_limited.json()["error"]["code"] == "SCAN_RATE_LIMITED"
    finally:
        client.close()


def test_legacy_plain_text_tags_are_read_without_migration_failure(tmp_path: Path) -> None:
    client, store, _, _, business = _build(tmp_path)
    try:
        with sqlite3.connect(business) as connection:
            connection.execute(
                "INSERT INTO watchlist(code, name, market, tags, user_id) VALUES(?,?,?,?,?)",
                ("600519", "贵州茅台", "SH", "白酒,核心", "owner"),
            )
        assert store.list_watchlist("owner")[0].tags == ("白酒", "核心")
    finally:
        client.close()

"""Public read-only v1 envelope and authorization contract tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from src.diting.bootstrap import ApplicationDependencies, create_container
from src.diting.config import AppConfig, RuntimeConfig, SecurityConfig
from src.diting.enums import (
    AnalysisProfile,
    CacheState,
    CacheTier,
    DataSource,
    RunStatus,
    TraceOutcome,
)
from src.diting.infra.errors import AnalysisError
from src.diting.schema import (
    AnalysisRequest,
    AnalysisRun,
    CacheInfo,
    DataResult,
    Instrument,
    InstrumentPage,
    OwnerSession,
    ProviderTrace,
    RealtimeQuote,
)
from src.diting.security.auth import AuthService, hash_owner_token
from src.diting.web.contracts_v1 import error_envelope
from src.diting.web.v1 import build_v1_router

NOW = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)


class FakeClock:
    def now(self) -> datetime:
        return NOW

    def today(self) -> date:
        return NOW.date()

    def monotonic(self) -> float:
        return 1.0


class FakeStore:
    def __init__(self) -> None:
        self.sessions: dict[str, OwnerSession] = {}
        self.run = None
        self.active = None

    def create_owner_session(self, session):
        self.sessions[session.session_id] = session

    def get_owner_session(self, session_id):
        return self.sessions.get(session_id)

    def revoke_owner_session(self, session_id, revoked_at):
        session = self.sessions.get(session_id)
        if session is None:
            return False
        from dataclasses import replace

        self.sessions[session_id] = replace(session, revoked_at=revoked_at)
        return True

    def get_analysis_run(self, run_id):
        return self.run if self.run and self.run.run_id == run_id else None

    def get_active_strategy(self, _name):
        return self.active


class FakeGateway:
    def __init__(self) -> None:
        trace = ProviderTrace(
            provider="fake-market",
            operation="quote",
            outcome=TraceOutcome.SUCCESS,
            started_at=NOW,
            finished_at=NOW,
        )
        quote = RealtimeQuote(
            "002475",
            "立讯精密",
            42,
            1.5,
            41,
            43,
            40,
            100,
            4200,
            pe=20,
            timestamp=NOW,
            source=DataSource.AKSHARE,
        )
        self.quote = DataResult(
            data=quote,
            data_time=NOW,
            cache_info=CacheInfo(
                state=CacheState.FRESH,
                tier=CacheTier.L2,
                cache_key="quote",
                cached_at=NOW,
                schema_version="quote-v1",
            ),
            provider_traces=(trace,),
            request_hash="quote-request",
        )
        self.search = DataResult(
            data=InstrumentPage(
                items=(Instrument("002475", "立讯精密", "SZ", "stock"),),
                total=1,
            ),
            data_time=NOW,
            provider_traces=(trace,),
            request_hash="search-request",
        )
        self.quote_calls = 0

    def get_quotes(self, request):
        self.quote_calls += 1
        return {request.symbols[0]: self.quote}

    def search_instruments(self, _request):
        return self.search


def _client(*, public_readonly: bool = True):
    store = FakeStore()
    gateway = FakeGateway()
    settings = AppConfig(
        runtime=RuntimeConfig(environment="test", public_readonly=public_readonly),
        security=SecurityConfig(allowed_origins=("http://testserver",)),
    )
    auth = AuthService(
        store,
        FakeClock(),
        owner_token_hash=hash_owner_token(
            "owner-token-0123456789",
            salt=b"0123456789abcdef",
            iterations=200_000,
        ),
        session_secret="session-secret-with-at-least-32-bytes",
    )
    container = create_container(
        settings,
        ApplicationDependencies(
            clock=FakeClock(),
            data_gateway=gateway,
            durable_store=store,
            auth=auth,
        ),
    )
    app = FastAPI()

    @app.middleware("http")
    async def request_id(request: Request, call_next):
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

    app.include_router(build_v1_router(container))
    return TestClient(app), gateway, store


def test_health_is_anonymous_and_uses_exact_envelope() -> None:
    client, _, _ = _client(public_readonly=False)
    try:
        response = client.get("/api/v1/health")
        body = response.json()

        assert response.status_code == 200
        assert set(body) == {"api_version", "request_id", "server_time", "data", "meta", "error"}
        assert body["api_version"] == "1.0"
        assert body["data"] == {"status": "ok", "version": "0.8.0"}
        assert body["request_id"] == response.headers["X-Request-ID"]
        assert body["error"] is None
    finally:
        client.close()


def test_public_quote_is_read_only_and_preserves_cache_freshness_trace() -> None:
    client, gateway, _ = _client()
    try:
        response = client.get("/api/v1/stocks/002475")
        body = response.json()

        assert response.status_code == 200
        assert gateway.quote_calls == 1
        assert body["data"]["symbol"] == "002475"
        assert body["data"]["price"] == 42
        assert body["data"]["source"] == "akshare"
        assert body["meta"]["cache"]["state"] == "fresh"
        assert body["meta"]["cache"]["level"] == "l2"
        assert body["meta"]["freshness"]["sources"] == ["fake-market"]
    finally:
        client.close()


def test_search_collection_has_stable_items_total_shape() -> None:
    client, _, _ = _client()
    try:
        response = client.get("/api/v1/instruments/search?q=立讯")
        data = response.json()["data"]

        assert response.status_code == 200
        assert data["total"] == 1
        assert data["items"][0]["symbol"] == "002475"
        assert isinstance(data["items"], list)
    finally:
        client.close()


def test_private_read_requires_owner_session() -> None:
    client, gateway, _ = _client(public_readonly=False)
    try:
        response = client.get("/api/v1/stocks/002475")

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTH_REQUIRED"
        assert response.json()["data"] is None
        assert gateway.quote_calls == 0
    finally:
        client.close()


def test_completed_analysis_is_returned_without_internal_error_detail() -> None:
    client, _, store = _client()
    store.run = AnalysisRun(
        run_id="run_public",
        request=AnalysisRequest("002475", AnalysisProfile.STANDARD),
        status=RunStatus.FAILED,
        snapshot_id="snapshot",
        snapshot_hash="snapshot-hash",
        config_hash="config-hash",
        strategy_version="analysis-v1",
        code_version="0.8.0",
        started_at=NOW,
        completed_at=NOW,
    )
    try:
        response = client.get("/api/v1/analyses/run_public")
        data = response.json()["data"]

        assert response.status_code == 200
        assert data["run_id"] == "run_public"
        assert data["status"] == "failed"
        assert "error_detail" not in response.text
    finally:
        client.close()


def test_no_active_strategy_is_explicit_and_never_uses_legacy_ranking() -> None:
    client, _, _ = _client()
    try:
        response = client.get("/api/v1/opportunities")
        body = response.json()

        assert response.status_code == 200
        assert body["data"] == {"items": [], "total": 0, "strategy_version": None}
        assert body["meta"]["result_status"] == "unavailable"
        assert body["meta"]["warnings"][0]["code"] == "NO_ACTIVE_STRATEGY"
    finally:
        client.close()


def test_validation_errors_use_same_envelope() -> None:
    client, _, _ = _client()
    try:
        response = client.get("/api/v1/stocks/not-a-code")
        body = response.json()

        assert response.status_code == 422
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert body["meta"]["result_status"] == "failed"
        assert body["request_id"] == response.headers["X-Request-ID"]
    finally:
        client.close()

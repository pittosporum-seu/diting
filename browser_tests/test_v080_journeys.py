"""Real Chromium journeys over a live FastAPI v0.8 application."""

from __future__ import annotations

import os
import socket
import subprocess
import threading
import time
import urllib.request
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from playwright.sync_api import Browser, expect, sync_playwright

from diting.bootstrap import ApplicationDependencies, create_container
from diting.config import AIConfig, AppConfig, RuntimeConfig, SecurityConfig
from diting.enums import (
    AnalysisProfile,
    CacheState,
    CacheTier,
    DataSource,
    EngineRunStatus,
    JobType,
    RunStatus,
    TraceOutcome,
)
from diting.infra.errors import AnalysisError
from diting.persistence.migrations import migrate_databases
from diting.persistence.store_v080 import SQLiteDurableStore
from diting.schema import (
    AnalysisRequest,
    AnalysisRun,
    CacheInfo,
    ConsensusResult,
    DataResult,
    EngineRun,
    Instrument,
    InstrumentPage,
    JobRecord,
    ProviderTrace,
    RealtimeQuote,
)
from diting.security.auth import AuthService, hash_owner_token
from diting.web.contracts_v1 import error_envelope
from diting.web.routes import build_router

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)
OWNER_TOKEN = "owner-token-0123456789"
RUN_ID = "run_browser"


class BrowserClock:
    def now(self) -> datetime:
        return NOW

    def today(self) -> date:
        return NOW.date()

    def monotonic(self) -> float:
        return time.monotonic()


class BrowserGateway:
    def __init__(self) -> None:
        trace = ProviderTrace(
            provider="browser-fixture",
            operation="quote",
            outcome=TraceOutcome.SUCCESS,
            started_at=NOW,
            finished_at=NOW,
        )
        self.quote = DataResult(
            data=RealtimeQuote(
                symbol="002475",
                name="立讯精密",
                price=42.0,
                change_pct=1.5,
                open=41.0,
                high=43.0,
                low=40.0,
                volume=1_000_000,
                turnover=42_000_000,
                pe=20.0,
                pb=4.0,
                timestamp=NOW,
                source=DataSource.AKSHARE,
            ),
            data_time=NOW,
            cache_info=CacheInfo(
                state=CacheState.FRESH,
                tier=CacheTier.L2,
                cache_key="browser:quote:002475",
                cached_at=NOW,
                schema_version="quote-v1",
            ),
            provider_traces=(trace,),
            request_hash="browser-quote",
        )
        self.search = DataResult(
            data=InstrumentPage(
                items=(Instrument("002475", "立讯精密", "SZ", "stock"),),
                total=1,
            ),
            data_time=NOW,
            provider_traces=(trace,),
            request_hash="browser-search",
        )

    def get_quotes(self, request):
        return {symbol: self.quote for symbol in request.symbols}

    def search_instruments(self, _request):
        return self.search


class BrowserJobs:
    def __init__(self) -> None:
        self.jobs: dict[str, JobRecord] = {}
        self.polls: dict[str, int] = {}

    def submit_analysis(self, _orchestrator, request) -> JobRecord:
        job = JobRecord(
            job_id=f"job_browser_{len(self.jobs) + 1}",
            job_type=JobType.ANALYSIS,
            status=RunStatus.QUEUED,
            progress=0,
            request_json="{}",
            created_at=NOW,
            deadline_at=request.deadline,
        )
        self.jobs[job.job_id] = job
        self.polls[job.job_id] = 0
        return job

    def get(self, job_id: str) -> JobRecord | None:
        job = self.jobs.get(job_id)
        if job is None or job.status in {RunStatus.SUCCEEDED, RunStatus.CANCELLED}:
            return job
        self.polls[job_id] += 1
        if self.polls[job_id] == 1:
            job = replace(job, status=RunStatus.RUNNING, progress=0.45, started_at=NOW)
        else:
            job = replace(
                job,
                status=RunStatus.SUCCEEDED,
                progress=1.0,
                result_ref=RUN_ID,
                finished_at=NOW,
            )
        self.jobs[job_id] = job
        return job

    def cancel(self, job_id: str) -> JobRecord | None:
        job = self.jobs.get(job_id)
        if job is None:
            return None
        job = replace(
            job,
            status=RunStatus.CANCELLED,
            cancel_requested=True,
            finished_at=NOW,
        )
        self.jobs[job_id] = job
        return job


class BrowserCache:
    def clear(self, _prefix=None) -> int:
        return 3


def _analysis_run() -> AnalysisRun:
    engine_run = EngineRun(
        engine_name="technical",
        engine_version="1.0.0",
        status=EngineRunStatus.SUCCEEDED,
        deterministic=True,
        started_at=NOW,
        finished_at=NOW,
        engine_score=72.0,
        confidence=0.8,
        duration_ms=12,
    )
    return AnalysisRun(
        run_id=RUN_ID,
        request=AnalysisRequest("002475", profile=AnalysisProfile.STANDARD),
        status=RunStatus.SUCCEEDED,
        snapshot_id="snapshot_browser",
        snapshot_hash="snapshot-hash-browser",
        config_hash="config-hash-browser",
        strategy_version="analysis-v1",
        code_version="0.8.0",
        started_at=NOW,
        engine_runs=(engine_run,),
        consensus=ConsensusResult(
            symbol="002475",
            analysis_score=72.0,
            confidence=0.8,
            weight_coverage=1.0,
            engines_used=("technical",),
            weight_snapshot=(("technical", 1.0),),
        ),
        completed_at=NOW,
    )


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def live_server(tmp_path_factory: pytest.TempPathFactory):
    port = _free_port()
    origin = f"http://127.0.0.1:{port}"
    directory = tmp_path_factory.mktemp("browser-v080")
    business = directory / "diting.db"
    migrate_databases(business, directory / "diting_cache.db")
    store = SQLiteDurableStore(business)
    store.save_analysis_run(_analysis_run())
    clock = BrowserClock()
    settings = AppConfig(
        runtime=RuntimeConfig(environment="test", public_readonly=True),
        security=SecurityConfig(allowed_origins=(origin,)),
        ai=AIConfig(enabled=False),
    )
    auth = AuthService(
        store,
        clock,
        owner_token_hash=hash_owner_token(
            OWNER_TOKEN,
            salt=b"0123456789abcdef",
            iterations=200_000,
        ),
        session_secret="browser-session-secret-with-at-least-32-bytes",
    )
    container = create_container(
        settings,
        ApplicationDependencies(
            clock=clock,
            data_gateway=BrowserGateway(),
            cache_store=BrowserCache(),
            durable_store=store,
            analysis=object(),
            jobs=BrowserJobs(),
            auth=auth,
            scanner=object(),
        ),
    )
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
            message=str(exc) if exc.http_status_code < 500 else "服务暂时不可用",
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

    app.include_router(build_router(container, frontend_dir=ROOT / "frontend"))
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    )
    thread = threading.Thread(target=server.run, name="browser-v080-server", daemon=True)
    thread.start()
    for _attempt in range(100):
        try:
            with urllib.request.urlopen(f"{origin}/api/v1/health", timeout=0.2) as response:
                if response.status == 200:
                    break
        except OSError:
            time.sleep(0.05)
    else:
        server.should_exit = True
        thread.join(timeout=5)
        pytest.fail("live FastAPI browser fixture did not become ready")

    yield origin

    server.should_exit = True
    thread.join(timeout=10)
    assert not thread.is_alive()


@pytest.fixture(scope="module")
def chromium():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        yield browser
        browser.close()


@contextmanager
def guarded_page(browser: Browser, name: str):
    artifacts = ROOT / "browser-artifacts"
    context = browser.new_context(locale="zh-CN", viewport={"width": 1440, "height": 1000})
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page = context.new_page()
    issues: list[str] = []
    page.on(
        "console",
        lambda message: (
            issues.append(f"console.{message.type}: {message.text}")
            if message.type in {"error", "warning"}
            else None
        ),
    )
    page.on("pageerror", lambda error: issues.append(f"pageerror: {error}"))
    try:
        yield page
        assert issues == []
    except BaseException:
        artifacts.mkdir(exist_ok=True)
        page.screenshot(path=artifacts / f"{name}.png", full_page=True)
        context.tracing.stop(path=artifacts / f"{name}.zip")
        raise
    else:
        context.tracing.stop()
    finally:
        context.close()


def test_candidate_smoke_covers_public_security_and_owner_contract(live_server: str) -> None:
    environment = os.environ.copy()
    environment["DITING_OWNER_TOKEN"] = OWNER_TOKEN
    environment["DITING_SMOKE_ORIGIN"] = live_server
    inherited_wslenv = environment.get("WSLENV", "")
    environment["WSLENV"] = ":".join(
        item
        for item in (
            inherited_wslenv,
            "DITING_OWNER_TOKEN",
            "DITING_SMOKE_ORIGIN",
        )
        if item
    )
    process = subprocess.run(
        ["bash", "scripts/smoke_test.sh", f"{live_server}/api/v1"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert process.returncode == 0, process.stdout + process.stderr
    assert "11 passed, 0 failed" in process.stdout
    assert OWNER_TOKEN not in process.stdout
    assert OWNER_TOKEN not in process.stderr


def test_anonymous_five_page_journey_has_explicit_states(
    live_server: str,
    chromium: Browser,
) -> None:
    with guarded_page(chromium, "anonymous-five-pages") as page:
        page.goto(f"{live_server}/#/dashboard", wait_until="networkidle")
        expect(page.locator("#system-label")).to_have_text("服务正常")
        expect(page.locator("#auth-state")).to_have_text("访客只读")
        expect(page.locator("#app-root")).to_contain_text("当前没有可用于生产排名的策略")

        routes = (
            ("stock", "个股分析", "输入证券代码"),
            ("opportunities", "机会策略", "NO_ACTIVE_STRATEGY"),
            ("watchlist", "自选列表", "需要 Owner 权限"),
            ("settings", "系统设置", "需要 Owner 权限"),
            ("dashboard", "市场概览", "生产策略"),
        )
        for route, heading, expected in routes:
            page.locator(f'[data-route="{route}"]').click()
            expect(page.locator("#page-title")).to_have_text(heading)
            expect(page.locator("#app-root")).to_contain_text(expected)


def test_owner_login_analysis_watchlist_settings_and_logout_journey(
    live_server: str,
    chromium: Browser,
) -> None:
    with guarded_page(chromium, "owner-full-journey") as page:
        page.goto(f"{live_server}/#/settings", wait_until="networkidle")
        expect(page.locator("#app-root")).to_contain_text("需要 Owner 权限")

        page.locator("#auth-button").click()
        page.locator("#owner-token").fill(OWNER_TOKEN)
        page.locator("#login-submit").click()
        expect(page.locator("#auth-state")).to_have_text("Owner 会话")
        expect(page.locator("#app-root")).to_contain_text("mean_reversion_v1（未激活）")
        expect(page.locator("#app-root")).to_contain_text("Unavailable")

        page.locator('select[name="theme"]').select_option("dark")
        page.locator('select[name="default_profile"]').select_option("standard")
        page.locator('input[type="number"]').fill("30")
        page.get_by_role("button", name="保存偏好").click()
        expect(page.locator("#toast-region")).to_contain_text("偏好已保存")

        page.locator('[data-route="watchlist"]').click()
        expect(page.locator("#page-title")).to_have_text("自选列表")
        page.get_by_role("button", name="添加证券").click()
        page.locator('dialog input[name="symbol"]').fill("002475")
        page.locator('dialog input[name="name"]').fill("立讯精密")
        page.locator("dialog").get_by_role("button", name="保存").click()
        expect(page.locator("#app-root")).to_contain_text("立讯精密")
        page.get_by_role("button", name="移除").click()
        expect(page.locator("#app-root")).to_contain_text("自选列表为空")

        page.goto(f"{live_server}/#/stock/002475", wait_until="networkidle")
        expect(page.locator("#app-root")).to_contain_text("42.00")
        page.get_by_role("button", name="标准分析").click()
        expect(page.locator(".analysis-panel .freshness")).to_contain_text("running · 45%")
        expect(page.locator(".analysis-panel")).to_contain_text("分析已持久化", timeout=5_000)
        expect(page.locator(".analysis-panel")).to_contain_text("72.0")

        page.locator("#auth-button").click()
        expect(page.locator("#auth-state")).to_have_text("访客只读")
        expect(page.locator("#toast-region")).to_contain_text("已退出 Owner 会话")

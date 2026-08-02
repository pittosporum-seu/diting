"""Integration contract for the v0.8 HTTP application surface."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.diting.bootstrap import ApplicationDependencies, create_container
from src.diting.config import AppConfig, RuntimeConfig
from src.diting.security.auth import AuthService
from src.diting.web.app import create_app


@pytest.fixture
def client(tmp_path):
    frontend = tmp_path / "frontend"
    (frontend / "css").mkdir(parents=True)
    (frontend / "index.html").write_text(
        "<!doctype html><title>Diting v0.8</title>",
        encoding="utf-8",
    )
    (frontend / "css" / "styles.css").write_text("body {}", encoding="utf-8")
    container = create_container(
        AppConfig(runtime=RuntimeConfig(environment="test", public_readonly=False)),
        ApplicationDependencies(
            auth=MagicMock(spec=AuthService),
            data_gateway=MagicMock(),
            durable_store=MagicMock(),
        ),
    )
    with TestClient(create_app(container, frontend_dir=frontend)) as test_client:
        yield test_client


@pytest.mark.parametrize(
    ("method", "path"),
    (
        ("GET", "/api/health"),
        ("GET", "/api/stock/002475"),
        ("POST", "/api/settings"),
        ("DELETE", "/api/watchlist/002475"),
    ),
)
def test_unversioned_api_is_permanently_removed(client: TestClient, method: str, path: str) -> None:
    response = client.request(method, path)
    body = response.json()

    assert response.status_code == 410
    assert body["api_version"] == "1.0"
    assert body["error"] == {
        "code": "API_VERSION_REMOVED",
        "message": "The unversioned API was removed in Diting 0.8; use /api/v1.",
        "retryable": False,
    }
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert body["data"] is None


def test_unknown_v1_route_is_not_misreported_as_legacy(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_v1_health_remains_the_canonical_health_endpoint(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["data"] == {"status": "ok", "version": "0.8.0"}


def test_spa_routes_and_assets_are_served_without_jinja(client: TestClient) -> None:
    root = client.get("/")
    deep_link = client.get("/stock/002475")
    asset = client.get("/css/styles.css")
    missing_asset = client.get("/js/missing.js")

    assert root.status_code == deep_link.status_code == asset.status_code == 200
    assert root.text == deep_link.text
    assert asset.text == "body {}"
    assert missing_asset.status_code == 404


def test_production_route_graph_has_no_legacy_service_or_template_imports() -> None:
    from src.diting.web import app, routes

    app_source = Path(app.__file__).read_text(encoding="utf-8")
    route_source = Path(routes.__file__).read_text(encoding="utf-8")

    assert "Jinja2" not in app_source
    assert "prefetch" not in app_source
    assert ".services" not in route_source
    assert "CacheManager" not in route_source
    assert "TemplateResponse" not in route_source

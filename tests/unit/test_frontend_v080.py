"""Static architecture guards for the dependency-free v0.8 frontend shell."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_frontend_has_one_api_client_and_one_application_state_machine() -> None:
    scripts = sorted((FRONTEND / "js").rglob("*.js"))

    assert [path.name for path in scripts] == ["api.js", "app.js"]
    assert "fetch(" in _read(FRONTEND / "js" / "api.js")
    assert "fetch(" not in _read(FRONTEND / "js" / "app.js")
    assert "const state =" in _read(FRONTEND / "js" / "app.js")
    assert all(
        phase in _read(FRONTEND / "js" / "app.js")
        for phase in ("loading", "ready", "empty", "error", "auth-required")
    )


def test_api_client_uses_only_v1_contract_and_csrf_for_mutations() -> None:
    source = _read(FRONTEND / "js" / "api.js")

    assert "'/api/v1'" in source
    assert "'/api/diting/v1'" in source
    assert "X-CSRF-Token" in source
    assert "credentials: 'same-origin'" in source
    assert "sessionStorage" in source
    assert all(
        endpoint in source
        for endpoint in (
            "/analyses",
            "/jobs/",
            "/watchlist",
            "/preferences",
            "/admin/cache/clear",
            "/admin/strategy",
            "/admin/diagnostics",
        )
    )
    assert "/api/stock" not in source
    assert "cacheManager" not in source


def test_shell_exposes_five_pages_auth_and_no_external_runtime_dependency() -> None:
    html = _read(FRONTEND / "index.html")

    assert all(
        route in html
        for route in (
            "#/dashboard",
            "#/stock",
            "#/opportunities",
            "#/watchlist",
            "#/settings",
        )
    )
    assert "login-dialog" in html
    assert "owner-token" in html
    assert "cdn.jsdelivr" not in html
    assert "v=0.7" not in html
    assert "🐾" not in html


def test_page_rendering_does_not_assign_unescaped_html_or_emit_debug_markers() -> None:
    source = _read(FRONTEND / "js" / "app.js")

    assert ".innerHTML" not in source
    assert "renderPage called" not in source
    assert "window.__loaded" not in source
    assert "console.log" not in source
    assert "console.warn" not in source
    assert "insertAdjacentHTML" not in source


def test_design_tokens_cover_light_dark_semantic_and_responsive_states() -> None:
    css = _read(FRONTEND / "css" / "styles.css")

    assert ':root[data-theme="dark"]' in css
    assert all(token in css for token in ("--danger", "--warning", "--success", "--info"))
    assert "@media (max-width: 760px)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert ".button:active" in css
    assert ".skeleton" in css
    assert ".toast" in css

"""AST dependency guards for the v0.8 composition boundary."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src" / "diting"

LEGACY_PROVIDER_IMPORT_EXCEPTIONS: set[str] = set()


def _provider_import_violations() -> set[str]:
    violations: set[str] = set()
    for path in SOURCE.rglob("*.py"):
        relative = path.relative_to(ROOT).as_posix()
        if relative == "src/diting/bootstrap.py" or relative.startswith("src/diting/data/"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = ""
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
            elif isinstance(node, ast.Import):
                module = " ".join(alias.name for alias in node.names)
            if "data.providers" in module:
                violations.add(relative)
    return violations


def test_concrete_market_provider_imports_have_no_new_bypasses() -> None:
    assert _provider_import_violations() == LEGACY_PROVIDER_IMPORT_EXCEPTIONS


def test_ports_do_not_import_adapters_or_interfaces() -> None:
    tree = ast.parse((SOURCE / "ports.py").read_text(encoding="utf-8"))
    forbidden = {"fastapi", "litellm", "akshare", "data.providers", "web"}
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert not {name for name in imported if any(item in name for item in forbidden)}


def test_web_data_paths_do_not_reference_legacy_raw_cache_tables() -> None:
    services = SOURCE / "web" / "services"
    forbidden = {"historical_cache", "watchlist_cache", "market_snapshot"}
    violations = {}
    for path in services.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        found = {
            name
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            for name in forbidden
            if name in node.value
        }
        if found:
            violations[path.name] = sorted(found)
    assert violations == {}


def test_interfaces_do_not_import_the_legacy_repository() -> None:
    violations = set()
    for relative in ("main.py", "web/routes.py", "web/services/_utils.py"):
        path = SOURCE / relative
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and "data.repository" in (node.module or ""):
                violations.add(relative)
    assert violations == set()

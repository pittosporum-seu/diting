"""Active documentation must describe the executable v0.8 contracts."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml

from src.diting.main import cli

ROOT = Path(__file__).resolve().parents[2]
ACTIVE_DOCS = (
    "README.md",
    "CONTRIBUTING.md",
    "AGENTS.md",
    "docs/README.md",
    "docs/01-design/README.md",
    "docs/01-design/api-contracts.md",
    "docs/01-design/development-workflow.md",
    "docs/01-design/v0.8.0-system-design.md",
    "docs/tutorials/quickstart.md",
    "docs/reference/configuration.md",
    "docs/how-to/extend-engine.md",
    "docs/how-to/activate-strategy.md",
    "docs/ops/deploy-checklist.md",
    "docs/research/INDEX.md",
)
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_readme_version_and_interface_facts_match_runtime_contracts() -> None:
    project = tomllib.loads(_read("pyproject.toml"))
    openapi = yaml.safe_load(_read("docs/api/diting-openapi.yaml"))
    readme = _read("README.md")

    assert project["project"]["version"] == "0.8.0"
    assert f"当前版本：`{project['project']['version']}`" in readme
    assert openapi["info"]["version"] == project["project"]["version"]
    assert set(cli.commands) == {
        "analyze",
        "compare",
        "quote",
        "scan",
        "serve",
        "strategy",
        "watchlist",
    }
    assert all(f"diting {command}" in readme for command in ("quote", "analyze", "scan"))
    assert all(
        engine in readme
        for engine in ("technical", "volume profile", "Wyckoff", "CANSLIM", "Buffett")
    )
    assert re.search(r"\b\d+ passed\b", readme) is None


def test_every_relative_link_in_active_markdown_resolves() -> None:
    missing: list[str] = []
    for relative in ACTIVE_DOCS:
        document = ROOT / relative
        for raw_target in MARKDOWN_LINK.findall(document.read_text(encoding="utf-8")):
            target = raw_target.strip().split("#", 1)[0].split("?", 1)[0]
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            resolved = (document.parent / target).resolve()
            if not resolved.exists():
                missing.append(f"{relative} -> {raw_target}")

    assert missing == []


def test_active_docs_do_not_reintroduce_removed_release_or_api_contracts() -> None:
    combined = "\n".join(_read(relative) for relative in ACTIVE_DOCS)

    assert "deploy.sh --skip-tests" not in combined
    assert "529 passed" not in combined
    assert "v0.2.1" not in combined
    assert "@register_engine" not in combined
    assert "/api/stock/" not in combined


def test_design_index_marks_pre_v080_families_as_superseded() -> None:
    index = _read("docs/01-design/README.md")

    assert "v0.8.0-system-design.md" in index
    assert "**Accepted**" in index
    assert "Superseded" in index
    assert all(family in index for family in ("v0.1.0-*", "v0.6.5-*", "v0.7.2-*"))


def test_research_index_matches_fail_closed_production_state() -> None:
    research = _read("docs/research/INDEX.md")

    assert "已实现" in research
    assert "尚未 validated/approved/active" in research
    assert "NO_ACTIVE_STRATEGY" in research
    assert "未伪造研究通过或 active 状态" in research


def test_documented_release_commands_exist_in_controller() -> None:
    controller = _read("scripts/deploy.sh")
    deployment = _read("docs/ops/deploy-checklist.md")

    for command in ("package", "stage", "verify", "rehearse", "promote", "rollback"):
        assert f"deploy.sh {command}" in deployment
        assert f"{command})" in controller

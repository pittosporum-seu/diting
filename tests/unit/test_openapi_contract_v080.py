"""Runtime-generated OpenAPI contract gates for the breaking v0.8 surface."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "docs" / "api" / "diting-openapi.yaml"


def test_checked_in_openapi_matches_runtime_without_loading_ai_client() -> None:
    process = subprocess.run(
        [sys.executable, "scripts/validate-api.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert process.returncode == 0, process.stdout + process.stderr
    assert "litellm" not in process.stdout.lower()
    assert "litellm" not in process.stderr.lower()


def test_contract_contains_only_versioned_runtime_paths() -> None:
    schema = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))

    assert schema["info"]["version"] == "0.8.0"
    assert schema["x-production-gateway-prefix"] == "/api/diting/v1"
    assert schema["paths"]
    assert all(path.startswith("/api/v1/") for path in schema["paths"])
    assert "/api/v1/auth/session" in schema["paths"]
    assert "/api/v1/opportunities" in schema["paths"]
    assert "/api/v1/scans" in schema["paths"]


def test_ci_has_no_path_filter_and_checks_non_python_surfaces() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    tests = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")

    assert "paths-filter" not in ci
    assert 'if [[ "$result" != "success" ]]' in ci
    assert "scripts/validate-api.py --check" in tests
    assert "node --check" in tests
    assert "bash -n" in tests

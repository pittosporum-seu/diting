#!/usr/bin/env python3
"""Generate or verify the checked-in FastAPI OpenAPI contract."""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path
from typing import Any, cast

import yaml
from fastapi import FastAPI

from diting import __version__
from diting.bootstrap import ApplicationContainer, SystemClock
from diting.config import AIConfig, AppConfig, RuntimeConfig
from diting.web.routes import build_router

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_FILE = PROJECT_ROOT / "docs" / "api" / "diting-openapi.yaml"
FRONTEND_DIR = PROJECT_ROOT / "frontend"


def build_runtime_schema() -> dict[str, Any]:
    """Build the schema from the same route factories and Pydantic models as production."""

    sentinel = cast(Any, object())
    settings = AppConfig(
        runtime=RuntimeConfig(environment="test", public_readonly=True),
        ai=AIConfig(enabled=False),
    )
    container = ApplicationContainer(
        settings=settings,
        clock=SystemClock(),
        data_gateway=sentinel,
        durable_store=sentinel,
        auth=sentinel,
    )
    application = FastAPI(
        title="谛听",
        version=__version__,
        description=(
            "Diting v0.8 typed API. FastAPI serves /api/v1/* internally; the production "
            "gateway exposes the same routes at /api/diting/v1/*."
        ),
    )
    application.include_router(build_router(container, frontend_dir=FRONTEND_DIR))
    schema = application.openapi()
    schema["servers"] = [
        {
            "url": "/",
            "description": "Internal FastAPI route root; paths include /api/v1",
        }
    ]
    schema["x-production-gateway-prefix"] = "/api/diting/v1"
    return schema


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _yaml_text(schema: dict[str, Any]) -> str:
    return yaml.safe_dump(
        schema,
        allow_unicode=True,
        sort_keys=False,
        width=120,
    )


def write_contract() -> int:
    """Replace the checked-in contract with the current runtime schema."""

    CONTRACT_FILE.write_text(_yaml_text(build_runtime_schema()), encoding="utf-8", newline="\n")
    print(f"OpenAPI contract written: {CONTRACT_FILE.relative_to(PROJECT_ROOT)}")
    return 0


def check_contract() -> int:
    """Fail when the checked-in document differs semantically from the runtime schema."""

    if not CONTRACT_FILE.is_file():
        print(f"OpenAPI contract is missing: {CONTRACT_FILE}", file=sys.stderr)
        return 1
    checked_in = yaml.safe_load(CONTRACT_FILE.read_text(encoding="utf-8"))
    runtime = build_runtime_schema()
    if _canonical(checked_in) == _canonical(runtime):
        print("OpenAPI contract matches the FastAPI runtime schema")
        return 0

    diff = difflib.unified_diff(
        _yaml_text(checked_in).splitlines(),
        _yaml_text(runtime).splitlines(),
        fromfile="checked-in",
        tofile="runtime",
        lineterm="",
    )
    print("OpenAPI contract is stale; run: uv run python scripts/validate-api.py --write")
    print("\n".join(list(diff)[:200]))
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="compare checked-in and runtime schema")
    mode.add_argument("--write", action="store_true", help="regenerate the checked-in schema")
    args = parser.parse_args()
    return check_contract() if args.check else write_contract()


if __name__ == "__main__":
    raise SystemExit(main())

"""Version-source consistency tests."""

from __future__ import annotations

import tomllib
from pathlib import Path

from click.testing import CliRunner

from src.diting import __version__
from src.diting.main import cli
from src.diting.web.app import app


def test_runtime_surfaces_use_pyproject_version() -> None:
    root = Path(__file__).resolve().parents[2]
    with (root / "pyproject.toml").open("rb") as handle:
        project_version = tomllib.load(handle)["project"]["version"]

    assert project_version == "0.8.0"
    assert __version__ == project_version
    assert app.version == project_version

    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert project_version in result.output

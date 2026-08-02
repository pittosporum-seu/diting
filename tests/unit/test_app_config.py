"""Strict application-configuration tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.diting.config import AppConfig, load_app_config
from src.diting.infra.config_loader import ConfigLoader
from src.diting.infra.errors import ConfigError


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_precedence_is_overrides_environment_yaml_defaults(tmp_path: Path) -> None:
    config_path = _write(
        tmp_path / "diting.yaml",
        """
runtime:
  public_readonly: false
pipeline:
  max_workers: 2
""",
    )

    settings = load_app_config(
        config_path,
        environ={"DITING_PUBLIC_READONLY": "true", "DITING_LOG": "INFO"},
        overrides={"runtime.public_readonly": False, "pipeline": {"max_workers": 7}},
    )

    assert settings.runtime.public_readonly is False
    assert settings.runtime.log_level == "INFO"
    assert settings.pipeline.max_workers == 7
    assert settings.pipeline.queue_limit == 100


@pytest.mark.parametrize(
    "content",
    [
        "unknown_section: true\n",
        "pipeline:\n  max_workerz: 4\n",
        "providers:\n  - name: mx_data\n    settings:\n      batch_limit: 4\n",
    ],
)
def test_unknown_yaml_fields_are_rejected(tmp_path: Path, content: str) -> None:
    with pytest.raises(ConfigError, match="配置校验失败"):
        load_app_config(_write(tmp_path / "diting.yaml", content), environ={})


@pytest.mark.parametrize(
    "content, field_name",
    [
        ("security:\n  session_secret: exposed\n", "security.session_secret"),
        ("ai:\n  api_key: exposed\n", "ai.api_key"),
        ("credentials:\n  mx_api_key: exposed\n", "credentials.mx_api_key"),
    ],
)
def test_secrets_are_rejected_in_yaml(tmp_path: Path, content: str, field_name: str) -> None:
    with pytest.raises(ConfigError, match=field_name):
        load_app_config(_write(tmp_path / "diting.yaml", content), environ={})


def test_secrets_can_be_injected_without_plaintext_repr(tmp_path: Path) -> None:
    settings = load_app_config(
        tmp_path / "missing.yaml",
        environ={
            "DITING_SESSION_SECRET": "session-value",
            "MX_APIKEY": "mx-value",
        },
    )

    assert settings.security.session_secret is not None
    assert settings.security.session_secret.get_secret_value() == "session-value"
    assert "session-value" not in repr(settings)
    assert "mx-value" not in repr(settings)


def test_production_report_directory_can_be_injected_from_environment(tmp_path: Path) -> None:
    settings = load_app_config(
        tmp_path / "missing.yaml",
        environ={"DITING_REPORT_OUTPUT_DIR": "/var/lib/diting/reports"},
    )

    assert settings.report.output_dir == Path("/var/lib/diting/reports")


def test_configuration_is_deeply_frozen() -> None:
    settings = AppConfig()
    with pytest.raises(ValidationError):
        settings.pipeline.max_workers = 9


def test_config_loader_only_exposes_configured_snapshot(tmp_path: Path) -> None:
    settings = load_app_config(
        tmp_path / "missing.yaml",
        environ={},
        overrides={"pipeline.max_workers": 6},
    )
    ConfigLoader.configure(settings)
    try:
        assert ConfigLoader.current() is settings
        assert ConfigLoader.get_section("pipeline")["max_workers"] == 6
        assert ConfigLoader.get_section("missing") == {}
    finally:
        ConfigLoader.reset()

"""P1-8 eltdx 配置与设置界面残留清理回归测试。"""

from pathlib import Path
from unittest.mock import MagicMock

import yaml

from diting.web.services import AnalysisService, DashboardService

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_PROVIDER_KEYS = [
    "provider_eastmoney",
    "provider_ashare",
    "provider_mxdata",
    "provider_akshare",
]


def _db_with_settings(settings: dict[str, str] | None = None) -> MagicMock:
    db = MagicMock()
    db.get_settings.return_value = settings or {}
    return db


def test_active_provider_config_excludes_eltdx() -> None:
    """当前 YAML provider 列表不再声明 eltdx，其他顺序保持不变。"""
    config = yaml.safe_load((ROOT / "config/diting.yaml").read_text(encoding="utf-8"))

    assert [provider["name"] for provider in config["providers"]] == [
        "ashare",
        "mx_data",
        "akshare",
    ]


def test_dashboard_settings_exclude_eltdx() -> None:
    """当前 API 使用的 DashboardService 不再返回 eltdx 开关。"""
    settings = DashboardService(watchlist_db=_db_with_settings()).get_settings()

    assert [item["key"] for item in settings["provider_toggles"]] == EXPECTED_PROVIDER_KEYS
    assert all("eltdx" not in item["label"].lower() for item in settings["provider_toggles"])


def test_legacy_analysis_settings_exclude_eltdx() -> None:
    """向后兼容的复合服务同样不再返回 eltdx 开关。"""
    db = _db_with_settings()
    db.list.return_value = []
    settings = AnalysisService(watchlist_db=db).get_settings()

    assert [item["key"] for item in settings["provider_toggles"]] == EXPECTED_PROVIDER_KEYS
    assert [item["requires_api_key"] for item in settings["provider_toggles"]] == [
        False,  # eastmoney
        False,  # ashare
        True,  # mxdata
        False,  # akshare
    ]


def test_settings_page_does_not_hardcode_adapter_degradation_chain() -> None:
    """v0.8 前端只读脱敏 diagnostics，不复制 bootstrap 的 Provider 顺序。"""
    app_source = (ROOT / "frontend/js/app.js").read_text(encoding="utf-8")
    api_source = (ROOT / "frontend/js/api.js").read_text(encoding="utf-8")

    assert "/admin/diagnostics" in api_source
    assert "eltdx" not in app_source.lower()
    assert "east_money →" not in app_source
    assert "mx_data →" not in app_source


def test_provider_order_is_declared_only_in_bootstrap_config() -> None:
    """Interfaces no longer construct their own Provider degradation chain."""
    config = yaml.safe_load((ROOT / "config/diting.yaml").read_text(encoding="utf-8"))
    priorities = [item["priority"] for item in config["providers"]]

    assert priorities == sorted(priorities)
    service = DashboardService(watchlist_db=_db_with_settings())
    try:
        service._build_repo()
    except RuntimeError as exc:
        assert "DataGateway" in str(exc)
    else:
        raise AssertionError("Web service constructed a Provider without bootstrap injection")

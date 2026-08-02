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


def test_settings_page_shows_real_degradation_chain() -> None:
    """前端只展示当前仓库实际采用的数据源降级链。"""
    source = (ROOT / "frontend/js/pages/settings.js").read_text(encoding="utf-8")

    assert "降级链顺序：east_money → ashare → akshare" in source
    assert "降级链顺序：eltdx" not in source


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

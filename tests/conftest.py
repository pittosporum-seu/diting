"""pytest 全局配置。

自动给依赖外部网络数据源（ashare/腾讯等）的测试打 `network` 标记，
便于 CI 在需要时用 `-m "not network"` 排除这些可能较慢/偶发的测试。
"""

import pytest

# 整个文件的测试都依赖网络的模块（按文件路径子串匹配）
_NETWORK_FILES = (
    "test_dashboard_monitor.py",
    "test_web_flows.py",
    "test_web_api.py",
)

# 文件内只有部分类依赖网络（文件路径子串 -> 类名集合）
_NETWORK_CLASSES = {
    "test_data_fallback.py": {"TestAshareProvider"},
}


def pytest_collection_modifyitems(config, items):
    for item in items:
        path = str(item.fspath)
        if any(name in path for name in _NETWORK_FILES):
            item.add_marker(pytest.mark.network)
            continue
        for file_substr, classes in _NETWORK_CLASSES.items():
            if file_substr in path and item.cls is not None:
                if item.cls.__name__ in classes:
                    item.add_marker(pytest.mark.network)
                break

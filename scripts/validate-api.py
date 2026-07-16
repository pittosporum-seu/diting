#!/usr/bin/env python3
"""校验 OpenAPI 契约与 routes.py 实现的一致性"""
import re
import yaml
import sys
from pathlib import Path


def get_openapi_paths(api_file: str) -> set[tuple[str, str]]:
    """从 OpenAPI YAML 提取 (path, method) 集合。

    OpenAPI 中 paths 是相对路径（如 /health），加上前缀 /api
    后对应 routes.py 中的实际路由。
    """
    spec = yaml.safe_load(Path(api_file).read_text())
    return {
        (f"/api{path}", method.upper())
        for path, methods in spec["paths"].items()
        for method in methods
    }


def get_routes_paths(routes_file: str) -> set[tuple[str, str]]:
    """从 routes.py 提取 (path, method) 集合。

    匹配 @router.get("/api/health") 等装饰器。
    排除 Jinja2 页面路由和 SPA catch-all。
    """
    text = Path(routes_file).read_text()
    pattern = r'@router\.(get|post|put|delete)\(["\'](/api/[^"\']+)["\']'
    return {(path, method.upper()) for method, path in re.findall(pattern, text)}


def main() -> int:
    api_paths = get_openapi_paths("docs/api/diting-openapi.yaml")
    route_paths = get_routes_paths("src/diting/web/routes.py")

    missing = api_paths - route_paths   # 契约有，routes 没有
    extra = route_paths - api_paths     # routes 有，契约没有

    rc = 0
    if missing:
        print(f"❌ 契约中有但 routes.py 缺失: {sorted(missing)}")
        rc = 1
    if extra:
        print(f"⚠️ routes.py 中有但契约未定义: {sorted(extra)}")
        # extra routes are warnings, not errors
    if not missing and not extra:
        print("✅ 契约与实现一致")
    elif not missing:
        print("✅ 契约端点已全部实现（routes.py 有额外路由）")

    return rc


if __name__ == "__main__":
    sys.exit(main())

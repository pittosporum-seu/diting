"""谛听 · Web 服务 — FastAPI 应用

挂载静态文件、初始化 Jinja2 模板、注册路由。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates


class NumpyEncoder(json.JSONEncoder):
    """Handle numpy types in JSON serialization."""
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.ndarray,)):
            return obj.tolist()
        return super().default(obj)

# ── suppress LiteLLM debug noise ──
os.environ.setdefault("LITELLM_LOG", "ERROR")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
TEMPLATES = Path(__file__).resolve().parent / "templates"
STATIC = Path(__file__).resolve().parent / "static"
FRONTEND = PROJECT_ROOT / "frontend"

app = FastAPI(title="谛听", version="0.3.0")
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
app.mount("/app", StaticFiles(directory=str(FRONTEND), html=True), name="frontend")
templates = Jinja2Templates(directory=str(TEMPLATES))

from .routes import router  # noqa: E402, I001
app.include_router(router)

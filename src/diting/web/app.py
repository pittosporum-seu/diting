"""谛听 · Web 服务 — FastAPI 应用

挂载静态文件、初始化 Jinja2 模板、注册路由。
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

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

from .routes import router  # noqa: E402, I001  — must follow templates init
app.include_router(router)

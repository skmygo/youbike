"""YouBike 智慧調度平台 API。

看得到（視覺化）→ 猜得到（預測）→ 叫得動（警示與調度）
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db, settings
from .routes import router as api_router

app = FastAPI(
    title="YouBike 智慧調度平台 API",
    description="新北市政府 AI 黑客松・交通局命題",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "youbike-api",
        "version": app.version,
        "now": datetime.now(timezone.utc).isoformat(),
        "commit": os.getenv("GIT_COMMIT", "dev"),
        "data": db.data_status(),
    }


# ── 前端靜態檔（SPA fallback）────────────────────────────────────────────
_dist = settings.WEB_DIST
if (_dist / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    """所有非 /api 路徑交給前端 router；前端還沒建置就回佔位頁。"""
    if full_path.startswith("api/"):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    candidate = _dist / full_path
    if full_path and candidate.is_file():
        return FileResponse(candidate)

    index = _dist / "index.html"
    if index.is_file():
        return FileResponse(index)

    return JSONResponse(
        {
            "service": "YouBike 智慧調度平台",
            "note": "前端建置產物尚未就緒，API 可用：/api/health、/api/docs",
        },
        status_code=200,
    )

"""資料 API 路由（掛在 /api 之下）。

所有查詢都走 DuckDB in-memory 讀 parquet；parquet 不存在時回空集合而不是
500，讓前端能在資料引導完成前先渲染（degraded 模式）。
"""
from __future__ import annotations

from fastapi import APIRouter

from . import db, settings

router = APIRouter()


@router.get("/meta")
def meta() -> dict:
    """資料涵蓋範圍與最後更新時間，前端頁首顯示用。"""
    out: dict = {"data": db.data_status()}
    if settings.LATEST_PARQUET.exists():
        row = db.query_one(
            "SELECT max(ts) AS last_ts, count(*) AS n_stations "
            f"FROM read_parquet('{settings.LATEST_PARQUET}')"
        )
        out["realtime"] = row
    return out

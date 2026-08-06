"""DuckDB 查詢層。

每次請求開一顆 in-memory 連線去查 parquet：沒有檔案鎖、pipeline 換檔
（原子 rename）不會擋到讀取，也不用管連線池。parquet 都在本機 volume，
開連線成本遠低於查詢本身。
"""
from __future__ import annotations

from typing import Any

import duckdb

from . import settings


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    con.execute("SET TimeZone='Asia/Taipei'")
    return con


def query(sql: str, params: list | dict | None = None) -> list[dict[str, Any]]:
    con = connect()
    try:
        rel = con.execute(sql, params) if params is not None else con.execute(sql)
        cols = [d[0] for d in rel.description]
        return [dict(zip(cols, row)) for row in rel.fetchall()]
    finally:
        con.close()


def query_one(sql: str, params: list | dict | None = None) -> dict[str, Any] | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def parquet_exists(path) -> bool:
    from pathlib import Path

    p = Path(path)
    if p.exists():
        return True
    # glob 形式
    parent = p.parent
    return parent.exists() and any(parent.glob(p.name))


def data_status() -> dict[str, Any]:
    """回報各層資料是否就緒（health 與前端 degraded 提示都用這個）。"""
    from pathlib import Path

    def stat(p: Path) -> dict[str, Any]:
        if p.exists():
            st = p.stat()
            return {"ready": True, "bytes": st.st_size, "mtime": int(st.st_mtime)}
        return {"ready": False}

    hist = sorted(settings.HISTORY_DIR.glob("snapshots_*.parquet"))
    return {
        "history_months": len(hist),
        "history_bytes": sum(f.stat().st_size for f in hist),
        "latest": stat(settings.LATEST_PARQUET),
        "stations": stat(settings.STATIONS_PARQUET),
        "alerts": stat(settings.ALERTS_PARQUET),
        "hourly": stat(settings.HOURLY_PARQUET),
        "forecast": stat(settings.FORECAST_PARQUET),
        "dispatch": stat(settings.DISPATCH_PARQUET),
        "report": stat(settings.REPORT_JSON),
    }

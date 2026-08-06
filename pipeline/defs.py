"""Dagster 資產與排程：即時爬取 → 服務層 parquet → 警示物化。

資料流（每 10 分鐘跑一次整條）：

    realtime_snapshot   爬新北開放平台 → /data/raw/snap_<ts>.parquet
        ↓
    station_registry    新站併入 serving/stations.parquet
        ↓
    serving_snapshots   raw 合併去重 → serving/recent.parquet（30 分槽）
                        + serving/latest.parquet（每站最新，地圖用）
        ↓
    alerts_table        規則型三級警示 → serving/alerts.parquet

所有寫入都是「寫 .tmp → 原子 rename」，API 在讀的當下不會看到半成品。
"""
from datetime import datetime, timedelta
from pathlib import Path

import dagster as dg
from dagster import AssetExecutionContext
import duckdb

from api import settings
from pipeline import alerts as alerts_mod
from pipeline import crawl

RAW_DIR = settings.DATA_DIR / "raw"
RAW_KEEP_DAYS = 14          # raw 小檔保留天數（每天 144 檔）


def _con() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    con.execute("SET TimeZone='Asia/Taipei'")
    return con


def _raw_files(days: int = RAW_KEEP_DAYS) -> list[str]:
    cutoff = datetime.now() - timedelta(days=days)
    out = []
    for p in sorted(RAW_DIR.glob("snap_*.parquet")):
        try:
            ts = datetime.strptime(p.stem.removeprefix("snap_"), "%Y%m%dT%H%M")
        except ValueError:
            continue
        if ts >= cutoff:
            out.append(str(p))
    return out


def _sql_list(paths: list[str]) -> str:
    return "read_parquet([" + ", ".join(f"'{p}'" for p in paths) + "])"


def _atomic_copy(con: duckdb.DuckDBPyConnection, select_sql: str, target: Path) -> int:
    """把查詢結果寫成 parquet，寫完才 rename 就位。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    con.execute(
        f"COPY ({select_sql}) TO '{tmp}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    tmp.replace(target)
    return con.execute(f"SELECT count(*) FROM read_parquet('{target}')").fetchone()[0]


# ── 1. 即時爬取 ──────────────────────────────────────────────────────────
@dg.asset(
    group_name="realtime",
    description="新北市資料開放平台 YouBike2.0 即時快照（約 1,580 站）",
)
def realtime_snapshot(context: AssetExecutionContext) -> dg.MaterializeResult:
    path = crawl.run()
    con = _con()
    n, ts = con.execute(
        f"SELECT count(*), max(ts) FROM read_parquet('{path}')").fetchone()
    con.close()

    # 順手清掉過期的 raw 小檔
    cutoff = datetime.now() - timedelta(days=RAW_KEEP_DAYS)
    removed = 0
    for p in RAW_DIR.glob("snap_*.parquet"):
        try:
            t = datetime.strptime(p.stem.removeprefix("snap_"), "%Y%m%dT%H%M")
        except ValueError:
            continue
        if t < cutoff:
            p.unlink(missing_ok=True)
            removed += 1

    return dg.MaterializeResult(metadata={
        "檔案": str(path),
        "站數": n,
        "時間槽": str(ts),
        "清除過期檔": removed,
    })


# ── 2. 站點主檔（納入新站）───────────────────────────────────────────────
@dg.asset(
    deps=[realtime_snapshot],
    group_name="serving",
    description="站點主檔：歷史站 + 即時資料中出現的新站",
)
def station_registry(context: AssetExecutionContext) -> dg.MaterializeResult:
    raw = _raw_files(days=2)
    target = settings.STATIONS_PARQUET
    if not raw:
        return dg.MaterializeResult(metadata={"狀態": "無即時資料，略過"})

    con = _con()
    src = _sql_list(raw)
    if not target.exists():
        n = _atomic_copy(con, f"""
            SELECT station_id, name, any_value(district) AS district,
                   any_value(lon) AS lon, any_value(lat) AS lat,
                   max(docks_total)::INT AS capacity_docks,
                   min(ts) AS first_ts, max(ts) AS last_ts,
                   count(*)::BIGINT AS n_snapshots,
                   max(bikes) = 0 AS always_empty
            FROM {src} GROUP BY station_id, name ORDER BY station_id
        """, target)
        con.close()
        return dg.MaterializeResult(metadata={"站數": n, "狀態": "初次建立"})

    existing = f"read_parquet('{target}')"
    new_n = con.execute(f"""
        SELECT count(DISTINCT station_id) FROM {src}
        WHERE station_id NOT IN (SELECT station_id FROM {existing})
    """).fetchone()[0]

    if new_n == 0:
        n = con.execute(f"SELECT count(*) FROM {existing}").fetchone()[0]
        con.close()
        return dg.MaterializeResult(metadata={"站數": n, "新站": 0})

    n = _atomic_copy(con, f"""
        SELECT * FROM {existing}
        UNION ALL
        SELECT station_id, name, any_value(district) AS district,
               any_value(lon) AS lon, any_value(lat) AS lat,
               max(docks_total)::INT AS capacity_docks,
               min(ts) AS first_ts, max(ts) AS last_ts,
               count(*)::BIGINT AS n_snapshots,
               false AS always_empty
        FROM {src}
        WHERE station_id NOT IN (SELECT station_id FROM {existing})
        GROUP BY station_id, name
        ORDER BY station_id
    """, target)
    con.close()
    return dg.MaterializeResult(metadata={"站數": n, "新站": new_n})


# ── 3. 服務層快照 ────────────────────────────────────────────────────────
@dg.asset(
    deps=[station_registry],
    group_name="serving",
    description="raw 合併去重 → recent.parquet（接續歷史）+ latest.parquet（地圖）",
)
def serving_snapshots(context: AssetExecutionContext) -> dg.MaterializeResult:
    raw = _raw_files()
    if not raw:
        return dg.MaterializeResult(metadata={"狀態": "無即時資料，略過"})

    con = _con()
    src = _sql_list(raw)

    # recent：欄位與歷史月檔完全一致，API 可以直接和 history 一起 read_parquet
    n_recent = _atomic_copy(con, f"""
        SELECT station_id, ts,
               bikes::SMALLINT AS bikes,
               docks_avail::SMALLINT AS docks_avail,
               docks_total::SMALLINT AS docks_total
        FROM {src}
        QUALIFY row_number() OVER (PARTITION BY station_id, ts ORDER BY fetched_at DESC) = 1
        ORDER BY station_id, ts
    """, settings.SERVING_DIR / "recent.parquet")

    # latest：每站最新一筆（含站點屬性，地圖直接吃）
    n_latest = _atomic_copy(con, f"""
        SELECT station_id, ts,
               bikes::SMALLINT AS bikes,
               docks_avail::SMALLINT AS docks_avail,
               docks_total::SMALLINT AS docks_total,
               name, district, lon, lat, fetched_at
        FROM {src}
        QUALIFY row_number() OVER (PARTITION BY station_id ORDER BY fetched_at DESC) = 1
        ORDER BY station_id
    """, settings.LATEST_PARQUET)

    as_of = con.execute(
        f"SELECT max(ts), max(fetched_at) FROM read_parquet('{settings.LATEST_PARQUET}')"
    ).fetchone()
    con.close()
    return dg.MaterializeResult(metadata={
        "recent 筆數": n_recent,
        "latest 站數": n_latest,
        "資料時間": str(as_of[0]),
        "抓取時間": str(as_of[1]),
        "raw 檔數": len(raw),
    })


# ── 4. 警示物化 ──────────────────────────────────────────────────────────
@dg.asset(
    deps=[serving_snapshots],
    group_name="serving",
    description="規則型三級警示（WP4）→ alerts.parquet，API 直接讀",
)
def alerts_table(context: AssetExecutionContext) -> dg.MaterializeResult:
    st = settings.STATIONS_PARQUET
    recent = settings.SERVING_DIR / "recent.parquet"
    if not st.exists() or not recent.exists():
        return dg.MaterializeResult(metadata={"狀態": "資料未就緒，略過"})

    con = _con()
    sql = alerts_mod.alerts_sql(
        f"read_parquet('{recent}')", f"read_parquet('{st}')")
    n = _atomic_copy(con, sql, settings.ALERTS_PARQUET)
    by_level = dict(con.execute(
        f"SELECT level, count(*) FROM read_parquet('{settings.ALERTS_PARQUET}') "
        f"GROUP BY 1").fetchall())
    con.close()
    return dg.MaterializeResult(metadata={
        "警示總數": n,
        "嚴重": by_level.get("critical", 0),
        "警戒": by_level.get("warning", 0),
        "注意": by_level.get("notice", 0),
    })


# ── Job / Schedule ───────────────────────────────────────────────────────
realtime_job = dg.define_asset_job(
    "realtime_refresh",
    selection=dg.AssetSelection.groups("realtime", "serving"),
    description="即時爬取 → 服務層 parquet → 警示（每 10 分鐘）",
)

realtime_schedule = dg.ScheduleDefinition(
    name="realtime_every_10min",
    job=realtime_job,
    cron_schedule="*/10 * * * *",
    execution_timezone="Asia/Taipei",
    default_status=dg.DefaultScheduleStatus.RUNNING,
)

defs = dg.Definitions(
    assets=[realtime_snapshot, station_registry, serving_snapshots, alerts_table],
    jobs=[realtime_job],
    schedules=[realtime_schedule],
)

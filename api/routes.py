"""資料 API 路由（掛在 /api 之下）。

所有查詢都走 DuckDB in-memory 讀 parquet；parquet 不存在時回空集合而不是
500，讓前端能在資料引導完成前先渲染（degraded 模式）。

狀態分級（分析規劃 WP4）：
    注意 near_empty/near_full  可借 ≤ 2 或可還 ≤ 2
    警戒 empty/full            已空／已滿且持續 ≥ 30 分鐘
    嚴重 critical              持續 ≥ 60 分鐘
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from pipeline import alerts as alerts_mod

from . import db, settings

router = APIRouter()

NEAR_THRESHOLD = alerts_mod.NEAR_THRESHOLD   # 將空／將滿門檻（台）
WARN_MINUTES = alerts_mod.WARN_MINUTES       # 警戒：已空滿持續分鐘
CRIT_MINUTES = alerts_mod.CRIT_MINUTES       # 嚴重：已空滿持續分鐘


# ── parquet 來源組裝 ─────────────────────────────────────────────────────
def _snapshot_sources(months: int | None = None) -> list[str]:
    """歷史月檔 + 即時累積檔，回傳實際存在的路徑清單。"""
    hist = sorted(settings.HISTORY_DIR.glob("snapshots_*.parquet"))
    if months:
        hist = hist[-months:]
    recent = sorted(settings.SERVING_DIR.glob("recent*.parquet"))
    return [str(p) for p in hist + recent]


def _sql_sources(paths: list[str]) -> str:
    if not paths:
        return ""
    arr = ", ".join(f"'{p}'" for p in paths)
    return f"read_parquet([{arr}])"


def _stations_sql() -> str | None:
    p = settings.STATIONS_PARQUET
    return f"read_parquet('{p}')" if p.exists() else None


def _latest_sql() -> str | None:
    p = settings.LATEST_PARQUET
    return f"read_parquet('{p}')" if p.exists() else None


def _status_expr(bikes: str = "bikes", docks: str = "docks_avail",
                 total: str = "docks_total") -> str:
    """站點狀態五分類；有車柱卻既無車也無空位＝離線／維護中，不算空滿。"""
    return f"""
        CASE WHEN {total} IS NULL OR {total} = 0 THEN 'offline'
             WHEN {bikes} = 0 AND {docks} = 0 THEN 'offline'
             WHEN {bikes} = 0 THEN 'empty'
             WHEN {docks} = 0 THEN 'full'
             WHEN {bikes} <= {NEAR_THRESHOLD} THEN 'near_empty'
             WHEN {docks} <= {NEAR_THRESHOLD} THEN 'near_full'
             ELSE 'normal' END
    """


# ── 後設資料 ─────────────────────────────────────────────────────────────
@router.get("/meta")
def meta() -> dict:
    """資料涵蓋範圍與最後更新時間，前端頁首顯示用。"""
    out: dict = {"data": db.data_status()}
    lat = _latest_sql()
    if lat:
        out["realtime"] = db.query_one(
            f"SELECT max(ts) AS last_ts, max(fetched_at) AS fetched_at, "
            f"count(*) AS n_stations FROM {lat}"
        )
    src = _sql_sources(_snapshot_sources())
    if src:
        out["history"] = db.query_one(
            f"SELECT min(ts) AS first_ts, max(ts) AS last_ts, count(*) AS n_rows, "
            f"count(DISTINCT station_id) AS n_stations FROM {src}"
        )
    return out


# ── 站點 ─────────────────────────────────────────────────────────────────
@router.get("/stations")
def stations(
    district: str | None = None,
    status: str | None = None,
    include_inactive: bool = False,
) -> dict:
    """全站列表 + 最新狀態（地圖主要資料源）。"""
    st = _stations_sql()
    if not st:
        return {"as_of": None, "count": 0, "stations": []}

    lat = _latest_sql()
    if lat:
        sql = f"""
            SELECT s.station_id, s.name, s.district, s.lon, s.lat,
                   s.capacity_docks, s.always_empty,
                   l.ts, l.bikes, l.docks_avail, l.docks_total,
                   round(l.bikes / nullif(l.docks_total, 0), 4) AS occ_rate,
                   {_status_expr('l.bikes', 'l.docks_avail', 'l.docks_total')} AS status
            FROM {st} s LEFT JOIN {lat} l USING (station_id)
        """
    else:
        sql = f"""
            SELECT s.station_id, s.name, s.district, s.lon, s.lat,
                   s.capacity_docks, s.always_empty,
                   NULL::TIMESTAMP AS ts, NULL::SMALLINT AS bikes,
                   NULL::SMALLINT AS docks_avail, NULL::SMALLINT AS docks_total,
                   NULL::DOUBLE AS occ_rate, 'unknown' AS status
            FROM {st} s
        """

    where = []
    if not include_inactive:
        where.append("NOT coalesce(always_empty, false)")
    if district:
        where.append(f"district = '{district}'")
    sql = f"SELECT * FROM ({sql}) t" + (" WHERE " + " AND ".join(where) if where else "")
    if status:
        sql += f" AND status = '{status}'" if where else f" WHERE status = '{status}'"
    sql += " ORDER BY station_id"

    rows = db.query(sql)
    as_of = max((r["ts"] for r in rows if r["ts"]), default=None)
    return {"as_of": as_of, "count": len(rows), "stations": rows}


@router.get("/stations/{station_id}")
def station_detail(station_id: int) -> dict:
    st = _stations_sql()
    if not st:
        raise HTTPException(503, "站點主檔尚未就緒")
    row = db.query_one(f"SELECT * FROM {st} WHERE station_id = {station_id}")
    if not row:
        raise HTTPException(404, "查無此站")

    lat = _latest_sql()
    if lat:
        row["current"] = db.query_one(
            f"SELECT ts, bikes, docks_avail, docks_total, "
            f"{_status_expr()} AS status FROM {lat} WHERE station_id = {station_id}"
        )

    src = _sql_sources(_snapshot_sources())
    if src:
        row["stats"] = db.query_one(f"""
            SELECT count(*) AS n_snapshots,
                   round(avg(bikes), 2) AS bikes_mean,
                   round(avg(CASE WHEN bikes = 0 THEN 1 ELSE 0 END), 4) AS empty_rate,
                   round(avg(CASE WHEN docks_avail = 0 THEN 1 ELSE 0 END), 4) AS full_rate,
                   round(avg(bikes / nullif(docks_total, 0)), 4) AS occ_rate
            FROM {src} WHERE station_id = {station_id}
        """)
    return row


@router.get("/stations/{station_id}/history")
def station_history(
    station_id: int,
    days: int = Query(7, ge=1, le=180),
    end: str | None = None,
) -> dict:
    """單站歷史曲線（前端站點詳情圖）。end 省略則接到資料最尾端。"""
    src = _sql_sources(_snapshot_sources())
    if not src:
        return {"station_id": station_id, "points": []}

    if end:
        end_expr = f"TIMESTAMP '{end}'"
    else:
        end_expr = f"(SELECT max(ts) FROM {src})"

    rows = db.query(f"""
        SELECT ts, bikes, docks_avail, docks_total,
               round(bikes / nullif(docks_total, 0), 4) AS occ_rate
        FROM {src}
        WHERE station_id = {station_id}
          AND ts > {end_expr} - INTERVAL {days} DAY
          AND ts <= {end_expr}
        ORDER BY ts
    """)
    return {"station_id": station_id, "days": days, "count": len(rows), "points": rows}


# ── 歷史回放 ─────────────────────────────────────────────────────────────
@router.get("/replay")
def replay(ts: str = Query(..., description="ISO 時間，例：2026-06-15T08:00:00")) -> dict:
    """任一時刻的全市快照（時間軸拉桿）。"""
    src = _sql_sources(_snapshot_sources())
    st = _stations_sql()
    if not src or not st:
        return {"ts": ts, "count": 0, "stations": []}

    rows = db.query(f"""
        SELECT s.station_id, st.name, st.district, st.lon, st.lat,
               s.ts, s.bikes, s.docks_avail, s.docks_total,
               round(s.bikes / nullif(s.docks_total, 0), 4) AS occ_rate,
               {_status_expr('s.bikes', 's.docks_avail', 's.docks_total')} AS status
        FROM {src} s JOIN {st} st USING (station_id)
        WHERE s.ts = time_bucket(INTERVAL '30 minutes', TIMESTAMP '{ts}')
          AND NOT coalesce(st.always_empty, false)
        ORDER BY s.station_id
    """)
    return {"ts": ts, "count": len(rows), "stations": rows}


@router.get("/replay/days")
def replay_days() -> dict:
    """可回放的日期清單（前端日曆／下拉）。"""
    src = _sql_sources(_snapshot_sources())
    if not src:
        return {"days": []}
    rows = db.query(f"""
        SELECT CAST(ts AS DATE) AS day, count(*) AS n_rows,
               count(DISTINCT ts) AS n_slots
        FROM {src} GROUP BY 1 ORDER BY 1
    """)
    return {"count": len(rows), "days": rows}


# ── 統計 ─────────────────────────────────────────────────────────────────
@router.get("/stats/hourly")
def stats_hourly(station_id: int | None = None, district: str | None = None) -> dict:
    """站 × 星期 × 半小時槽 的歷史型態（熱力圖 / 基準線）。"""
    p = settings.HOURLY_PARQUET
    if not p.exists():
        return {"rows": []}
    src = f"read_parquet('{p}')"
    st = _stations_sql()

    if station_id is not None:
        rows = db.query(f"""
            SELECT isodow, slot, n, bikes_p10, bikes_p50, bikes_p90, bikes_mean,
                   empty_rate, full_rate, occ_rate
            FROM {src} WHERE station_id = {station_id} ORDER BY isodow, slot
        """)
        return {"station_id": station_id, "rows": rows}

    join = ""
    where = ""
    if district and st:
        join = f"JOIN {st} s USING (station_id)"
        where = f"WHERE s.district = '{district}'"

    rows = db.query(f"""
        SELECT h.isodow, h.slot,
               round(sum(h.empty_rate * h.n) / sum(h.n), 4) AS empty_rate,
               round(sum(h.full_rate  * h.n) / sum(h.n), 4) AS full_rate,
               round(sum(h.occ_rate   * h.n) / sum(h.n), 4) AS occ_rate,
               sum(h.n)::BIGINT AS n
        FROM {src} h {join} {where}
        GROUP BY 1, 2 ORDER BY 1, 2
    """)
    return {"district": district, "rows": rows}


@router.get("/stats/pulse")
def stats_pulse(date: str | None = None) -> dict:
    """某一天全市各時間槽的空／滿站數（首頁脈搏帶、回放時間軸的底圖）。

    date 省略則取資料最後一天。
    """
    src = _sql_sources(_snapshot_sources())
    st = _stations_sql()
    if not src or not st:
        return {"date": date, "points": []}

    if date:
        day_expr = f"DATE '{date}'"
    else:
        day_expr = f"(SELECT CAST(max(ts) AS DATE) FROM {src})"

    rows = db.query(f"""
        SELECT sn.ts,
               (EXTRACT(hour FROM sn.ts) * 2
                + (EXTRACT(minute FROM sn.ts) >= 30)::INT)::TINYINT AS slot,
               count(*)::INT AS n_stations,
               sum(CASE WHEN sn.bikes = 0 AND sn.docks_avail > 0
                        THEN 1 ELSE 0 END)::INT AS n_empty,
               sum(CASE WHEN sn.docks_avail = 0 AND sn.bikes > 0
                        THEN 1 ELSE 0 END)::INT AS n_full,
               sum(CASE WHEN (sn.bikes <= {NEAR_THRESHOLD} OR sn.docks_avail <= {NEAR_THRESHOLD})
                        AND NOT (sn.bikes = 0 AND sn.docks_avail = 0)
                        THEN 1 ELSE 0 END)::INT AS n_risk,
               sum(sn.bikes)::INT AS bikes,
               round(sum(sn.bikes) / nullif(sum(sn.docks_total), 0), 4) AS occ_rate
        FROM {src} sn JOIN {st} s USING (station_id)
        WHERE CAST(sn.ts AS DATE) = {day_expr}
          AND NOT coalesce(s.always_empty, false)
        GROUP BY 1, 2 ORDER BY 1
    """)
    day = rows[0]["ts"].date().isoformat() if rows else date
    return {"date": day, "count": len(rows), "points": rows}


@router.get("/stats/districts")
def stats_districts() -> dict:
    """行政區彙總（管理視角）。"""
    st = _stations_sql()
    lat = _latest_sql()
    if not st:
        return {"districts": []}
    if not lat:
        rows = db.query(f"""
            SELECT district, count(*) AS n_stations, sum(capacity_docks) AS capacity
            FROM {st} WHERE NOT coalesce(always_empty, false)
            GROUP BY 1 ORDER BY 2 DESC
        """)
        return {"districts": rows}

    rows = db.query(f"""
        SELECT s.district,
               count(*)::INT                              AS n_stations,
               sum(l.docks_total)::INT                    AS docks_total,
               sum(l.bikes)::INT                          AS bikes,
               sum(l.docks_avail)::INT                    AS docks_avail,
               round(sum(l.bikes) / nullif(sum(l.docks_total), 0), 4) AS occ_rate,
               sum(CASE WHEN l.bikes = 0 AND l.docks_avail > 0
                        THEN 1 ELSE 0 END)::INT                        AS n_empty,
               sum(CASE WHEN l.docks_avail = 0 AND l.bikes > 0
                        THEN 1 ELSE 0 END)::INT                        AS n_full,
               sum(CASE WHEN l.bikes = 0 AND l.docks_avail = 0
                        THEN 1 ELSE 0 END)::INT                        AS n_offline,
               sum(CASE WHEN l.bikes <= {NEAR_THRESHOLD} AND l.bikes > 0
                        THEN 1 ELSE 0 END)::INT                        AS n_near_empty,
               sum(CASE WHEN l.docks_avail <= {NEAR_THRESHOLD} AND l.docks_avail > 0
                        THEN 1 ELSE 0 END)::INT                        AS n_near_full
        FROM {st} s JOIN {lat} l USING (station_id)
        WHERE NOT coalesce(s.always_empty, false) AND s.district IS NOT NULL
        GROUP BY 1 ORDER BY n_empty + n_full DESC, n_stations DESC
    """)
    return {"count": len(rows), "districts": rows}


@router.get("/stats/overview")
def stats_overview() -> dict:
    """首頁 KPI：現況 + 歷史痛點數字。"""
    out: dict = {}
    st, lat = _stations_sql(), _latest_sql()
    if st and lat:
        out["now"] = db.query_one(f"""
            SELECT max(l.ts) AS as_of,
                   count(*)::INT AS n_stations,
                   sum(l.bikes)::INT AS bikes,
                   sum(l.docks_total)::INT AS docks_total,
                   round(sum(l.bikes) / nullif(sum(l.docks_total), 0), 4) AS occ_rate,
                   sum(CASE WHEN l.bikes = 0 AND l.docks_avail > 0
                            THEN 1 ELSE 0 END)::INT                        AS n_empty,
                   sum(CASE WHEN l.docks_avail = 0 AND l.bikes > 0
                            THEN 1 ELSE 0 END)::INT                        AS n_full,
                   sum(CASE WHEN l.bikes = 0 AND l.docks_avail = 0
                            THEN 1 ELSE 0 END)::INT                        AS n_offline,
                   sum(CASE WHEN (l.bikes <= {NEAR_THRESHOLD} OR l.docks_avail <= {NEAR_THRESHOLD})
                            AND NOT (l.bikes = 0 AND l.docks_avail = 0)
                            THEN 1 ELSE 0 END)::INT                        AS n_risk
            FROM {st} s JOIN {lat} l USING (station_id)
            WHERE NOT coalesce(s.always_empty, false)
        """)

    src = _sql_sources(_snapshot_sources())
    if src and st:
        out["history"] = db.query_one(f"""
            SELECT min(sn.ts) AS first_ts, max(sn.ts) AS last_ts,
                   count(*)::BIGINT AS n_rows,
                   count(DISTINCT sn.station_id)::INT AS n_stations,
                   round(avg(CASE WHEN sn.bikes = 0 THEN 1 ELSE 0 END), 4)       AS empty_rate,
                   round(avg(CASE WHEN sn.docks_avail = 0 THEN 1 ELSE 0 END), 4) AS full_rate
            FROM {src} sn JOIN {st} s USING (station_id)
            WHERE NOT coalesce(s.always_empty, false)
        """)
    return out


@router.get("/stats/worst")
def stats_worst(limit: int = Query(20, ge=1, le=200), metric: str = "empty") -> dict:
    """歷史最常空／滿的站點排行（痛點佐證）。"""
    src = _sql_sources(_snapshot_sources())
    st = _stations_sql()
    if not src or not st:
        return {"rows": []}
    col = "empty_rate" if metric == "empty" else "full_rate"
    rows = db.query(f"""
        SELECT sn.station_id, s.name, s.district, s.capacity_docks,
               count(*)::BIGINT AS n,
               round(avg(CASE WHEN sn.bikes = 0 THEN 1 ELSE 0 END), 4)       AS empty_rate,
               round(avg(CASE WHEN sn.docks_avail = 0 THEN 1 ELSE 0 END), 4) AS full_rate
        FROM {src} sn JOIN {st} s USING (station_id)
        WHERE NOT coalesce(s.always_empty, false)
        GROUP BY 1, 2, 3, 4
        HAVING count(*) > 100
        ORDER BY {col} DESC
        LIMIT {limit}
    """)
    return {"metric": metric, "count": len(rows), "rows": rows}


# ── 警示 ─────────────────────────────────────────────────────────────────
@router.get("/alerts")
def alerts(level: str | None = None, district: str | None = None) -> dict:
    """規則型警示（WP4）。

    以最新快照為基準往回看 6 小時，算出目前空／滿已持續多久，套三級門檻。
    pipeline 若已物化 alerts.parquet 就直接讀（省算），否則即時計算。
    """
    if settings.ALERTS_PARQUET.exists():
        src = f"read_parquet('{settings.ALERTS_PARQUET}')"
        where = []
        if level:
            where.append(f"level = '{level}'")
        if district:
            where.append(f"district = '{district}'")
        sql = f"SELECT * FROM {src}"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY CASE level WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, duration_min DESC"
        rows = db.query(sql)
        return {"source": "pipeline", "count": len(rows), "alerts": rows}

    rows = _compute_alerts(level, district)
    return {"source": "live", "count": len(rows), "alerts": rows}


def _compute_alerts(level: str | None, district: str | None) -> list[dict]:
    src = _sql_sources(_snapshot_sources(months=1))
    st = _stations_sql()
    if not src or not st:
        return []

    rows = db.query(alerts_mod.alerts_sql(src, st))
    if district:
        rows = [r for r in rows if r["district"] == district]
    if level:
        rows = [r for r in rows if r["level"] == level]
    return rows

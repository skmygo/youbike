"""規則型警示計算（WP4），API 與 Dagster 共用同一套 SQL。

分級（分析規劃 WP4）：
    notice   注意  可借 ≤ 2 或可還 ≤ 2（將空／將滿）
    warning  警戒  已空／已滿，且持續 ≥ 30 分鐘（1 個快照週期）
    critical 嚴重  持續 ≥ 60 分鐘

持續時間 = 目前狀態往回追到「最後一次不是該狀態」的時間差。若整個 6 小時
觀察窗內都是該狀態，就用「窗內可觀察到的最早時間」當起點並標記
`duration_capped`，避免在資料剛開始累積時謊報 6 小時。
"""
from __future__ import annotations

NEAR_THRESHOLD = 2
WARN_MINUTES = 30
CRIT_MINUTES = 60
WINDOW_HOURS = 6


def alerts_sql(snapshots_sql: str, stations_sql: str) -> str:
    """組出警示查詢。

    snapshots_sql / stations_sql 是可直接放進 FROM 的片段
    （例如 `read_parquet(['a.parquet','b.parquet'])`）。
    """
    return f"""
    WITH src AS (
        SELECT station_id, ts, bikes, docks_avail, docks_total FROM {snapshots_sql}
    ),
    win AS (
        SELECT * FROM src
        WHERE ts > (SELECT max(ts) FROM src) - INTERVAL {WINDOW_HOURS} HOUR
          AND docks_total > 0            -- docks_total = 0 是無效站，不進警示
          -- 有車柱卻既無車也無空位＝該站離線／維護中，不是調度問題
          AND NOT (bikes = 0 AND docks_avail = 0)
    ),
    cur AS (
        SELECT * FROM win WHERE ts = (SELECT max(ts) FROM win)
    ),
    obs AS (                              -- 各站在觀察窗內最早可見的時間
        SELECT station_id, min(ts) AS since FROM win GROUP BY 1
    ),
    dur AS (
        SELECT c.station_id,
               CASE WHEN c.bikes = 0 THEN 'empty' ELSE 'full' END AS kind,
               c.ts, c.bikes, c.docks_avail, c.docks_total,
               (SELECT max(w.ts) FROM win w
                 WHERE w.station_id = c.station_id AND w.ts < c.ts
                   AND NOT (CASE WHEN c.bikes = 0 THEN w.bikes = 0
                                 ELSE w.docks_avail = 0 END)) AS last_ok_ts,
               o.since
        FROM cur c JOIN obs o USING (station_id)
        WHERE c.bikes = 0 OR c.docks_avail = 0
    ),
    dur2 AS (
        SELECT station_id, kind, ts, bikes, docks_avail, docks_total,
               CASE WHEN last_ok_ts IS NOT NULL
                    THEN date_diff('minute', last_ok_ts, ts)
                    ELSE date_diff('minute', since, ts) END AS duration_min,
               last_ok_ts IS NULL AS duration_capped
        FROM dur
    ),
    near AS (
        SELECT c.station_id,
               CASE WHEN c.bikes <= {NEAR_THRESHOLD} THEN 'near_empty'
                    ELSE 'near_full' END AS kind,
               c.ts, c.bikes, c.docks_avail, c.docks_total,
               0 AS duration_min, false AS duration_capped
        FROM cur c
        WHERE c.bikes > 0 AND c.docks_avail > 0
          AND (c.bikes <= {NEAR_THRESHOLD} OR c.docks_avail <= {NEAR_THRESHOLD})
    ),
    merged AS (SELECT * FROM dur2 UNION ALL SELECT * FROM near)
    SELECT m.station_id, s.name, s.district, s.lon, s.lat, s.capacity_docks,
           m.ts, m.bikes, m.docks_avail, m.docks_total,
           m.kind, m.duration_min::INT AS duration_min, m.duration_capped,
           CASE
             WHEN m.kind IN ('empty', 'full') AND m.duration_min >= {CRIT_MINUTES} THEN 'critical'
             WHEN m.kind IN ('empty', 'full') THEN 'warning'
             ELSE 'notice'
           END AS level
    FROM merged m JOIN {stations_sql} s USING (station_id)
    WHERE NOT coalesce(s.always_empty, false)
    ORDER BY CASE level WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
             m.duration_min DESC, m.station_id
    """

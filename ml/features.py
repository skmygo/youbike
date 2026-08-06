"""M4 特徵庫：用 DuckDB 從 6 個月歷史快照建 (station, ts) 特徵表 + 多 horizon 目標。

設計要點
- **完整時間網格**：先 CROSS JOIN 站點 × 30 分槽（限站點存活期），再 LEFT JOIN 快照，
  這樣 LAG/LEAD 的 offset 精確等於時間位移，缺槽自然變 NULL，不會把「跳過的槽」當相鄰。
- **無未來洩漏**：所有統計量（歷史常態、站點分群、假日偵測）只用訓練期（1–4 月）算。
- **中間表落 DuckDB 檔**（`_out/ml/work.duckdb`，本機訓練專用，不與 API/dagster 共用）→
  避免一個巨大 query 撐爆 14GB 記憶體。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import duckdb
import numpy as np

from ml.config import (
    EMPTY_BIKES_MAX,
    FULL_DOCKS_MAX,
    HISTORY_GLOB,
    HORIZONS,
    ML_DIR,
    N_CLUSTERS,
    STATIONS_PARQUET,
    TEST_RANGE,
    TRAIN_RANGE,
    VALID_RANGE,
    horizon_steps,
)

WORK_DB = ML_DIR / "work.duckdb"
N_NEIGHBORS = 5
NEIGHBOR_RADIUS_KM = 1.0


def _log(msg: str) -> None:
    print(f"[features] {time.strftime('%H:%M:%S')} {msg}", flush=True)


def connect(memory_limit: str = "3GB", threads: int = 3) -> duckdb.DuckDBPyConnection:
    ML_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(WORK_DB))
    con.execute(f"SET memory_limit='{memory_limit}'")
    con.execute(f"SET threads={threads}")
    con.execute(f"SET temp_directory='{ML_DIR / 'duckdb_tmp'}'")
    con.execute("SET preserve_insertion_order=false")
    return con


# --------------------------------------------------------------------------- 基底

def build_base(con: duckdb.DuckDBPyConnection) -> None:
    """站點清單 + 完整時間網格 + 觀測值（ratio）。"""
    _log("建立 stations_ml…")
    con.execute("DROP TABLE IF EXISTS stations_ml")
    con.execute(
        f"""
        CREATE TABLE stations_ml AS
        WITH base AS (
            SELECT station_id, name, district, lon, lat,
                   capacity_docks::INT AS capacity, first_ts, last_ts, n_snapshots
            FROM read_parquet('{STATIONS_PARQUET}')
            WHERE capacity_docks > 0
              AND NOT always_empty
              AND n_snapshots >= 1000          -- 有足夠歷史才進模型
        ), dcode AS (
            SELECT district, (dense_rank() OVER (ORDER BY district) - 1)::INT AS district_id
            FROM (SELECT DISTINCT district FROM base)
        )
        SELECT b.*, d.district_id FROM base b JOIN dcode d USING (district)
        """
    )
    n = con.execute("SELECT count(*) FROM stations_ml").fetchone()[0]
    _log(f"stations_ml: {n} 站")

    _log("建立 obs（原始快照，只留有效站）…")
    con.execute("DROP TABLE IF EXISTS obs")
    con.execute(
        f"""
        CREATE TABLE obs AS
        SELECT s.station_id, s.ts, s.bikes::INT AS bikes,
               s.docks_avail::INT AS docks_avail, s.docks_total::INT AS docks_total,
               s.bikes::DOUBLE / s.docks_total AS ratio
        FROM read_parquet('{HISTORY_GLOB}') s
        JOIN stations_ml m USING (station_id)
        WHERE s.docks_total > 0
          -- 離線站：有車柱卻既無車也無空位 → 不是真實狀態，排除
          AND NOT (s.bikes = 0 AND s.docks_avail = 0)
        """
    )
    _log(f"obs: {con.execute('SELECT count(*) FROM obs').fetchone()[0]:,} 筆")

    _log("建立完整時間網格 grid…")
    con.execute("DROP TABLE IF EXISTS grid")
    con.execute(
        """
        CREATE TABLE grid AS
        WITH slots AS (
            SELECT unnest(generate_series(
                (SELECT min(ts) FROM obs),
                (SELECT max(ts) FROM obs),
                INTERVAL 30 MINUTE)) AS ts
        ),
        span AS (
            SELECT m.station_id, m.capacity, m.lat, m.lon, m.district,
                   min(o.ts) AS t0, max(o.ts) AS t1
            FROM stations_ml m JOIN obs o USING (station_id)
            GROUP BY 1,2,3,4,5
        )
        SELECT sp.station_id, sl.ts,
               o.bikes, o.docks_avail, o.docks_total, o.ratio
        FROM span sp
        JOIN slots sl ON sl.ts BETWEEN sp.t0 AND sp.t1
        LEFT JOIN obs o ON o.station_id = sp.station_id AND o.ts = sl.ts
        """
    )
    _log(f"grid: {con.execute('SELECT count(*) FROM grid').fetchone()[0]:,} 列")


# ------------------------------------------------------------------- 訓練期統計量

def detect_holidays(con: duckdb.DuckDBPyConnection) -> list[str]:
    """從資料自己認假日：平日中「日內使用輪廓」比較像週末的那些天。

    比硬編行事曆誠實，也能抓到補假/颱風假。關鍵是**用局部基準**（前後 ±21 天的平日/週末
    原型）比對，否則冬季整體騎乘少、輪廓本來就平，1–2 月會被整片誤判成假日。
    """
    _log("偵測假日（資料驅動，局部基準）…")
    df = con.execute(
        """
        SELECT CAST(ts AS DATE) AS d, hour(ts) AS h, avg(ratio) AS r
        FROM grid WHERE ratio IS NOT NULL GROUP BY 1,2 ORDER BY 1,2
        """
    ).df()
    piv = df.pivot(index="d", columns="h", values="r").dropna()
    # 標準化每天的輪廓（只看形狀，不看水位）
    X = piv.to_numpy()
    X = (X - X.mean(axis=1, keepdims=True)) / (X.std(axis=1, keepdims=True) + 1e-9)
    dates = list(piv.index)
    dow = np.array([d.weekday() for d in dates])
    idx = np.arange(len(dates))
    day_num = np.array([(d - dates[0]).days for d in dates])
    WINDOW = 21

    holidays: list[str] = []
    for i in idx:
        if dow[i] >= 5:
            continue
        near = np.abs(day_num - day_num[i]) <= WINDOW
        wk_end = near & (dow >= 5)
        wk_day = near & (dow < 5) & (idx != i)
        if wk_end.sum() < 4 or wk_day.sum() < 8:
            continue
        d_end = float(np.linalg.norm(X[i] - X[wk_end].mean(axis=0)))
        d_day = float(np.linalg.norm(X[i] - X[wk_day].mean(axis=0)))
        if d_end < d_day:
            holidays.append(str(dates[i]))
    _log(f"偵測到 {len(holidays)} 個平日假期：{holidays}")
    (ML_DIR / "holidays.json").write_text(
        json.dumps(holidays, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    con.execute("DROP TABLE IF EXISTS holidays")
    con.execute("CREATE TABLE holidays(d DATE)")
    if holidays:
        con.executemany("INSERT INTO holidays VALUES (?)", [(h,) for h in holidays])
    return holidays


def build_clusters(con: duckdb.DuckDBPyConnection) -> None:
    """站點行為分群：以訓練期「平日/週末 × 小時」的平均 ratio 輪廓做 k-means。"""
    _log("站點行為分群 k-means…")
    from sklearn.cluster import KMeans

    df = con.execute(
        f"""
        SELECT station_id,
               (CASE WHEN dayofweek(ts) IN (0,6) THEN 24 ELSE 0 END) + hour(ts) AS col,
               avg(ratio) AS r
        FROM grid
        WHERE ratio IS NOT NULL AND ts < TIMESTAMP '{TRAIN_RANGE[1]} 23:59:59'
        GROUP BY 1,2
        """
    ).df()
    piv = df.pivot(index="station_id", columns="col", values="r")
    piv = piv.reindex(columns=range(48)).interpolate(axis=1).bfill(axis=1).ffill(axis=1)
    piv = piv.fillna(piv.mean().mean())
    X = piv.to_numpy()
    # 只看輪廓形狀（水位另有 norm_ratio 特徵承載）
    Xs = (X - X.mean(axis=1, keepdims=True)) / (X.std(axis=1, keepdims=True) + 1e-9)
    km = KMeans(n_clusters=N_CLUSTERS, n_init=10, random_state=42).fit(Xs)
    out = piv.reset_index()[["station_id"]].copy()
    out["cluster_id"] = km.labels_.astype("int32")
    con.execute("DROP TABLE IF EXISTS clusters")
    con.register("clusters_df", out)
    con.execute("CREATE TABLE clusters AS SELECT * FROM clusters_df")
    con.unregister("clusters_df")
    sizes = out.groupby("cluster_id").size().to_dict()
    _log(f"cluster 大小：{sizes}")


def build_norms(con: duckdb.DuckDBPyConnection) -> None:
    """歷史常態：station × dow × slot 的平均 ratio / 空率 / 滿率（僅訓練期）。"""
    _log("建立歷史常態 norms（僅訓練期）…")
    con.execute("DROP TABLE IF EXISTS norms")
    con.execute(
        f"""
        CREATE TABLE norms AS
        SELECT station_id,
               dayofweek(ts) AS dow,
               (hour(ts) * 2 + (minute(ts) / 30)::INT) AS slot_of_day,
               avg(ratio) AS norm_ratio,
               avg(CASE WHEN bikes <= {EMPTY_BIKES_MAX} THEN 1.0 ELSE 0.0 END) AS norm_empty_rate,
               avg(CASE WHEN docks_avail <= {FULL_DOCKS_MAX} THEN 1.0 ELSE 0.0 END) AS norm_full_rate
        FROM grid
        WHERE ratio IS NOT NULL AND ts <= TIMESTAMP '{TRAIN_RANGE[1]} 23:59:59'
        GROUP BY 1,2,3
        """
    )
    _log(f"norms: {con.execute('SELECT count(*) FROM norms').fetchone()[0]:,} 列")


def build_neighbors(con: duckdb.DuckDBPyConnection) -> None:
    """每站最近 N 個鄰居（1km 內），與逐槽鄰域平均 ratio。"""
    _log("計算鄰近站…")
    con.execute("DROP TABLE IF EXISTS neighbors")
    con.execute(
        f"""
        CREATE TABLE neighbors AS
        WITH pairs AS (
            SELECT a.station_id, b.station_id AS neighbor_id,
                   111.0 * sqrt(pow(a.lat - b.lat, 2)
                        + pow((a.lon - b.lon) * cos(radians(a.lat)), 2)) AS km
            FROM stations_ml a JOIN stations_ml b ON a.station_id <> b.station_id
        ), ranked AS (
            SELECT *, row_number() OVER (PARTITION BY station_id ORDER BY km) AS rn
            FROM pairs WHERE km <= {NEIGHBOR_RADIUS_KM}
        )
        SELECT station_id, neighbor_id, km FROM ranked WHERE rn <= {N_NEIGHBORS}
        """
    )
    _log(f"neighbors: {con.execute('SELECT count(*) FROM neighbors').fetchone()[0]:,} 對")

    _log("彙總鄰域 / 行政區 / 分群的逐槽水位…")
    con.execute("DROP TABLE IF EXISTS neigh_agg")
    con.execute(
        """
        CREATE TABLE neigh_agg AS
        SELECT n.station_id, g.ts, avg(g.ratio) AS neigh_ratio, count(*) AS neigh_n
        FROM neighbors n
        JOIN grid g ON g.station_id = n.neighbor_id
        WHERE g.ratio IS NOT NULL
        GROUP BY 1,2
        """
    )
    con.execute("DROP TABLE IF EXISTS group_agg")
    con.execute(
        """
        CREATE TABLE group_agg AS
        SELECT s.district, c.cluster_id, g.ts,
               avg(g.ratio) AS ratio, count(*) AS n
        FROM grid g
        JOIN stations_ml s USING (station_id)
        JOIN clusters c USING (station_id)
        WHERE g.ratio IS NOT NULL
        GROUP BY 1,2,3
        """
    )
    con.execute("DROP TABLE IF EXISTS district_agg")
    con.execute(
        """
        CREATE TABLE district_agg AS
        SELECT district, ts, sum(ratio * n) / sum(n) AS district_ratio
        FROM group_agg GROUP BY 1,2
        """
    )
    con.execute("DROP TABLE IF EXISTS cluster_agg")
    con.execute(
        """
        CREATE TABLE cluster_agg AS
        SELECT cluster_id, ts, sum(ratio * n) / sum(n) AS cluster_ratio
        FROM group_agg GROUP BY 1,2
        """
    )
    _log("彙總完成")


# ------------------------------------------------------------------------ 特徵表

def build_features(con: duckdb.DuckDBPyConnection) -> None:
    """lag / rolling / 時間 / 靜態 / 常態 / 鄰域 + 多 horizon 目標 → features 表。"""
    _log("組裝特徵表 features…")
    lead_cols = []
    for h in HORIZONS:
        k = horizon_steps(h)
        lead_cols.append(
            f"LEAD(ratio, {k}) OVER w AS y_ratio_{h}, "
            f"LEAD(bikes, {k}) OVER w AS y_bikes_{h}, "
            f"LEAD(docks_avail, {k}) OVER w AS y_docks_{h}, "
            # baseline B：上週同日同時段「目標時刻」的水位（t+h-7d）
            f"LAG(ratio, {336 - k}) OVER w AS bl_lastweek_{h}"
        )
    leads = ",\n               ".join(lead_cols)

    con.execute("DROP TABLE IF EXISTS features")
    con.execute(
        f"""
        CREATE TABLE features AS
        WITH w AS (
            SELECT station_id, ts, bikes, docks_avail, docks_total, ratio,
                   LAG(ratio, 1)   OVER w AS ratio_lag1,
                   LAG(ratio, 2)   OVER w AS ratio_lag2,
                   LAG(ratio, 3)   OVER w AS ratio_lag3,
                   LAG(ratio, 4)   OVER w AS ratio_lag4,
                   LAG(ratio, 6)   OVER w AS ratio_lag6,
                   LAG(ratio, 12)  OVER w AS ratio_lag12,
                   LAG(ratio, 24)  OVER w AS ratio_lag24,
                   LAG(ratio, 48)  OVER w AS ratio_lag48,
                   LAG(ratio, 336) OVER w AS ratio_lag336,
                   avg(ratio) OVER (PARTITION BY station_id ORDER BY ts
                        ROWS BETWEEN 3 PRECEDING AND CURRENT ROW) AS roll_mean_4,
                   stddev_samp(ratio) OVER (PARTITION BY station_id ORDER BY ts
                        ROWS BETWEEN 3 PRECEDING AND CURRENT ROW) AS roll_std_4,
                   avg(ratio) OVER (PARTITION BY station_id ORDER BY ts
                        ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) AS roll_mean_12,
                   stddev_samp(ratio) OVER (PARTITION BY station_id ORDER BY ts
                        ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) AS roll_std_12,
                   avg(ratio) OVER (PARTITION BY station_id ORDER BY ts
                        ROWS BETWEEN 47 PRECEDING AND CURRENT ROW) AS roll_mean_48,
                   min(ratio) OVER (PARTITION BY station_id ORDER BY ts
                        ROWS BETWEEN 47 PRECEDING AND CURRENT ROW) AS roll_min_48,
                   max(ratio) OVER (PARTITION BY station_id ORDER BY ts
                        ROWS BETWEEN 47 PRECEDING AND CURRENT ROW) AS roll_max_48,
                   sum(CASE WHEN bikes <= {EMPTY_BIKES_MAX} THEN 1 ELSE 0 END) OVER (
                        PARTITION BY station_id ORDER BY ts
                        ROWS BETWEEN 5 PRECEDING AND CURRENT ROW) AS empty_streak,
                   sum(CASE WHEN docks_avail <= {FULL_DOCKS_MAX} THEN 1 ELSE 0 END) OVER (
                        PARTITION BY station_id ORDER BY ts
                        ROWS BETWEEN 5 PRECEDING AND CURRENT ROW) AS full_streak,
               {leads}
            FROM grid
            WINDOW w AS (PARTITION BY station_id ORDER BY ts)
        )
        SELECT
            w.station_id, w.ts,
            w.ratio, w.bikes, w.docks_total,
            w.ratio_lag1, w.ratio_lag2, w.ratio_lag3, w.ratio_lag4, w.ratio_lag6,
            w.ratio_lag12, w.ratio_lag24, w.ratio_lag48, w.ratio_lag336,
            w.ratio - w.ratio_lag1 AS d1,
            w.ratio - w.ratio_lag2 AS d2,
            w.ratio - w.ratio_lag4 AS d4,
            w.roll_mean_4, w.roll_std_4, w.roll_mean_12, w.roll_std_12,
            w.roll_mean_48, w.roll_min_48, w.roll_max_48,
            w.empty_streak::INT AS empty_streak,
            w.full_streak::INT AS full_streak,
            (hour(w.ts) * 2 + (minute(w.ts) / 30)::INT) AS slot_of_day,
            dayofweek(w.ts) AS dow,
            (CASE WHEN dayofweek(w.ts) IN (0,6) THEN 1 ELSE 0 END) AS is_weekend,
            (CASE WHEN h.d IS NOT NULL THEN 1 ELSE 0 END) AS is_holiday,
            (hour(w.ts) * 60 + minute(w.ts)) AS minutes_since_midnight,
            s.capacity, s.lat, s.lon,
            c.cluster_id, s.district_id,
            n.norm_ratio, w.ratio - n.norm_ratio AS norm_dev,
            n.norm_empty_rate, n.norm_full_rate,
            da.district_ratio,
            ca.cluster_ratio,
            na.neigh_ratio, na.neigh_ratio - da.district_ratio AS neigh_dev,
            {", ".join(f"w.y_ratio_{h}, w.y_bikes_{h}, w.y_docks_{h}, w.bl_lastweek_{h}" for h in HORIZONS)}
        FROM w
        JOIN stations_ml s USING (station_id)
        JOIN clusters c USING (station_id)
        LEFT JOIN norms n ON n.station_id = w.station_id
             AND n.dow = dayofweek(w.ts)
             AND n.slot_of_day = (hour(w.ts) * 2 + (minute(w.ts) / 30)::INT)
        LEFT JOIN district_agg da ON da.district = s.district AND da.ts = w.ts
        LEFT JOIN cluster_agg ca ON ca.cluster_id = c.cluster_id AND ca.ts = w.ts
        LEFT JOIN neigh_agg na ON na.station_id = w.station_id AND na.ts = w.ts
        LEFT JOIN holidays h ON h.d = CAST(w.ts AS DATE)
        WHERE w.ratio IS NOT NULL
        """
    )
    _log(f"features: {con.execute('SELECT count(*) FROM features').fetchone()[0]:,} 列")


def export_splits(con: duckdb.DuckDBPyConnection) -> dict:
    """依時間序切成 train/valid/test parquet（不洗牌）。"""
    stats = {}
    for name, (a, b) in (
        ("train", TRAIN_RANGE),
        ("valid", VALID_RANGE),
        ("test", TEST_RANGE),
    ):
        out = ML_DIR / f"features_{name}.parquet"
        # 目標齊全才留（最長 horizon 也要有答案），否則評估會混入不同樣本數
        cond = " AND ".join(f"y_ratio_{h} IS NOT NULL" for h in HORIZONS)
        con.execute(
            f"""
            COPY (
                SELECT * FROM features
                WHERE ts >= TIMESTAMP '{a} 00:00:00' AND ts <= TIMESTAMP '{b} 23:59:59'
                  AND {cond}
                ORDER BY ts, station_id
            ) TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)
            """
        )
        n = con.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchone()[0]
        stats[name] = {"rows": int(n), "path": str(out), "range": [a, b]}
        _log(f"{name}: {n:,} 列 → {out}")
    (ML_DIR / "splits.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    return stats


def export_serving_tables(con: duckdb.DuckDBPyConnection) -> None:
    """M5 線上預測要的輔助表：站點靜態（含 cluster/district_id）、歷史常態、鄰居表。

    這幾張表隨模型一起上 S3，容器啟動時拉下來；線上只做特徵組裝，不重算統計。
    """
    _log("匯出 serving 輔助表…")
    serving = ML_DIR / "serving"
    serving.mkdir(parents=True, exist_ok=True)
    con.execute(
        f"COPY (SELECT m.station_id, m.name, m.district, m.district_id, m.lon, m.lat, "
        f"       m.capacity, c.cluster_id "
        f"      FROM stations_ml m JOIN clusters c USING (station_id)) "
        f"TO '{serving / 'ml_stations.parquet'}' (FORMAT PARQUET)"
    )
    con.execute(f"COPY norms TO '{serving / 'ml_norms.parquet'}' (FORMAT PARQUET)")
    con.execute(f"COPY neighbors TO '{serving / 'ml_neighbors.parquet'}' (FORMAT PARQUET)")
    con.execute(f"COPY holidays TO '{serving / 'ml_holidays.parquet'}' (FORMAT PARQUET)")
    _log(f"serving 輔助表 → {serving}")


def main() -> None:
    t0 = time.time()
    con = connect()
    build_base(con)
    detect_holidays(con)
    build_clusters(con)
    build_norms(con)
    build_neighbors(con)
    build_features(con)
    stats = export_splits(con)
    export_serving_tables(con)
    con.close()
    _log(f"完成，耗時 {time.time() - t0:.0f}s；{json.dumps(stats)}")


if __name__ == "__main__":
    main()

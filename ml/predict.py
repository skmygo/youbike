"""M5 線上推論：對最新一個時間槽算特徵 → 12 個 LightGBM 模型 → predictions.parquet。

設計重點
--------
1. **特徵零漂移**：這裡的 window SQL 與 `ml/features.py::build_features` 逐欄對齊，
   差別只在不算 LEAD 目標欄、且最後只留最新一槽（約 1,500 列），所以推論極輕量。
2. **歷史橋接（bridge）**：lag 最遠要看 336 槽＝7 天，但即時快照是這次黑客松才開始累積的，
   歷史資料則停在 2026-06-30。缺口不能留 NULL（訓練時這些欄位都有值，全空會讓分布崩掉），
   因此缺的槽用「同站、同星期幾、同半小時、歷史上最後一次的實際觀測」補，並標記 `is_live`。
   語義是「還沒有近期觀測時，先用該站上一次同時段的真實水位暖機」；即時資料每多累積一槽，
   橋接佔比就自動下降，是會自我修復的設計。輸出的 `live_slot_ratio` 誠實揭露這個比例。
3. **絕不在 API 請求路徑跑模型**：這支由 Dagster 排程呼叫，結果寫成 parquet，API 只讀檔。
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd

from ml.config import (
    ALERT_PROBA_THRESHOLD,
    CATEGORICAL_COLS,
    DATA_DIR,
    FEATURE_COLS,
    HORIZONS,
    MODEL_DIR,
    N_CLUSTERS,
    SLOT_MINUTES,
)

SERVING_DIR = DATA_DIR / "serving"
# 推論用的輔助表（站點/常態/鄰居/假日）跟模型檔一起放 models/，
# 部署時 bootstrap 只要拉 models/ 就湊齊了；本機剛跑完 features 時則直接用 ml/serving/。
_ML_SERVING_CANDIDATES = (MODEL_DIR, DATA_DIR / "ml" / "serving")
RECENT_PARQUET = SERVING_DIR / "recent.parquet"
HISTORY_GLOB = str(DATA_DIR / "history" / "snapshots_*.parquet")
TARGET = SERVING_DIR / "forecast.parquet"        # 對齊 api/settings.py 的 FORECAST_PARQUET
META_TARGET = SERVING_DIR / "forecast_meta.json"

# 橋接取樣窗：歷史尾端這麼多天內、同 dow×slot 的最後一次觀測
BRIDGE_LOOKBACK_DAYS = 28
LAG_SLOTS = 336  # 7 天，等於最遠的 lag


def _log(msg: str) -> None:
    print(f"[predict] {time.strftime('%H:%M:%S')} {msg}", flush=True)


def _con() -> duckdb.DuckDBPyConnection:
    """線上推論跟 API / Dagster 同機共存，配額壓到最低。"""
    con = duckdb.connect(":memory:")
    con.execute("SET memory_limit='1GB'")
    con.execute("SET threads=2")
    con.execute("SET preserve_insertion_order=false")
    return con


# --------------------------------------------------------------------- 特徵重算

def _aux(name: str) -> Path:
    """找推論輔助表：先看 models/，再看本機 ml/serving/。"""
    for base in _ML_SERVING_CANDIDATES:
        p = base / f"ml_{name}.parquet"
        if p.exists():
            return p
    raise FileNotFoundError(
        f"缺少 ML 輔助表 ml_{name}.parquet（找過 {[str(b) for b in _ML_SERVING_CANDIDATES]}）")


def build_live_features(con: duckdb.DuckDBPyConnection) -> tuple[pd.DataFrame, dict]:
    """組出「最新一槽」的特徵表（欄位與訓練期逐欄對齊）。"""
    stations = _aux("stations")
    norms = _aux("norms")
    neighbors = _aux("neighbors")
    holidays = _aux("holidays")
    if not RECENT_PARQUET.exists():
        raise FileNotFoundError(f"缺少即時快照：{RECENT_PARQUET}")

    con.execute(f"CREATE VIEW stations_ml AS SELECT * FROM read_parquet('{stations}')")
    con.execute(f"CREATE VIEW norms AS SELECT * FROM read_parquet('{norms}')")
    con.execute(f"CREATE VIEW neighbors AS SELECT * FROM read_parquet('{neighbors}')")
    con.execute(f"CREATE VIEW holidays AS SELECT * FROM read_parquet('{holidays}')")

    # 即時觀測：過濾條件與 features.build_base 的 obs 一致（含離線站剔除）
    con.execute(
        f"""
        CREATE TABLE obs_live AS
        SELECT s.station_id, s.ts, s.bikes::INT AS bikes,
               s.docks_avail::INT AS docks_avail, s.docks_total::INT AS docks_total,
               s.bikes::DOUBLE / s.docks_total AS ratio
        FROM read_parquet('{RECENT_PARQUET}') s
        JOIN stations_ml m USING (station_id)
        WHERE s.docks_total > 0 AND NOT (s.bikes = 0 AND s.docks_avail = 0)
        """
    )
    base_ts = con.execute("SELECT max(ts) FROM obs_live").fetchone()[0]
    if base_ts is None:
        raise RuntimeError("即時快照沒有任何有效觀測")
    n_live_stations = con.execute(
        "SELECT count(*) FROM obs_live WHERE ts = ?", [base_ts]
    ).fetchone()[0]
    _log(f"最新槽 {base_ts}，即時站數 {n_live_stations}")

    # 橋接表：歷史尾端 28 天內，每站每 (dow, slot) 的最後一次實際觀測
    con.execute(
        f"""
        CREATE TABLE bridge AS
        WITH h AS (
            SELECT s.station_id, s.ts, s.bikes::INT AS bikes,
                   s.docks_avail::INT AS docks_avail, s.docks_total::INT AS docks_total,
                   s.bikes::DOUBLE / s.docks_total AS ratio
            FROM read_parquet('{HISTORY_GLOB}') s
            JOIN stations_ml m USING (station_id)
            WHERE s.docks_total > 0 AND NOT (s.bikes = 0 AND s.docks_avail = 0)
              AND s.ts >= (SELECT max(ts) FROM read_parquet('{HISTORY_GLOB}'))
                          - INTERVAL {BRIDGE_LOOKBACK_DAYS} DAY
        )
        SELECT station_id,
               dayofweek(ts) AS dow,
               (hour(ts) * 2 + (minute(ts) / 30)::INT) AS slot_of_day,
               arg_max(bikes, ts) AS bikes,
               arg_max(docks_avail, ts) AS docks_avail,
               arg_max(docks_total, ts) AS docks_total,
               arg_max(ratio, ts) AS ratio
        FROM h GROUP BY 1, 2, 3
        """
    )

    # 完整 30 分槽網格：即時優先，缺的用橋接補
    con.execute(
        f"""
        CREATE TABLE grid AS
        WITH slots AS (
            SELECT unnest(generate_series(
                TIMESTAMP '{base_ts}' - INTERVAL {LAG_SLOTS * SLOT_MINUTES} MINUTE,
                TIMESTAMP '{base_ts}',
                INTERVAL {SLOT_MINUTES} MINUTE)) AS ts
        ), cells AS (
            SELECT m.station_id, sl.ts FROM stations_ml m CROSS JOIN slots sl
        )
        SELECT c.station_id, c.ts,
               COALESCE(o.bikes, b.bikes) AS bikes,
               COALESCE(o.docks_avail, b.docks_avail) AS docks_avail,
               COALESCE(o.docks_total, b.docks_total) AS docks_total,
               COALESCE(o.ratio, b.ratio) AS ratio,
               (o.ratio IS NOT NULL) AS is_live
        FROM cells c
        LEFT JOIN obs_live o ON o.station_id = c.station_id AND o.ts = c.ts
        LEFT JOIN bridge b ON b.station_id = c.station_id
             AND b.dow = dayofweek(c.ts)
             AND b.slot_of_day = (hour(c.ts) * 2 + (minute(c.ts) / 30)::INT)
        """
    )
    cover = con.execute(
        "SELECT count(*) FILTER (WHERE is_live), count(*) FILTER (WHERE ratio IS NOT NULL),"
        " count(*) FROM grid"
    ).fetchone()
    _log(f"grid {cover[2]:,} 格：即時 {cover[0]:,}、橋接後有值 {cover[1]:,}")

    # 逐槽鄰域 / 行政區 / 分群水位（與訓練期同定義）
    con.execute(
        """
        CREATE TABLE neigh_agg AS
        SELECT n.station_id, g.ts, avg(g.ratio) AS neigh_ratio
        FROM neighbors n JOIN grid g ON g.station_id = n.neighbor_id
        WHERE g.ratio IS NOT NULL GROUP BY 1, 2
        """
    )
    con.execute(
        """
        CREATE TABLE group_agg AS
        SELECT s.district, s.cluster_id, g.ts, avg(g.ratio) AS ratio, count(*) AS n
        FROM grid g JOIN stations_ml s USING (station_id)
        WHERE g.ratio IS NOT NULL GROUP BY 1, 2, 3
        """
    )
    con.execute(
        """
        CREATE TABLE district_agg AS
        SELECT district, ts, sum(ratio * n) / sum(n) AS district_ratio
        FROM group_agg GROUP BY 1, 2
        """
    )
    con.execute(
        """
        CREATE TABLE cluster_agg AS
        SELECT cluster_id, ts, sum(ratio * n) / sum(n) AS cluster_ratio
        FROM group_agg GROUP BY 1, 2
        """
    )

    # 與 features.build_features 逐欄對齊的 window 特徵，只留最新一槽
    feat = con.execute(
        f"""
        WITH w AS (
            SELECT station_id, ts, bikes, docks_avail, docks_total, ratio, is_live,
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
                   sum(CASE WHEN bikes <= 1 THEN 1 ELSE 0 END) OVER (
                        PARTITION BY station_id ORDER BY ts
                        ROWS BETWEEN 5 PRECEDING AND CURRENT ROW) AS empty_streak,
                   sum(CASE WHEN docks_avail <= 1 THEN 1 ELSE 0 END) OVER (
                        PARTITION BY station_id ORDER BY ts
                        ROWS BETWEEN 5 PRECEDING AND CURRENT ROW) AS full_streak
            FROM grid
            WINDOW w AS (PARTITION BY station_id ORDER BY ts)
        )
        SELECT
            w.station_id, w.ts, s.name, s.district, w.is_live,
            w.docks_avail,
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
            s.capacity, s.lat, s.lon, s.cluster_id, s.district_id,
            n.norm_ratio, w.ratio - n.norm_ratio AS norm_dev,
            n.norm_empty_rate, n.norm_full_rate,
            da.district_ratio, ca.cluster_ratio,
            na.neigh_ratio, na.neigh_ratio - da.district_ratio AS neigh_dev
        FROM w
        JOIN stations_ml s USING (station_id)
        LEFT JOIN norms n ON n.station_id = w.station_id
             AND n.dow = dayofweek(w.ts)
             AND n.slot_of_day = (hour(w.ts) * 2 + (minute(w.ts) / 30)::INT)
        LEFT JOIN district_agg da ON da.district = s.district AND da.ts = w.ts
        LEFT JOIN cluster_agg ca ON ca.cluster_id = s.cluster_id AND ca.ts = w.ts
        LEFT JOIN neigh_agg na ON na.station_id = w.station_id AND na.ts = w.ts
        WHERE w.ts = TIMESTAMP '{base_ts}' AND w.ratio IS NOT NULL
        """
    ).df()

    meta = {
        "base_ts": str(base_ts),
        "n_stations": int(len(feat)),
        "n_live_stations": int(n_live_stations),
        "grid_cells": int(cover[2]),
        "live_slot_ratio": round(cover[0] / cover[2], 4) if cover[2] else 0.0,
        "bridged_slot_ratio": round((cover[1] - cover[0]) / cover[2], 4) if cover[2] else 0.0,
    }
    _log(f"特徵表 {len(feat):,} 列（即時槽佔比 {meta['live_slot_ratio']:.1%}）")
    return feat, meta


# ------------------------------------------------------------------------ 推論

def _as_model_frame(feat: pd.DataFrame) -> pd.DataFrame:
    """轉成模型吃的型別。

    類別欄一定要用「訓練期的完整類別集合」建 Categorical：線上只有一個時間槽，
    dow / slot_of_day 都只剩單一值，直接 astype('category') 會讓 codes 從 0 重編而錯位。
    """
    spec = json.loads((MODEL_DIR / "feature_cols.json").read_text(encoding="utf-8"))
    cols, cats = spec["features"], spec["categorical"]
    n_district = int(feat["district_id"].max()) + 1 if len(feat) else 1
    domains = {
        "cluster_id": range(N_CLUSTERS),
        "district_id": range(max(n_district, int(feat["district_id"].max()) + 1)),
        "dow": range(7),
        "slot_of_day": range(48),
    }
    X = pd.DataFrame(index=feat.index)
    for c in cols:
        if c in cats:
            X[c] = pd.Categorical(feat[c].astype("Int16"), categories=list(domains[c]))
        else:
            X[c] = feat[c].astype("float32")
    return X


def load_models() -> dict[str, lgb.Booster]:
    models = {}
    for h in HORIZONS:
        models[f"reg_h{h}"] = lgb.Booster(model_file=str(MODEL_DIR / f"lgbm_reg_h{h}.txt"))
        for ev in ("empty", "full"):
            models[f"clf_{ev}_h{h}"] = lgb.Booster(
                model_file=str(MODEL_DIR / f"lgbm_clf_{ev}_h{h}.txt"))
    return models


def load_thresholds() -> dict:
    """驗證集上 F1 最佳的門檻（0.10–0.30 之間），當「營運建議」用。

    規劃書定的 0.70 是高信心門檻，精確率高但召回低，長時距幾乎不會觸發；
    兩組都輸出，讓調度單位自己決定要多敏感（報告裡兩個門檻的表現都有列）。
    """
    p = MODEL_DIR / "thresholds.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def predict(feat: pd.DataFrame) -> pd.DataFrame:
    X = _as_model_frame(feat)
    models = load_models()
    thresholds = load_thresholds()
    cap = feat["docks_total"].to_numpy(dtype="float64")
    rows = []
    for h in HORIZONS:
        ratio = np.clip(models[f"reg_h{h}"].predict(X), 0.0, 1.0)
        p_empty = models[f"clf_empty_h{h}"].predict(X)
        p_full = models[f"clf_full_h{h}"].predict(X)
        t_empty = float(thresholds.get(f"clf_empty_h{h}", ALERT_PROBA_THRESHOLD))
        t_full = float(thresholds.get(f"clf_full_h{h}", ALERT_PROBA_THRESHOLD))
        bikes = np.round(ratio * cap)
        rows.append(pd.DataFrame({
            "station_id": feat["station_id"].to_numpy(),
            "name": feat["name"].to_numpy(),
            "district": feat["district"].to_numpy(),
            "base_ts": feat["ts"].to_numpy(),
            "horizon": np.int16(h),
            "now_bikes": feat["bikes"].to_numpy().astype("int16"),
            "now_docks_avail": feat["docks_avail"].to_numpy().astype("int16"),
            "docks_total": cap.astype("int16"),
            "pred_ratio": ratio.astype("float32"),
            "pred_bikes": bikes.astype("int16"),
            "pred_docks": np.maximum(cap - bikes, 0).astype("int16"),
            "proba_empty": p_empty.astype("float32"),
            "proba_full": p_full.astype("float32"),
            # alert_* = 規劃書的 70% 高信心門檻；watch_* = 驗證集最佳 F1 門檻（營運建議）
            "alert_empty": p_empty >= ALERT_PROBA_THRESHOLD,
            "alert_full": p_full >= ALERT_PROBA_THRESHOLD,
            "watch_empty": p_empty >= t_empty,
            "watch_full": p_full >= t_full,
            "thr_empty": np.float32(t_empty),
            "thr_full": np.float32(t_full),
            "is_live": feat["is_live"].to_numpy(),
        }))
    return pd.concat(rows, ignore_index=True)


def write_atomic(df: pd.DataFrame, target: Path) -> None:
    """寫 .tmp → rename，API 讀的當下不會看到半成品。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    df.to_parquet(tmp, index=False, compression="zstd")
    tmp.replace(target)


def run() -> dict:
    t0 = time.time()
    con = _con()
    try:
        feat, meta = build_live_features(con)
    finally:
        con.close()
    preds = predict(feat)
    write_atomic(preds, TARGET)

    at60 = preds["horizon"] == 60
    n_alert_empty = int(preds.loc[at60, "alert_empty"].sum())
    n_alert_full = int(preds.loc[at60, "alert_full"].sum())
    meta.update({
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "rows": int(len(preds)),
        "horizons": list(HORIZONS),
        "alert_threshold": ALERT_PROBA_THRESHOLD,
        "alerts_60min": {"empty": n_alert_empty, "full": n_alert_full},
        "watch_60min": {"empty": int(preds.loc[at60, "watch_empty"].sum()),
                        "full": int(preds.loc[at60, "watch_full"].sum())},
        "operational_thresholds": load_thresholds(),
        "elapsed_sec": round(time.time() - t0, 1),
    })
    META_TARGET.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    _log(f"predictions → {TARGET}（{len(preds):,} 列，60 分內預警 空 {n_alert_empty} / 滿 {n_alert_full}，"
         f"{meta['elapsed_sec']}s）")
    return meta


if __name__ == "__main__":
    run()

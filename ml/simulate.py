"""M6 / KPI1：用 6 月測試集模擬「照模型建議調度，能減少多少無車時間」。

這是**模擬**不是實測，所以假設全部攤開寫在輸出的 assumptions 裡，前端也照樣顯示：

1. 時間粒度 30 分鐘；「無車」沿用 WP4 定義（可借 ≤ 1）。
2. 調度隊每 30 分鐘能處理 K 個站（K 做敏感度分析）。車補到位需要時間，因此
   - **模型調度**：t 時刻看 60 分後的預測，挑機率最高的 K 站派車 → 車在 t+60 到位，
     覆蓋 t+60 起的 COVER 個槽。優勢是**車在站空掉之前就到了**。
   - **規則型調度**：t 時刻只看得到「現在已經空了」的站（照已空時長排序挑 K 站）→
     車在 t+30 到位，覆蓋 t+30 起的 COVER 個槽。缺點是**站早就空了才出發**。
3. 一次補車能讓該站接下來 COVER 個槽不缺車（預設 4 槽＝2 小時）。
   這是樂觀假設：真實世界會被熱門站的持續流失打折。
4. 只算「無車站-槽」的減少，不換算成營收或滿意度——那需要需求彈性資料，我們沒有。

輸出 `models/kpi.json`，API `/api/model/kpi` 讀它。
"""

from __future__ import annotations

import json
import time

import lightgbm as lgb
import numpy as np
import pandas as pd

from ml.config import (
    EMPTY_BIKES_MAX,
    FEATURE_COLS,
    MLFLOW_EXPERIMENT,
    MLFLOW_TRACKING_URI,
    MODEL_DIR,
    SLOT_MINUTES,
    TEST_RANGE,
)
from ml.evaluate import find_events
from ml.train import load_split

HORIZON = 60                      # 用哪個時距的模型擬定調度
COVER_SLOTS = 4                   # 一次補車撐幾個槽（4 × 30 分 = 2 小時）
CAPACITIES = (5, 10, 20, 40)      # 每 30 分鐘能處理幾個站（敏感度分析）
MODEL_LEAD_SLOTS = HORIZON // SLOT_MINUTES   # 模型：派車後 60 分到位
RULE_LEAD_SLOTS = 1                          # 規則型：發現已空後 30 分到位


def _log(msg: str) -> None:
    print(f"[kpi] {time.strftime('%H:%M:%S')} {msg}", flush=True)


def _covered_pairs(picks: pd.DataFrame, lead: int, slot: pd.Timedelta) -> set:
    """把「在 ts 派往 station 的車」展開成它覆蓋到的 (station_id, ts) 集合。"""
    out = []
    for k in range(lead, lead + COVER_SLOTS):
        out.append(pd.DataFrame({
            "station_id": picks["station_id"].to_numpy(),
            "ts": picks["ts"].to_numpy() + slot * k,
        }))
    cov = pd.concat(out, ignore_index=True).drop_duplicates()
    return set(map(tuple, cov.to_numpy()))


def run() -> dict:
    t0 = time.time()
    test = load_split("test")
    booster = lgb.Booster(model_file=str(MODEL_DIR / f"lgbm_clf_empty_h{HORIZON}.txt"))
    _log("推論 h60 空車機率…")
    proba = booster.predict(test[FEATURE_COLS])

    df = pd.DataFrame({
        "station_id": test["station_id"].to_numpy(),
        "ts": pd.to_datetime(test["ts"].to_numpy()),
        "bikes": test["bikes"].to_numpy(),
        "empty_streak": test["empty_streak"].to_numpy(),
        "proba": proba.astype("float32"),
    })
    del test, proba
    df["is_empty"] = df["bikes"] <= EMPTY_BIKES_MAX
    slot = pd.Timedelta(minutes=SLOT_MINUTES)

    total_empty = int(df["is_empty"].sum())
    empty_pairs = set(map(tuple, df.loc[df["is_empty"], ["station_id", "ts"]].to_numpy()))
    _log(f"6 月無車站-槽共 {total_empty:,}（{total_empty * SLOT_MINUTES / 60:,.0f} 站-小時）")

    # 調度是兩個佇列，不是一個排序：
    #   預防佇列 —— 只從「現在還沒空」的站裡挑預測機率最高的（規則型做不到這件事）
    #   補救佇列 —— 從「現在已經空了」的站裡挑空最久的（規則型唯一能做的事）
    # 若混在一起排序，已空站的機率永遠是 0.99+，會把預防名額整個吃光。
    prevent_pool = df[~df["is_empty"]].copy()
    prevent_pool["rank_prevent"] = prevent_pool.groupby("ts")["proba"].rank(
        method="first", ascending=False)
    rule_pool = df[df["is_empty"]].copy()
    rule_pool["rank_rule"] = rule_pool.groupby("ts")["empty_streak"].rank(
        method="first", ascending=False)

    # 事件層級：對「新發生」的空車事件，預防佇列能在它開始前就把車派到嗎
    ev_src = df[["station_id", "ts", "bikes"]].copy()
    ev_src["docks_total"] = 0  # find_events 判斷 empty 時用不到，補欄位滿足介面
    events = find_events(ev_src, "empty")
    rank_lookup = prevent_pool.set_index(["station_id", "ts"])["rank_prevent"]
    ev_key = pd.MultiIndex.from_arrays([
        events["station_id"].to_numpy(),
        events["ts"].to_numpy() - np.timedelta64(HORIZON, "m"),
    ])
    ranks_before = np.nan_to_num(rank_lookup.reindex(ev_key).to_numpy(), nan=1e9)

    scenarios = []
    for k in CAPACITIES:
        half = max(k // 2, 1)
        prevent_cov = _covered_pairs(
            prevent_pool.loc[prevent_pool["rank_prevent"] <= k], MODEL_LEAD_SLOTS, slot)
        rule_cov = _covered_pairs(
            rule_pool.loc[rule_pool["rank_rule"] <= k], RULE_LEAD_SLOTS, slot)
        hybrid_cov = _covered_pairs(
            prevent_pool.loc[prevent_pool["rank_prevent"] <= half], MODEL_LEAD_SLOTS, slot
        ) | _covered_pairs(
            rule_pool.loc[rule_pool["rank_rule"] <= half], RULE_LEAD_SLOTS, slot)

        p_hit = len(empty_pairs & prevent_cov)
        r_hit = len(empty_pairs & rule_cov)
        h_hit = len(empty_pairs & hybrid_cov)
        n_ev = int(np.sum(ranks_before <= k))
        n_ev_half = int(np.sum(ranks_before <= half))

        scenarios.append({
            "capacity_per_slot": k,
            "dispatches_per_day": k * (24 * 60 // SLOT_MINUTES),
            # 三種策略在同一份量能下的表現
            "prevent_avoided_slots": p_hit,
            "prevent_avoided_pct": round(100 * p_hit / total_empty, 2),
            "prevent_avoided_station_hours": round(p_hit * SLOT_MINUTES / 60, 1),
            "rule_avoided_slots": r_hit,
            "rule_avoided_pct": round(100 * r_hit / total_empty, 2),
            "hybrid_avoided_slots": h_hit,
            "hybrid_avoided_pct": round(100 * h_hit / total_empty, 2),
            "hybrid_avoided_station_hours": round(h_hit * SLOT_MINUTES / 60, 1),
            "hybrid_uplift_vs_rule_pct_points": round(100 * (h_hit - r_hit) / total_empty, 2),
            # 事件層級：規則型在事件開始前不可能知道，恆為 0
            "events_prevented": n_ev,
            "events_prevented_pct": round(100 * n_ev / max(len(events), 1), 2),
            "events_prevented_hybrid": n_ev_half,
            "events_prevented_hybrid_pct": round(100 * n_ev_half / max(len(events), 1), 2),
            "rule_events_prevented_pct": 0.0,
        })
        s = scenarios[-1]
        _log(f"每槽 {k} 站｜純預防 {s['prevent_avoided_pct']}%、純補救(規則型) {s['rule_avoided_pct']}%、"
             f"一半一半 {s['hybrid_avoided_pct']}%（比規則型 {s['hybrid_uplift_vs_rule_pct_points']:+.2f}pp）"
             f"｜新事件可預防 {n_ev:,}/{len(events):,} = {s['events_prevented_pct']}%")

    # ── 結構性分析：無車時間到底集中在哪些站 ────────────────────────────────
    per_station = df.groupby("station_id")["is_empty"].sum().sort_values(ascending=False)
    n_top = max(int(len(per_station) * 0.05), 1)
    top_share = float(per_station.head(n_top).sum() / total_empty)
    always_empty_stations = int((per_station / df.groupby("station_id").size() > 0.5).sum())

    out = {
        "kpi": "KPI1 — 照建議調度可減少的無車時間（6 月測試集模擬）",
        "test_range": list(TEST_RANGE),
        "horizon_minutes": HORIZON,
        "slot_minutes": SLOT_MINUTES,
        "total_empty_station_slots": total_empty,
        "total_empty_station_hours": round(total_empty * SLOT_MINUTES / 60, 1),
        "n_new_events": int(len(events)),
        "structural": {
            "top5pct_stations": n_top,
            "top5pct_share_of_empty_time": round(top_share, 4),
            "stations_empty_over_half_the_time": always_empty_stations,
            "insight": "無車時間高度集中在少數站——那是車輛配置與站點規模的問題，"
                       "調度只能緩解、不能根治。動態調度真正能改變的是「新發生的空車事件」。",
        },
        "scenarios": scenarios,
        "assumptions": [
            f"「無車」＝可借車輛 ≤ {EMPTY_BIKES_MAX} 台（沿用 WP4 定義）",
            f"一次補車能讓該站接下來 {COVER_SLOTS} 個槽（{COVER_SLOTS * SLOT_MINUTES} 分鐘）不缺車"
            "——樂觀假設，熱門站實際會更快再空",
            f"模型調度：看 {HORIZON} 分後的預測派車，車在 {HORIZON} 分鐘後到位（站還沒空就補上）",
            f"規則型調度：只看得到已經空掉的站，車在 {RULE_LEAD_SLOTS * SLOT_MINUTES} 分鐘後到位"
            "（比模型快，但出發時站早就空了）",
            "兩者的每槽派工量能相同，差別只在「挑哪些站」與「什麼時候出發」",
            "調度分兩個佇列：「預防」只從現在還沒空的站裡挑（規則型做不到）；"
            "「補救」從已經空了的站裡挑空最久的（規則型唯一能做的）。"
            "混在一起排序沒有意義——已空站的預測機率永遠是 0.99+，會把預防名額整個吃光",
            "「一半一半」＝把量能拆成一半預防、一半補救，這最接近真實調度室會做的事",
            "只計算無車站-槽的減少，未換算成營收或滿意度（缺需求彈性資料）",
            "「新事件可預防率」＝新發生的空車事件中，模型在事件開始前 60 分鐘就把該站排進預防佇列前 K 名"
            "的比例；規則型在事件開始前不可能知道，恆為 0",
        ],
        "elapsed_sec": round(time.time() - t0, 1),
    }
    path = MODEL_DIR / "kpi.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    _log(f"kpi → {path}")

    try:
        import mlflow

        mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
        mlflow.set_experiment(MLFLOW_EXPERIMENT)
        with mlflow.start_run(run_name="kpi1-dispatch-simulation"):
            mlflow.set_tags({"stage": "kpi", "split": "test", "milestone": "M6"})
            for s in scenarios:
                k = s["capacity_per_slot"]
                mlflow.log_metric(f"k{k}_model_avoided_pct", s["model_avoided_pct"])
                mlflow.log_metric(f"k{k}_rule_avoided_pct", s["rule_avoided_pct"])
            mlflow.log_dict(out, "kpi1_dispatch_simulation.json")
    except Exception as exc:  # MLflow 不通不該擋住 KPI 產出
        _log(f"MLflow 記錄失敗（不影響輸出）：{exc}")
    return out


if __name__ == "__main__":
    run()

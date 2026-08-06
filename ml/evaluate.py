"""M4 回測：6 月測試集（訓練/驗證期完全沒碰過）→ report.json。

三層評估
1. 水位回歸：LightGBM vs persistence vs 上週同日同時段（MAE / RMSE，ratio 與車輛數兩種單位）
2. 事件分類：空/滿 × 4 horizon 的 precision / recall / F1 / PR-AUC（含線上實際用的 0.70 門檻）
3. **事件級預警**：對 6 月真實發生的空/滿事件，量「模型最早能提前幾分鐘示警」與覆蓋率、誤報率
   —— 這是命題最在意的數字（規則型警示的提前量恆為 0 分，模型的增量就是價值）
"""

from __future__ import annotations

import json
import time
from datetime import datetime

import lightgbm as lgb
import numpy as np
import pandas as pd

from ml.config import (
    ALERT_PROBA_THRESHOLD,
    CATEGORICAL_COLS,
    EMPTY_BIKES_MAX,
    FEATURE_COLS,
    FULL_DOCKS_MAX,
    HORIZONS,
    ML_DIR,
    MLFLOW_EXPERIMENT,
    MLFLOW_TRACKING_URI,
    MODEL_DIR,
    SLOT_MINUTES,
    TEST_RANGE,
    TRAIN_RANGE,
    VALID_RANGE,
)
from ml.train import load_split, mae, prf, rmse

MIN_EVENT_SLOTS = 2  # 連續 2 槽（60 分）以上才算一次有意義的空/滿事件


def _log(msg: str) -> None:
    print(f"[eval] {time.strftime('%H:%M:%S')} {msg}", flush=True)


def load_models() -> dict:
    models = {}
    for h in HORIZONS:
        models[f"reg_h{h}"] = lgb.Booster(model_file=str(MODEL_DIR / f"lgbm_reg_h{h}.txt"))
        for ev in ("empty", "full"):
            models[f"clf_{ev}_h{h}"] = lgb.Booster(
                model_file=str(MODEL_DIR / f"lgbm_clf_{ev}_h{h}.txt")
            )
    return models


# --------------------------------------------------------------- 1+2 逐列指標

def evaluate_pointwise(test: pd.DataFrame, models: dict, thresholds: dict) -> tuple[dict, dict, pd.DataFrame]:
    X = test[FEATURE_COLS]
    cap = test["docks_total"].to_numpy(dtype="float64")
    regression: dict = {}
    classification: dict = {"empty": {}, "full": {}}
    proba_cols = {}

    for h in HORIZONS:
        y = test[f"y_ratio_{h}"].to_numpy(dtype="float64")
        pred = models[f"reg_h{h}"].predict(X)
        pred = np.clip(pred, 0.0, 1.0)
        per: dict = {}
        per["lgbm"] = {
            "mae_ratio": mae(y, pred),
            "rmse_ratio": rmse(y, pred),
            "mae_bikes": mae(y * cap, pred * cap),
            "n": int(len(y)),
        }
        pers = test["ratio"].to_numpy(dtype="float64")
        per["persistence"] = {
            "mae_ratio": mae(y, pers),
            "rmse_ratio": rmse(y, pers),
            "mae_bikes": mae(y * cap, pers * cap),
            "n": int(len(y)),
        }
        lw = test[f"bl_lastweek_{h}"].to_numpy(dtype="float64")
        ok = ~np.isnan(lw)
        per["lastweek"] = {
            "mae_ratio": mae(y[ok], lw[ok]),
            "rmse_ratio": rmse(y[ok], lw[ok]),
            "mae_bikes": mae(y[ok] * cap[ok], lw[ok] * cap[ok]),
            "n": int(ok.sum()),
        }
        for b in ("persistence", "lastweek"):
            per["lgbm"][f"improve_vs_{b}_pct"] = (
                100 * (per[b]["mae_bikes"] - per["lgbm"]["mae_bikes"]) / per[b]["mae_bikes"]
            )
        regression[str(h)] = per
        _log(f"reg h={h}: LGBM {per['lgbm']['mae_bikes']:.3f} 台 | persistence "
             f"{per['persistence']['mae_bikes']:.3f} | lastweek {per['lastweek']['mae_bikes']:.3f}")

        for ev, col, thr in (("empty", f"y_bikes_{h}", EMPTY_BIKES_MAX),
                             ("full", f"y_docks_{h}", FULL_DOCKS_MAX)):
            yb = (test[col].to_numpy() <= thr).astype(int)
            proba = models[f"clf_{ev}_h{h}"].predict(X)
            proba_cols[f"p_{ev}_{h}"] = proba.astype("float32")
            from sklearn.metrics import average_precision_score, roc_auc_score

            t_best = thresholds.get(f"clf_{ev}_h{h}", 0.5)
            m = {
                "pos_rate": float(yb.mean()),
                "pr_auc": float(average_precision_score(yb, proba)),
                "roc_auc": float(roc_auc_score(yb, proba)),
                "at_alert_threshold": {"threshold": ALERT_PROBA_THRESHOLD,
                                       **prf(yb, (proba >= ALERT_PROBA_THRESHOLD).astype(int))},
                "at_valid_best_f1": {"threshold": t_best,
                                     **prf(yb, (proba >= t_best).astype(int))},
            }
            # 規則型對照：用 persistence 換算的事件判斷
            base_pred = (
                (test["ratio"].to_numpy() * cap <= EMPTY_BIKES_MAX).astype(int)
                if ev == "empty"
                else ((1 - test["ratio"].to_numpy()) * cap <= FULL_DOCKS_MAX).astype(int)
            )
            m["persistence_rule"] = prf(yb, base_pred)
            classification[ev][str(h)] = m
            _log(f"clf {ev} h={h}: PR-AUC={m['pr_auc']:.3f} "
                 f"F1@0.7={m['at_alert_threshold']['f1']:.3f} "
                 f"(規則型 F1={m['persistence_rule']['f1']:.3f})")

    proba_df = pd.DataFrame(proba_cols, index=test.index)
    proba_df["station_id"] = test["station_id"].to_numpy()
    proba_df["ts"] = test["ts"].to_numpy()
    return regression, classification, proba_df


# ------------------------------------------------------------ 3 事件級預警評估

def find_events(test: pd.DataFrame, kind: str) -> pd.DataFrame:
    """找 6 月真實發生的空/滿事件起點（連續 ≥MIN_EVENT_SLOTS 槽）。"""
    col = "bikes" if kind == "empty" else None
    df = test[["station_id", "ts", "bikes", "docks_total"]].copy()
    if kind == "empty":
        df["in_state"] = (df["bikes"] <= EMPTY_BIKES_MAX).astype(int)
    else:
        df["in_state"] = ((df["docks_total"] - df["bikes"]) <= FULL_DOCKS_MAX).astype(int)
    df = df.sort_values(["station_id", "ts"])
    g = df.groupby("station_id", sort=False)["in_state"]
    prev = g.shift(1).fillna(0)
    # 連續 MIN_EVENT_SLOTS 槽都在狀態內
    sustained = df["in_state"].copy()
    for k in range(1, MIN_EVENT_SLOTS):
        sustained = sustained & g.shift(-k).fillna(0).astype(int)
    starts = df[(df["in_state"] == 1) & (prev == 0) & (sustained == 1)]
    return starts[["station_id", "ts"]].reset_index(drop=True)


def evaluate_events(test: pd.DataFrame, proba_df: pd.DataFrame, kind: str,
                    threshold: float = ALERT_PROBA_THRESHOLD) -> dict:
    """對每個事件：最早在幾分鐘前，模型就以 ≥threshold 的機率預告了它。"""
    events = find_events(test, kind)
    if events.empty:
        return {"n_events": 0}
    lookup = proba_df.set_index(["station_id", "ts"])
    lead = np.zeros(len(events), dtype="int32")  # 0 = 未提前偵測到
    for h in HORIZONS:
        key = pd.MultiIndex.from_arrays(
            [events["station_id"].to_numpy(),
             events["ts"].to_numpy() - np.timedelta64(h, "m")]
        )
        col = f"p_{kind}_{h}"
        vals = lookup[col].reindex(key).to_numpy()
        hit = np.nan_to_num(vals, nan=0.0) >= threshold
        lead = np.where(hit & (lead < h), h, lead)

    detected = lead > 0
    n_days = (pd.Timestamp(TEST_RANGE[1]) - pd.Timestamp(TEST_RANGE[0])).days + 1
    n_stations = int(test["station_id"].nunique())
    # 誤報：發出預警（任一 horizon ≥threshold）但該 horizon 的目標時刻其實沒事
    fa_total, alert_total = 0, 0
    for h in HORIZONS:
        col = f"y_bikes_{h}" if kind == "empty" else f"y_docks_{h}"
        thr = EMPTY_BIKES_MAX if kind == "empty" else FULL_DOCKS_MAX
        truth = (test[col].to_numpy() <= thr)
        fired = proba_df[f"p_{kind}_{h}"].to_numpy() >= threshold
        alert_total += int(fired.sum())
        fa_total += int((fired & ~truth).sum())

    out = {
        "n_events": int(len(events)),
        "detected": int(detected.sum()),
        "coverage": float(detected.mean()),
        "mean_lead_minutes": float(lead[detected].mean()) if detected.any() else 0.0,
        "median_lead_minutes": float(np.median(lead[detected])) if detected.any() else 0.0,
        "mean_lead_minutes_all_events": float(lead.mean()),
        "lead_distribution": {str(h): int((lead == h).sum()) for h in HORIZONS},
        "missed": int((~detected).sum()),
        "threshold": threshold,
        "alerts_fired": alert_total,
        "false_alarms": fa_total,
        "false_alarm_rate": float(fa_total / alert_total) if alert_total else 0.0,
        "alerts_per_station_per_day": float(alert_total / max(n_stations * n_days, 1)),
        "baseline_rule_lead_minutes": 0.0,  # 規則型只能在事件已發生後才報
    }
    _log(f"事件 {kind}: {out['n_events']:,} 起，偵測率 {out['coverage']:.1%}，"
         f"平均提前 {out['mean_lead_minutes']:.0f} 分，誤報率 {out['false_alarm_rate']:.1%}")
    return out


# ------------------------------------------------------------------------ main

def main() -> None:
    t0 = time.time()
    thresholds = json.loads((MODEL_DIR / "thresholds.json").read_text())
    train_summary = json.loads((ML_DIR / "train_summary.json").read_text())
    splits = json.loads((ML_DIR / "splits.json").read_text())
    holidays = json.loads((ML_DIR / "holidays.json").read_text())

    test = load_split("test")
    models = load_models()
    regression, classification, proba_df = evaluate_pointwise(test, models, thresholds)
    events = {k: evaluate_events(test, proba_df, k) for k in ("empty", "full")}

    importance = {}
    for h in HORIZONS:
        b = models[f"reg_h{h}"]
        pairs = sorted(zip(b.feature_name(), b.feature_importance("gain")), key=lambda x: -x[1])
        importance[f"reg_h{h}"] = [{"feature": k, "gain": float(v)} for k, v in pairs[:15]]

    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "task": "YouBike 新北市場站水位預測與空/滿事件預警",
        "data": {
            "history_range": ["2026-01-01", "2026-06-30"],
            "slot_minutes": SLOT_MINUTES,
            "split": {"train": TRAIN_RANGE, "valid": VALID_RANGE, "test": TEST_RANGE},
            "rows": {k: v["rows"] for k, v in splits.items()},
            "stations": int(test["station_id"].nunique()),
            "n_features": len(FEATURE_COLS),
            "detected_holidays": holidays,
        },
        "model": {
            "algorithm": "LightGBM",
            "regression_objective": "regression_l1 (MAE)",
            "horizons_minutes": list(HORIZONS),
            "categorical_features": CATEGORICAL_COLS,
            "best_iterations": {k: v.get("best_iteration") for k, v in train_summary["models"].items()},
        },
        "regression": regression,
        "classification": classification,
        "events": events,
        "valid_baselines": train_summary["baselines"],
        "feature_importance": importance,
        "headline": {},
    }

    # 首頁 KPI 用的一句話數字（M6 的 hero 直接讀這裡）
    h60 = regression["60"]
    report["headline"] = {
        "mae_bikes_60min": round(h60["lgbm"]["mae_bikes"], 3),
        "mae_bikes_60min_persistence": round(h60["persistence"]["mae_bikes"], 3),
        "improve_vs_persistence_pct_60min": round(h60["lgbm"]["improve_vs_persistence_pct"], 1),
        "empty_event_coverage": round(events["empty"]["coverage"], 4),
        "empty_event_mean_lead_minutes": round(events["empty"]["mean_lead_minutes"], 1),
        "empty_f1_60min": round(classification["empty"]["60"]["at_alert_threshold"]["f1"], 3),
        "full_event_coverage": round(events["full"]["coverage"], 4),
        "full_event_mean_lead_minutes": round(events["full"]["mean_lead_minutes"], 1),
        "n_empty_events_june": events["empty"]["n_events"],
        "n_full_events_june": events["full"]["n_events"],
    }

    out = MODEL_DIR / "report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    _log(f"report → {out}")

    import mlflow

    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    mlflow.set_experiment(MLFLOW_EXPERIMENT)
    with mlflow.start_run(run_name="backtest-june-2026"):
        mlflow.set_tags({"stage": "backtest", "split": "test", "milestone": "M4"})
        flat = {}
        for h in HORIZONS:
            for who in ("lgbm", "persistence", "lastweek"):
                flat[f"h{h}_{who}_mae_bikes"] = regression[str(h)][who]["mae_bikes"]
            for ev in ("empty", "full"):
                c = classification[ev][str(h)]
                flat[f"h{h}_{ev}_pr_auc"] = c["pr_auc"]
                flat[f"h{h}_{ev}_f1_at_alert"] = c["at_alert_threshold"]["f1"]
        for ev in ("empty", "full"):
            flat[f"event_{ev}_coverage"] = events[ev]["coverage"]
            flat[f"event_{ev}_mean_lead_min"] = events[ev]["mean_lead_minutes"]
            flat[f"event_{ev}_false_alarm_rate"] = events[ev]["false_alarm_rate"]
        mlflow.log_metrics(flat)
        mlflow.log_artifact(str(out))
    _log(f"回測完成，耗時 {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()

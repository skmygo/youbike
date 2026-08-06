"""M4 訓練：LightGBM 回歸（水位）+ 分類（空/滿事件），4 個 horizon，全程進 MLflow。

紀律
- 1–4 月訓練 / 5 月驗證（early stopping 用）/ 6 月測試（訓練完全不碰，只在 evaluate.py 用）
- 兩個 baseline（persistence、上週同日同時段）在同一份驗證集上先跑，模型贏不過就誠實呈現
"""

from __future__ import annotations

import json
import time
from pathlib import Path

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
    RANDOM_SEED,
    TRAIN_SAMPLE_FRAC,
)

REG_PARAMS = dict(
    objective="regression_l1",  # 直接優化 MAE，與評估指標一致
    metric="l1",
    learning_rate=0.07,
    num_leaves=95,
    min_data_in_leaf=200,
    feature_fraction=0.85,
    bagging_fraction=0.8,
    bagging_freq=1,
    lambda_l2=1.0,
    num_threads=3,
    verbosity=-1,
    seed=RANDOM_SEED,
)

CLF_PARAMS = dict(
    objective="binary",
    metric=["average_precision", "auc"],
    learning_rate=0.07,
    num_leaves=95,
    min_data_in_leaf=200,
    feature_fraction=0.85,
    bagging_fraction=0.8,
    bagging_freq=1,
    lambda_l2=1.0,
    num_threads=3,
    verbosity=-1,
    seed=RANDOM_SEED,
)

N_ROUNDS = 500
EARLY_STOP = 40


def _log(msg: str) -> None:
    print(f"[train] {time.strftime('%H:%M:%S')} {msg}", flush=True)


def load_split(name: str, frac: float = 1.0) -> pd.DataFrame:
    path = ML_DIR / f"features_{name}.parquet"
    cols = list(dict.fromkeys(FEATURE_COLS + ["station_id", "ts"]))
    for h in HORIZONS:
        cols += [f"y_ratio_{h}", f"y_bikes_{h}", f"y_docks_{h}", f"bl_lastweek_{h}"]
    df = pd.read_parquet(path, columns=cols)
    if frac < 1.0:
        rng = np.random.default_rng(RANDOM_SEED)
        keep = rng.random(len(df)) < frac
        df = df[keep]
    for c in FEATURE_COLS:
        if c in CATEGORICAL_COLS:
            df[c] = df[c].astype("int16").astype("category")
        else:
            df[c] = df[c].astype("float32")
    _log(f"{name}: {len(df):,} 列, {df.memory_usage(deep=True).sum() / 1e9:.2f} GB")
    return df


def mae(y, p) -> float:
    return float(np.mean(np.abs(np.asarray(y) - np.asarray(p))))


def rmse(y, p) -> float:
    return float(np.sqrt(np.mean((np.asarray(y) - np.asarray(p)) ** 2)))


def prf(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    tp = int(np.sum((y_true == 1) & (y_pred == 1)))
    fp = int(np.sum((y_true == 0) & (y_pred == 1)))
    fn = int(np.sum((y_true == 1) & (y_pred == 0)))
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": p, "recall": r, "f1": f1, "tp": tp, "fp": fp, "fn": fn}


def best_f1_threshold(y_true: np.ndarray, proba: np.ndarray) -> tuple[float, dict]:
    best = (0.5, {"f1": -1.0})
    for t in np.arange(0.05, 0.96, 0.05):
        m = prf(y_true, (proba >= t).astype(int))
        if m["f1"] > best[1]["f1"]:
            best = (float(t), m)
    return best


# ------------------------------------------------------------------- baselines

def baseline_metrics(df: pd.DataFrame) -> dict:
    """persistence（現況延續）與 lastweek（上週同日同時段）在水位與事件上的表現。"""
    out: dict = {}
    for h in HORIZONS:
        y = df[f"y_ratio_{h}"].to_numpy(dtype="float64")
        cap = df["docks_total"].to_numpy(dtype="float64")
        res_h: dict = {}
        for bl_name, pred in (
            ("persistence", df["ratio"].to_numpy(dtype="float64")),
            ("lastweek", df[f"bl_lastweek_{h}"].to_numpy(dtype="float64")),
        ):
            ok = ~np.isnan(pred)
            m = {
                "n": int(ok.sum()),
                "mae_ratio": mae(y[ok], pred[ok]),
                "rmse_ratio": rmse(y[ok], pred[ok]),
                "mae_bikes": mae(y[ok] * cap[ok], pred[ok] * cap[ok]),
            }
            # 事件：把 baseline 的水位預測換算成車輛數再套門檻（規則型警示的等價物）
            for ev, truth, hit in (
                (
                    "empty",
                    (df[f"y_bikes_{h}"].to_numpy() <= EMPTY_BIKES_MAX).astype(int),
                    (pred * cap <= EMPTY_BIKES_MAX).astype(int),
                ),
                (
                    "full",
                    (df[f"y_docks_{h}"].to_numpy() <= FULL_DOCKS_MAX).astype(int),
                    ((1 - pred) * cap <= FULL_DOCKS_MAX).astype(int),
                ),
            ):
                m[ev] = prf(truth[ok], hit[ok])
            res_h[bl_name] = m
        out[str(h)] = res_h
    return out


# --------------------------------------------------------------------- 訓練主體

def train_all(train: pd.DataFrame, valid: pd.DataFrame) -> dict:
    import mlflow

    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    mlflow.set_experiment(MLFLOW_EXPERIMENT)

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    Xtr = train[FEATURE_COLS]
    Xva = valid[FEATURE_COLS]
    summary: dict = {"models": {}, "baselines": {}}

    _log("先跑 baseline（驗證集）…")
    bl = baseline_metrics(valid)
    summary["baselines"] = bl
    with mlflow.start_run(run_name="baselines-valid"):
        mlflow.set_tags({"stage": "baseline", "split": "valid", "milestone": "M4"})
        for h, per in bl.items():
            for name, m in per.items():
                mlflow.log_metric(f"{name}_h{h}_mae_ratio", m["mae_ratio"])
                mlflow.log_metric(f"{name}_h{h}_mae_bikes", m["mae_bikes"])
                mlflow.log_metric(f"{name}_h{h}_empty_f1", m["empty"]["f1"])
                mlflow.log_metric(f"{name}_h{h}_full_f1", m["full"]["f1"])
        mlflow.log_dict(bl, "baselines_valid.json")
    for h in HORIZONS:
        b = bl[str(h)]
        _log(
            f"  h={h}: persistence MAE(bikes)={b['persistence']['mae_bikes']:.3f} | "
            f"lastweek MAE(bikes)={b['lastweek']['mae_bikes']:.3f}"
        )

    # ---- 回歸：水位（ratio） ----
    for h in HORIZONS:
        t0 = time.time()
        ytr = train[f"y_ratio_{h}"].to_numpy(dtype="float32")
        yva = valid[f"y_ratio_{h}"].to_numpy(dtype="float32")
        dtr = lgb.Dataset(Xtr, ytr, categorical_feature=CATEGORICAL_COLS, free_raw_data=False)
        dva = lgb.Dataset(Xva, yva, reference=dtr, categorical_feature=CATEGORICAL_COLS, free_raw_data=False)
        with mlflow.start_run(run_name=f"lgbm-reg-h{h}"):
            mlflow.set_tags({"stage": "train", "task": "regression", "horizon": str(h), "milestone": "M4"})
            mlflow.log_params({**REG_PARAMS, "n_rounds": N_ROUNDS, "early_stop": EARLY_STOP,
                               "train_rows": len(train), "valid_rows": len(valid),
                               "train_frac": TRAIN_SAMPLE_FRAC, "n_features": len(FEATURE_COLS)})
            booster = lgb.train(
                REG_PARAMS, dtr, num_boost_round=N_ROUNDS, valid_sets=[dva],
                callbacks=[lgb.early_stopping(EARLY_STOP, verbose=False), lgb.log_evaluation(100)],
            )
            pv = booster.predict(Xva, num_iteration=booster.best_iteration)
            cap = valid["docks_total"].to_numpy(dtype="float64")
            m = {
                "mae_ratio": mae(yva, pv),
                "rmse_ratio": rmse(yva, pv),
                "mae_bikes": mae(yva * cap, pv * cap),
                "best_iteration": int(booster.best_iteration),
            }
            base_mae = bl[str(h)]["persistence"]["mae_bikes"]
            m["improve_vs_persistence_pct"] = 100 * (base_mae - m["mae_bikes"]) / base_mae
            mlflow.log_metrics({k: v for k, v in m.items() if isinstance(v, (int, float))})
            path = MODEL_DIR / f"lgbm_reg_h{h}.txt"
            booster.save_model(str(path), num_iteration=booster.best_iteration)
            mlflow.log_artifact(str(path))
            imp = sorted(zip(FEATURE_COLS, booster.feature_importance("gain")),
                         key=lambda x: -x[1])[:20]
            mlflow.log_dict({k: float(v) for k, v in imp}, f"importance_reg_h{h}.json")
            summary["models"][f"reg_h{h}"] = m
        _log(f"  reg h={h}: MAE(bikes)={m['mae_bikes']:.3f} "
             f"(persistence {base_mae:.3f}, {m['improve_vs_persistence_pct']:+.1f}%) "
             f"iter={m['best_iteration']} {time.time()-t0:.0f}s")
        del dtr, dva

    # ---- 分類：空 / 滿事件 ----
    for ev, col, thr in (("empty", "y_bikes_{}", EMPTY_BIKES_MAX), ("full", "y_docks_{}", FULL_DOCKS_MAX)):
        for h in HORIZONS:
            t0 = time.time()
            ytr = (train[col.format(h)].to_numpy() <= thr).astype("int8")
            yva = (valid[col.format(h)].to_numpy() <= thr).astype("int8")
            pos = float(ytr.mean())
            dtr = lgb.Dataset(Xtr, ytr, categorical_feature=CATEGORICAL_COLS, free_raw_data=False)
            dva = lgb.Dataset(Xva, yva, reference=dtr, categorical_feature=CATEGORICAL_COLS, free_raw_data=False)
            with mlflow.start_run(run_name=f"lgbm-clf-{ev}-h{h}"):
                mlflow.set_tags({"stage": "train", "task": f"clf_{ev}", "horizon": str(h), "milestone": "M4"})
                mlflow.log_params({**{k: v for k, v in CLF_PARAMS.items() if k != "metric"},
                                   "metric": "average_precision,auc", "n_rounds": N_ROUNDS,
                                   "pos_rate": round(pos, 5), "train_rows": len(train)})
                booster = lgb.train(
                    CLF_PARAMS, dtr, num_boost_round=N_ROUNDS, valid_sets=[dva],
                    callbacks=[lgb.early_stopping(EARLY_STOP, verbose=False), lgb.log_evaluation(100)],
                )
                proba = booster.predict(Xva, num_iteration=booster.best_iteration)
                t_best, m_best = best_f1_threshold(yva, proba)
                m_alert = prf(yva, (proba >= ALERT_PROBA_THRESHOLD).astype(int))
                from sklearn.metrics import average_precision_score, roc_auc_score

                m = {
                    "pos_rate": pos,
                    "pr_auc": float(average_precision_score(yva, proba)),
                    "roc_auc": float(roc_auc_score(yva, proba)),
                    "best_threshold": t_best,
                    "best_f1": m_best["f1"],
                    "best_precision": m_best["precision"],
                    "best_recall": m_best["recall"],
                    "alert_f1": m_alert["f1"],
                    "alert_precision": m_alert["precision"],
                    "alert_recall": m_alert["recall"],
                    "best_iteration": int(booster.best_iteration),
                }
                mlflow.log_metrics(m)
                path = MODEL_DIR / f"lgbm_clf_{ev}_h{h}.txt"
                booster.save_model(str(path), num_iteration=booster.best_iteration)
                mlflow.log_artifact(str(path))
                summary["models"][f"clf_{ev}_h{h}"] = m
            _log(f"  clf {ev} h={h}: PR-AUC={m['pr_auc']:.3f} bestF1={m['best_f1']:.3f}@{t_best:.2f} "
                 f"alertF1={m['alert_f1']:.3f} iter={m['best_iteration']} {time.time()-t0:.0f}s")
            del dtr, dva

    (ML_DIR / "train_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    # 給線上服務用的 threshold 表
    thresholds = {
        f"clf_{ev}_h{h}": summary["models"][f"clf_{ev}_h{h}"]["best_threshold"]
        for ev in ("empty", "full")
        for h in HORIZONS
    }
    (MODEL_DIR / "thresholds.json").write_text(json.dumps(thresholds, indent=2), encoding="utf-8")
    (MODEL_DIR / "feature_cols.json").write_text(
        json.dumps({"features": FEATURE_COLS, "categorical": CATEGORICAL_COLS, "horizons": list(HORIZONS)},
                   indent=2), encoding="utf-8")
    return summary


def main() -> None:
    t0 = time.time()
    train = load_split("train", TRAIN_SAMPLE_FRAC)
    valid = load_split("valid")
    train_all(train, valid)
    _log(f"訓練完成，總耗時 {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()

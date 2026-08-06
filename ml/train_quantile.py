"""S2 分位數回歸：給預測一個誠實的區間，而不是一個假裝很準的點。

主模型（regression_l1）給的是中位數式的點預測；這裡另外訓練 10% 與 90% 兩個
分位數模型，前端就能把「預測帶」畫成真的帶。驗證集上會順便量**實際覆蓋率**
（真值落在區間內的比例，理想 80%）——區間寬不寬、準不準，數字擺出來讓人自己判斷。

模型檔：`lgbm_reg_q10_h{h}.txt` / `lgbm_reg_q90_h{h}.txt`
"""

from __future__ import annotations

import gc
import json
import time

import lightgbm as lgb
import numpy as np

from ml.config import (
    CATEGORICAL_COLS,
    FEATURE_COLS,
    HORIZONS,
    ML_DIR,
    MLFLOW_EXPERIMENT,
    MLFLOW_TRACKING_URI,
    MODEL_DIR,
    RANDOM_SEED,
    TRAIN_SAMPLE_FRAC,
    VALID_SAMPLE_FRAC,
)
from ml.train import load_split

QUANTILES = (0.1, 0.9)
N_ROUNDS = 350          # 分位數回歸比 L1 慢，回合數收斂即可（早停會提前收手）
EARLY_STOP = 30

BASE_PARAMS = dict(
    objective="quantile",
    metric="quantile",
    learning_rate=0.08,
    num_leaves=63,           # 比主模型小一點：區間模型不需要那麼細
    min_data_in_leaf=300,
    feature_fraction=0.85,
    bagging_fraction=0.8,
    bagging_freq=1,
    lambda_l2=1.0,
    num_threads=3,
    verbosity=-1,
    seed=RANDOM_SEED,
)


def _log(msg: str) -> None:
    print(f"[quantile] {time.strftime('%H:%M:%S')} {msg}", flush=True)


def main() -> None:
    t0 = time.time()
    import mlflow

    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    mlflow.set_experiment(MLFLOW_EXPERIMENT)

    train = load_split("train", TRAIN_SAMPLE_FRAC)
    valid = load_split("valid", VALID_SAMPLE_FRAC)
    Xtr, Xva = train[FEATURE_COLS], valid[FEATURE_COLS]
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    summary: dict = {}
    for h in HORIZONS:
        ytr = train[f"y_ratio_{h}"].to_numpy(dtype="float32")
        yva = valid[f"y_ratio_{h}"].to_numpy(dtype="float32")
        cap = valid["docks_total"].to_numpy(dtype="float64")
        preds = {}
        for q in QUANTILES:
            t1 = time.time()
            params = {**BASE_PARAMS, "alpha": q}
            dtr = lgb.Dataset(Xtr, ytr, categorical_feature=CATEGORICAL_COLS)
            dva = lgb.Dataset(Xva, yva, reference=dtr, categorical_feature=CATEGORICAL_COLS)
            with mlflow.start_run(run_name=f"lgbm-q{int(q * 100)}-h{h}"):
                mlflow.set_tags({"stage": "train", "task": "quantile",
                                 "quantile": str(q), "horizon": str(h), "milestone": "S2"})
                mlflow.log_params({**params, "n_rounds": N_ROUNDS, "train_rows": len(train)})
                booster = lgb.train(
                    params, dtr, num_boost_round=N_ROUNDS, valid_sets=[dva],
                    callbacks=[lgb.early_stopping(EARLY_STOP, verbose=False),
                               lgb.log_evaluation(100)],
                )
                p = np.clip(booster.predict(Xva, num_iteration=booster.best_iteration), 0.0, 1.0)
                preds[q] = p
                path = MODEL_DIR / f"lgbm_reg_q{int(q * 100)}_h{h}.txt"
                booster.save_model(str(path), num_iteration=booster.best_iteration)
                mlflow.log_artifact(str(path))
                mlflow.log_metric("best_iteration", booster.best_iteration)
            _log(f"  q={q} h={h}: iter={booster.best_iteration} {time.time() - t1:.0f}s")
            del dtr, dva, booster
            gc.collect()

        lo, hi = preds[0.1], preds[0.9]
        # 分位數回歸不保證 lo ≤ hi（兩個模型各訓各的），畫圖前先排好
        lo2, hi2 = np.minimum(lo, hi), np.maximum(lo, hi)
        covered = float(np.mean((yva >= lo2) & (yva <= hi2)))
        width_bikes = float(np.mean((hi2 - lo2) * cap))
        crossed = float(np.mean(lo > hi))
        summary[str(h)] = {
            "coverage": covered,
            "target_coverage": 0.8,
            "mean_width_bikes": width_bikes,
            "crossed_rate": crossed,
        }
        _log(f"h={h}: 覆蓋率 {covered:.1%}（目標 80%）、平均帶寬 {width_bikes:.2f} 台、"
             f"交叉率 {crossed:.2%}")

    (ML_DIR / "quantile_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    with mlflow.start_run(run_name="quantile-coverage-summary"):
        mlflow.set_tags({"stage": "eval", "task": "quantile", "milestone": "S2"})
        for h, m in summary.items():
            mlflow.log_metric(f"h{h}_coverage", m["coverage"])
            mlflow.log_metric(f"h{h}_mean_width_bikes", m["mean_width_bikes"])
        mlflow.log_dict(summary, "quantile_summary.json")
    _log(f"完成，總耗時 {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()

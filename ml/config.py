"""M4 ML 設定：路徑、切分、目標與事件門檻（全流程單一事實來源）。"""

from __future__ import annotations

import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("YOUBIKE_DATA_DIR", "_out")).resolve()
HISTORY_GLOB = str(DATA_DIR / "history" / "snapshots_*.parquet")
STATIONS_PARQUET = str(DATA_DIR / "serving" / "stations.parquet")

ML_DIR = DATA_DIR / "ml"
MODEL_DIR = DATA_DIR / "models"

# 30 分槽 → horizon 以「幾個槽」表示
SLOT_MINUTES = 30
HORIZONS = (30, 60, 120, 180)  # 分鐘


def horizon_steps(minutes: int) -> int:
    return minutes // SLOT_MINUTES


# 時間序切分（不洗牌，嚴防未來洩漏）
TRAIN_RANGE = ("2026-01-01", "2026-04-30")
VALID_RANGE = ("2026-05-01", "2026-05-31")
TEST_RANGE = ("2026-06-01", "2026-06-30")

# 事件定義（對齊 WP4 警示語彙）
EMPTY_BIKES_MAX = 1  # 可借 ≤1 視為「無車」
FULL_DOCKS_MAX = 1  # 可還 ≤1 視為「滿位」
ALERT_PROBA_THRESHOLD = 0.70  # 預測型警示門檻（60 分內機率 ≥70%）

# 訓練抽樣（記憶體 14GB，訓練集全量 8.9M 列太吃；固定種子可重現）
TRAIN_SAMPLE_FRAC = float(os.environ.get("YOUBIKE_TRAIN_FRAC", "0.35"))
RANDOM_SEED = 42

# 站點行為分群
N_CLUSTERS = 6

MLFLOW_TRACKING_URI = os.environ.get(
    "MLFLOW_TRACKING_URI", "http://192.168.50.190:5000"
)
MLFLOW_EXPERIMENT = os.environ.get("YOUBIKE_MLFLOW_EXPERIMENT", "youbike-hackathon")

FEATURE_COLS = [
    # 當下狀態
    "ratio",
    "bikes",
    "docks_total",
    # lag（30m ~ 一週前）
    "ratio_lag1",
    "ratio_lag2",
    "ratio_lag3",
    "ratio_lag4",
    "ratio_lag6",
    "ratio_lag12",
    "ratio_lag24",
    "ratio_lag48",
    "ratio_lag336",
    # 動能
    "d1",
    "d2",
    "d4",
    # rolling
    "roll_mean_4",
    "roll_std_4",
    "roll_mean_12",
    "roll_std_12",
    "roll_mean_48",
    "roll_min_48",
    "roll_max_48",
    # 時間
    "slot_of_day",
    "dow",
    "is_weekend",
    "is_holiday",
    "minutes_since_midnight",
    # 站點靜態
    "capacity",
    "lat",
    "lon",
    "cluster_id",
    "district_id",
    # 歷史常態與偏離（只用訓練期統計，無未來洩漏）
    "norm_ratio",
    "norm_dev",
    "norm_empty_rate",
    "norm_full_rate",
    # 鄰域 / 群體同步訊號
    "district_ratio",
    "cluster_ratio",
    "neigh_ratio",
    "neigh_dev",
    # 目前已持續空/滿多久（槽數）
    "empty_streak",
    "full_streak",
]

CATEGORICAL_COLS = ["cluster_id", "district_id", "dow", "slot_of_day"]

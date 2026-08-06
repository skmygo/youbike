"""路徑與環境設定。

容器內 `/data` 是共用 volume：dagster 寫、api 讀。兩邊都不開同一顆 .duckdb
檔（會撞檔案鎖），一律以 parquet 交換。
"""
import os
from pathlib import Path

DATA_DIR = Path(os.getenv("YOUBIKE_DATA_DIR", "/data"))

# pipeline 物化的服務層（小檔、頻繁更新，原子 rename 寫入）
SERVING_DIR = DATA_DIR / "serving"
# 歷史大表（按月分檔，開機時從 S3 引導）
HISTORY_DIR = DATA_DIR / "history"
# 模型檔與回測報告
MODEL_DIR = DATA_DIR / "models"

# 前端建置產物（Dockerfile 會把 web/dist 複製到這）
WEB_DIST = Path(os.getenv("YOUBIKE_WEB_DIST", "/app/web_dist"))

# 服務層檔案（pipeline 產、api 讀）
LATEST_PARQUET = SERVING_DIR / "latest.parquet"          # 每站最新一筆狀態
STATIONS_PARQUET = SERVING_DIR / "stations.parquet"      # 站點主檔
ALERTS_PARQUET = SERVING_DIR / "alerts.parquet"          # 規則型警示
HOURLY_PARQUET = SERVING_DIR / "hourly.parquet"          # 站×時段統計
FORECAST_PARQUET = SERVING_DIR / "forecast.parquet"      # 模型預測
DISPATCH_PARQUET = SERVING_DIR / "dispatch.parquet"      # 調度建議
REPORT_JSON = MODEL_DIR / "report.json"                  # 6 月回測報告

# 歷史快照 parquet glob（read_parquet 直接吃）
HISTORY_GLOB = str(HISTORY_DIR / "snapshots_*.parquet")
# 近期快照（pipeline 每 10 分鐘追加，與歷史合併查詢）
RECENT_GLOB = str(SERVING_DIR / "recent_*.parquet")

TZ = "Asia/Taipei"

#!/usr/bin/env bash
# 容器入口：先做資料引導（缺檔才從 Garage S3 拉），再依角色啟動服務。
#   entrypoint.sh api        → FastAPI（前端靜態檔一併由它服務）
#   entrypoint.sh dagster    → Dagster webserver + daemon
#   entrypoint.sh <其他>     → 直接當指令執行
set -euo pipefail

DATA_DIR="${YOUBIKE_DATA_DIR:-/data}"
mkdir -p "$DATA_DIR"/{serving,history,models,raw,dagster}

bootstrap() {
  if [ -z "${S3_ACCESS_KEY:-}" ]; then
    echo "[bootstrap] 未設定 S3_ACCESS_KEY，跳過資料引導"
    return 0
  fi
  if compgen -G "$DATA_DIR/history/snapshots_*.parquet" > /dev/null; then
    echo "[bootstrap] 歷史資料已存在，跳過下載"
    return 0
  fi
  echo "[bootstrap] 從 S3 引導歷史資料…"
  python -m pipeline.bootstrap || echo "[bootstrap] 失敗（不阻擋啟動，API 走 degraded 模式）"
}

case "${1:-api}" in
  api)
    bootstrap
    exec uvicorn api.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'
    ;;
  dagster)
    bootstrap
    dagster-daemon run &
    exec dagster-webserver -h 0.0.0.0 -p 3000 -m pipeline.defs
    ;;
  *)
    exec "$@"
    ;;
esac

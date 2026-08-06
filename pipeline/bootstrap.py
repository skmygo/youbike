"""容器資料引導：把 S3 上的歷史 parquet / 站點主檔 / 模型檔拉到本機 volume。

只補缺檔，已存在就跳過（容器重啟不重下 500MB）。任何失敗都不阻擋服務啟動，
API 會走 degraded 模式（前端顯示資料尚未就緒）。
"""
from __future__ import annotations

import sys
from pathlib import Path

from api import settings
from pipeline import s3util

# S3 key prefix → 本機目錄；第三欄 = 每次啟動都重抓
# models/ 會隨訓練更新，若沿用「檔案存在就跳過」，重新部署永遠拿不到新模型
LAYOUT = [
    ("history/", settings.HISTORY_DIR, False),
    ("serving/", settings.SERVING_DIR, False),
    ("models/", settings.MODEL_DIR, True),
]


def main() -> int:
    try:
        keys = s3util.list_keys()
    except Exception as e:  # 沒 key / S3 不通
        print(f"[bootstrap] 無法列出 S3 物件：{e}", file=sys.stderr)
        return 1

    if not keys:
        print("[bootstrap] S3 上沒有資料，跳過")
        return 0

    n_ok = n_skip = 0
    for key in keys:
        target: Path | None = None
        always = False
        for prefix, dest, refresh in LAYOUT:
            if key.startswith(prefix):
                target, always = dest / key[len(prefix):], refresh
                break
        if target is None or key.endswith("/"):
            continue
        if target.exists() and not always:
            n_skip += 1
            continue
        try:
            s3util.download(key, target)
            n_ok += 1
        except Exception as e:
            print(f"[bootstrap] 下載失敗 {key}: {e}", file=sys.stderr)

    print(f"[bootstrap] 完成：新下載 {n_ok} 檔、既有 {n_skip} 檔")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

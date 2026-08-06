"""把訓練產物上傳 Garage S3 的 `models/`，容器啟動時 bootstrap 會拉下來。

上傳內容：12 個 LightGBM 模型 + thresholds.json + feature_cols.json + report.json，
外加線上推論要用的 4 張輔助表（站點 / 歷史常態 / 鄰居 / 假日）——
輔助表跟模型放同一個前綴，部署端只要拉 models/ 就湊得齊。

用法（需要 .env 裡的 S3 金鑰）：
    set -a; source .env; set +a
    .venv/bin/python -m ml.upload_models
"""

from __future__ import annotations

from pathlib import Path

from ml.config import DATA_DIR, MODEL_DIR
from pipeline import s3util

AUX_NAMES = ("stations", "norms", "neighbors", "holidays")


def collect() -> list[Path]:
    files = [p for p in sorted(MODEL_DIR.glob("*")) if p.is_file()]
    have = {p.name for p in files}
    for n in AUX_NAMES:
        p = DATA_DIR / "ml" / "serving" / f"ml_{n}.parquet"
        if p.exists() and p.name not in have:
            files.append(p)
    return files


def main() -> int:
    files = collect()
    if not files:
        print("[upload] models/ 是空的，沒東西可傳")
        return 1
    total = 0
    for p in files:
        s3util.upload(p, f"models/{p.name}")
        total += p.stat().st_size
    print(f"[upload] 完成 {len(files)} 個檔案，共 {total / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

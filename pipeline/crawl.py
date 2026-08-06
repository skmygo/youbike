"""新北市 YouBike2.0 即時快照爬蟲（容器版，輸出 parquet）。

與歷史資料的接法：歷史 `station_id` 是 build_duckdb.py 以「場站名稱」為 key
產生的流水號，所以即時資料也用站名對應回去（站名先套歷史的修正表）。歷史沒
見過的新站另外配號（>= NEW_ID_BASE），不會撞到既有 id。

輸出 `/data/raw/snap_<YYYYmmddTHHMM>.parquet`（一次一檔、小檔），由 dagster
的 `snapshots_recent` 資產合併成服務層 parquet。
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import pandas as pd

from api import settings

API = ("https://data.ntpc.gov.tw/api/datasets/"
       "010e5b15-3823-4b20-b401-b1cf000550c5/json?page=0&size=3000")

# 與 build_duckdb.py 同一份修正表（Big5 匯出缺字 + 一次無縫更名）。
# 即時來源給的是正確站名，這裡只需要處理「歷史用新名、即時給舊名」的情況。
NAME_FIXES = {
    "美麗新淡海影城": "新市五義山路口",
}

NEW_ID_BASE = 900000


def fetch(retries: int = 3) -> list[dict]:
    for i in range(retries):
        try:
            req = urllib.request.Request(API, headers={"User-Agent": "youbike-hackathon/1.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except Exception as e:
            if i == retries - 1:
                raise
            print(f"[crawl] 抓取失敗（{e}），{15 * (i + 1)} 秒後重試", file=sys.stderr)
            time.sleep(15 * (i + 1))
    return []


def _name_map() -> dict[str, int]:
    """站名 → station_id（來自服務層站點主檔）。"""
    p = settings.STATIONS_PARQUET
    if not p.exists():
        return {}
    df = pd.read_parquet(p, columns=["station_id", "name"])
    return dict(zip(df["name"], df["station_id"].astype(int)))


def normalize(rows: list[dict], ts: datetime) -> pd.DataFrame:
    recs = []
    for r in rows:
        name = str(r.get("sna", "")).removeprefix("YouBike2.0_").strip()
        name = NAME_FIXES.get(name, name)
        if not name:
            continue
        try:
            recs.append({
                "name": name,
                "district": str(r.get("sarea", "")).strip() or None,
                "bikes": int(r.get("sbi_quantity") or 0),
                "docks_avail": int(r.get("bemp") or 0),
                "docks_total": int(r.get("tot_quantity") or 0),
                "lon": float(r.get("lng") or 0) or None,
                "lat": float(r.get("lat") or 0) or None,
                "sno": str(r.get("sno", "")),
            })
        except (TypeError, ValueError):
            continue

    df = pd.DataFrame(recs).drop_duplicates(subset=["name"], keep="last")
    # 對齊 30 分鐘槽，與歷史同節奏（即時每 10 分鐘爬，槽內保留最新）
    df["ts"] = pd.Timestamp(ts).floor("30min")
    df["fetched_at"] = pd.Timestamp(ts)

    mapping = _name_map()
    next_id = max([*mapping.values(), NEW_ID_BASE - 1]) + 1 if mapping else NEW_ID_BASE
    ids = []
    for n in df["name"]:
        if n not in mapping:
            mapping[n] = next_id
            next_id += 1
        ids.append(mapping[n])
    df["station_id"] = ids

    return df[["station_id", "ts", "bikes", "docks_avail", "docks_total",
               "name", "district", "lon", "lat", "sno", "fetched_at"]]


def run(now: datetime | None = None) -> Path:
    now = now or datetime.now()
    df = normalize(fetch(), now)
    out_dir = settings.DATA_DIR / "raw"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"snap_{now:%Y%m%dT%H%M}.parquet"
    tmp = out.with_suffix(".parquet.part")
    df.to_parquet(tmp, index=False, compression="zstd")
    tmp.replace(out)
    print(f"[crawl] {now:%Y-%m-%d %H:%M} 寫入 {len(df)} 站 → {out}")
    return out


if __name__ == "__main__":
    run()

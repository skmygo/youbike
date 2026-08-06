#!/usr/bin/env python3
"""從新北市資料開放平臺抓 YouBike2.0 即時資料，續接 資料集/ 的快照格式。

資料集：新北市公共自行車租賃系統(YouBike2.0)
    https://data.ntpc.gov.tw/datasets/010e5b15-3823-4b20-b401-b1cf000550c5
單次執行抓一個快照（全市約 1,586 站），輸出與黑客松檔相同的 9 欄、
UTF-8 編碼（黑客松原檔是 Big5，這裡不再沿用），依月份追加到：
    資料集/即時爬取_YYYYMM.csv

排程（對齊既有資料的 30 分鐘快照節奏）：
    */30 * * * * cd /home/sk/work/youbike && python3 crawl_realtime.py >> crawl.log 2>&1

之後要進 youbike.duckdb，在 build_duckdb.py 的 raw_all 視圖再 UNION 一段
read_csv('{DATA}/即時爬取_*.csv', ...)（時間格式同新北AWS檔，且已是 UTF-8）。
"""
import csv
import json
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "資料集"
API = ("https://data.ntpc.gov.tw/api/datasets/"
       "010e5b15-3823-4b20-b401-b1cf000550c5/json?page=0&size=3000")
HEADER = ["日期", "城市", "行政區", "場站名稱",
          "總車柱數", "可借車數", "可還位數", "經度", "緯度"]


def fetch(retries: int = 3) -> list[dict]:
    for i in range(retries):
        try:
            with urllib.request.urlopen(API, timeout=60) as resp:
                return json.load(resp)
        except Exception as e:
            if i == retries - 1:
                raise
            print(f"抓取失敗（{e}），{15 * (i + 1)} 秒後重試", file=sys.stderr)
            time.sleep(15 * (i + 1))
    return []


def main() -> None:
    now = datetime.now()
    rows = fetch()
    out = OUT_DIR / f"即時爬取_{now:%Y%m}.csv"
    new_file = not out.exists()
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    with out.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(HEADER)
        for r in sorted(rows, key=lambda r: r["sno"]):
            w.writerow([ts, r["scity"], r["sarea"],
                        r["sna"].removeprefix("YouBike2.0_"),
                        r["tot_quantity"], r["sbi_quantity"], r["bemp"],
                        r["lng"], r["lat"]])
    print(f"{ts} 寫入 {len(rows)} 站 → {out.name}")


if __name__ == "__main__":
    main()

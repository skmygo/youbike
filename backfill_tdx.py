#!/usr/bin/env python3
"""用 TDX 歷史 API 回補新北 YouBike2.0 快照（例如 2026-07 之後的缺口）。

新北開放平台只提供「當下」狀態，無歷史；TDX（運輸資料流通服務平臺）的
歷史即時車位 API 可逐日回溯（介接指南範例抓到 2022 年）：
    https://tdx.transportdata.tw/api/historical/v2/Historical/Bike/Availability/City/NewTaipei

需要免費 TDX 一般會員金鑰（https://tdx.transportdata.tw 註冊 → 會員中心 → 取得 API 金鑰）：
    export TDX_CLIENT_ID=xxx TDX_CLIENT_SECRET=xxx

用法（日期含頭含尾，逐日抓）：
    python3 backfill_tdx.py --start 2026-07-01 --end 2026-08-05

流程：站點主檔以新北開放平台為準（站名/行政區/座標與既有資料一致），
TDX 站點主檔補退役站；每站每 30 分鐘槽取最後一筆降採樣，輸出與既有檔
相同 9 欄、UTF-8，依月份追加到 資料集/TDX回補_YYYYMM.csv。
「總車柱數」與原始資料同語意（＝可借＋可還）。
已完成日期記在 資料集/.tdx_backfill_done，中斷重跑會自動略過。
"""
import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "資料集"
DONE_FILE = OUT_DIR / ".tdx_backfill_done"
HEADER = ["日期", "城市", "行政區", "場站名稱",
          "總車柱數", "可借車數", "可還位數", "經度", "緯度"]

NTPC_API = ("https://data.ntpc.gov.tw/api/datasets/"
            "010e5b15-3823-4b20-b401-b1cf000550c5/json?page=0&size=3000")
TDX = "https://tdx.transportdata.tw"
TOKEN_URL = f"{TDX}/auth/realms/TDXConnect/protocol/openid-connect/token"
STATION_URL = f"{TDX}/api/basic/v2/Bike/Station/City/NewTaipei?$format=JSON"
HIS_URL = (f"{TDX}/api/historical/v2/Historical/Bike/Availability/City/NewTaipei"
           "?Dates={d}&$format=JSON")


def get_token() -> str:
    cid, secret = os.environ.get("TDX_CLIENT_ID"), os.environ.get("TDX_CLIENT_SECRET")
    if not cid or not secret:
        sys.exit("請先 export TDX_CLIENT_ID / TDX_CLIENT_SECRET（免費註冊 tdx.transportdata.tw）")
    body = urllib.parse.urlencode({"grant_type": "client_credentials",
                                   "client_id": cid, "client_secret": secret}).encode()
    with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=body), timeout=30) as r:
        return json.load(r)["access_token"]


def http_get(url: str, token: str, timeout: int = 600) -> bytes:
    req = urllib.request.Request(url, headers={"authorization": f"Bearer {token}",
                                               "accept-encoding": "gzip"})
    for i in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    import gzip
                    raw = gzip.decompress(raw)
                return raw
        except urllib.error.HTTPError as e:
            if e.code == 429 and i < 3:          # 流量限制，等一分鐘再試
                print("  429 rate limit，睡 65 秒", file=sys.stderr)
                time.sleep(65)
                continue
            raise
    raise RuntimeError("unreachable")


def station_map(token: str) -> dict[str, tuple]:
    """sno → (行政區, 站名, 經度, 緯度)。新北開放平台為主、TDX 主檔補缺。"""
    m = {}
    with urllib.request.urlopen(NTPC_API, timeout=60) as r:
        for s in json.load(r):
            m[s["sno"]] = (s["sarea"], s["sna"].removeprefix("YouBike2.0_"),
                           s["lng"], s["lat"])
    for s in json.loads(http_get(STATION_URL, token)):
        sno = s["StationUID"].removeprefix("NWT")
        if sno not in m:
            addr = (s.get("StationAddress") or {}).get("Zh_tw") or ""
            dist = (re.search(r"新北市(\S+?區)", addr) or [None, ""])[1]
            pos = s.get("StationPosition") or {}
            m[sno] = (dist, (s["StationName"]["Zh_tw"]).removeprefix("YouBike2.0_"),
                      pos.get("PositionLon", ""), pos.get("PositionLat", ""))
    return m


def fetch_day(token: str, day: str) -> dict[tuple, tuple]:
    """回傳 {(sno, 30分槽): (SrcUpdateTime, 可借, 可還)}，每槽取最後一筆。

    整天 JSON 可能上百 MB，用 raw_decode 逐物件掃、不留整串 list。
    """
    text = http_get(HIS_URL.format(d=day), token).decode("utf-8")
    dec = json.JSONDecoder()
    slots: dict[tuple, tuple] = {}
    i, n = text.find("{"), len(text)
    n_rec = 0
    while 0 <= i < n:
        obj, end = dec.raw_decode(text, i)
        n_rec += 1
        ts = datetime.fromisoformat(obj["SrcUpdateTime"]).replace(tzinfo=None)
        key = (obj["StationUID"].removeprefix("NWT"),
               ts.replace(minute=ts.minute // 30 * 30, second=0))
        cur = slots.get(key)
        if cur is None or ts > cur[0]:
            slots[key] = (ts, obj["AvailableRentBikes"], obj["AvailableReturnBikes"])
        j = text.find("{", end)
        i = j
    print(f"  原始 {n_rec:,} 筆 → 30 分槽 {len(slots):,} 筆")
    return slots


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="YYYY-MM-DD（含）")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD（含）")
    args = ap.parse_args()
    d0, d1 = date.fromisoformat(args.start), date.fromisoformat(args.end)

    done = set(DONE_FILE.read_text().split()) if DONE_FILE.exists() else set()
    token = get_token()
    smap = station_map(token)
    print(f"站點主檔 {len(smap)} 站")

    unmapped: set[str] = set()
    d = d0
    while d <= d1:
        day = d.isoformat()
        if day in done:
            print(f"{day} 已完成，略過")
            d += timedelta(days=1)
            continue
        print(f"{day} 抓取中…")
        slots = fetch_day(token, day)
        if slots:
            out = OUT_DIR / f"TDX回補_{day[:7].replace('-', '')}.csv"
            new_file = not out.exists()
            with out.open("a", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                if new_file:
                    w.writerow(HEADER)
                for (sno, _slot), (ts, rent, ret) in sorted(slots.items(),
                                                            key=lambda kv: (kv[0][1], kv[0][0])):
                    st = smap.get(sno)
                    if st is None:
                        unmapped.add(sno)
                        continue
                    dist, name, lng, lat = st
                    w.writerow([ts.strftime("%Y-%m-%d %H:%M:%S"), "新北市", dist, name,
                                int(rent) + int(ret), rent, ret, lng, lat])
        else:
            print(f"  {day} 無資料（可能早於 TDX 保存範圍）")
        with DONE_FILE.open("a") as f:
            f.write(day + "\n")
        d += timedelta(days=1)
        time.sleep(2)                       # 對 TDX 客氣一點

    if unmapped:
        print(f"注意：{len(unmapped)} 個站號在兩份主檔都查不到，已跳過：{sorted(unmapped)[:10]}…")
    print("完成")


if __name__ == "__main__":
    main()

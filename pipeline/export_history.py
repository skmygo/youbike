"""把本機 youbike.duckdb（6 個月歷史）匯出成部署用 parquet，並上傳 Garage S3。

只在本機跑一次（資料在本機、1,332 萬筆）。產出：

    history/snapshots_YYYYMM.parquet   月分檔快照事實表
    serving/stations.parquet           站點主檔
    serving/hourly.parquet             站 × 星期 × 半小時槽 的歷史統計（基準線 + /api/stats）
    serving/latest.parquet             最後一筆快照（即時資料進來前的地圖 fallback）

用法：
    uv run --with duckdb --with boto3 python -m pipeline.export_history [--no-upload]
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent.parent
DB = HERE / "ref_data" / "youbike.duckdb"
OUT = HERE / "_out"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--db", default=str(DB))
    args = ap.parse_args()

    (OUT / "history").mkdir(parents=True, exist_ok=True)
    (OUT / "serving").mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(args.db, read_only=True)

    months = [r[0] for r in con.execute(
        "SELECT DISTINCT strftime(ts, '%Y%m') AS m FROM snapshots ORDER BY 1"
    ).fetchall()]
    print(f"月份：{months}")

    produced: list[tuple[Path, str]] = []

    for m in months:
        p = OUT / "history" / f"snapshots_{m}.parquet"
        con.execute(f"""
            COPY (
                SELECT station_id, ts, bikes, docks_avail, docks_total
                FROM snapshots WHERE strftime(ts, '%Y%m') = '{m}'
                ORDER BY station_id, ts
            ) TO '{p}' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 200000)
        """)
        print(f"  {p.name}  {p.stat().st_size / 1e6:.1f} MB")
        produced.append((p, f"history/{p.name}"))

    # 站點主檔
    p = OUT / "serving" / "stations.parquet"
    con.execute(f"""
        COPY (
            SELECT station_id, name, district, lon, lat, capacity_docks,
                   first_ts, last_ts, n_snapshots, always_empty
            FROM stations ORDER BY station_id
        ) TO '{p}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """)
    print(f"  {p.name}  {p.stat().st_size / 1e3:.0f} KB")
    produced.append((p, "serving/stations.parquet"))

    # 歷史型態：站 × isodow × 半小時槽（0..47）的中位數 / 空滿率 → 基準線與 /api/stats/hourly
    p = OUT / "serving" / "hourly.parquet"
    con.execute(f"""
        COPY (
            SELECT station_id,
                   isodow(ts)::TINYINT AS isodow,
                   (EXTRACT(hour FROM ts) * 2 + (EXTRACT(minute FROM ts) >= 30)::INT)::TINYINT AS slot,
                   count(*)::INT                                       AS n,
                   round(median(bikes), 2)                             AS bikes_p50,
                   round(quantile_cont(bikes, 0.1), 2)                 AS bikes_p10,
                   round(quantile_cont(bikes, 0.9), 2)                 AS bikes_p90,
                   round(avg(bikes), 2)                                AS bikes_mean,
                   round(avg(CASE WHEN bikes = 0 THEN 1 ELSE 0 END), 4)        AS empty_rate,
                   round(avg(CASE WHEN docks_avail = 0 THEN 1 ELSE 0 END), 4)  AS full_rate,
                   round(avg(bikes / nullif(docks_total, 0)), 4)       AS occ_rate
            FROM snapshots
            GROUP BY 1, 2, 3
            ORDER BY 1, 2, 3
        ) TO '{p}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """)
    print(f"  {p.name}  {p.stat().st_size / 1e6:.1f} MB")
    produced.append((p, "serving/hourly.parquet"))

    # 最後一筆快照（即時資料尚未進來時的地圖 fallback）
    p = OUT / "serving" / "latest.parquet"
    con.execute(f"""
        COPY (
            SELECT s.station_id, s.ts, s.bikes, s.docks_avail, s.docks_total,
                   st.name, st.district, st.lon, st.lat, s.ts AS fetched_at
            FROM snapshots s JOIN stations st USING (station_id)
            WHERE s.ts = (SELECT max(ts) FROM snapshots)
            ORDER BY s.station_id
        ) TO '{p}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """)
    print(f"  {p.name}  {p.stat().st_size / 1e3:.0f} KB")
    produced.append((p, "serving/latest.parquet"))

    con.close()

    total = sum(pp.stat().st_size for pp, _ in produced)
    print(f"總計 {len(produced)} 檔、{total / 1e6:.0f} MB")

    if args.no_upload:
        return
    os.environ.setdefault("S3_BUCKET", "youbike")
    from pipeline import s3util

    for local, key in produced:
        s3util.upload(local, key)
    print("上傳完成")


if __name__ == "__main__":
    main()

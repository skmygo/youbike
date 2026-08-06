#!/usr/bin/env python3
"""把 資料集/ 的 12 個 CSV 整理成 youbike.duckdb。

用法：
    uv run --with duckdb python build_duckdb.py [--big5-dir <已轉UTF-8的黑客松檔目錄>]

黑客松檔（新北AWS*）原始編碼是 Big5；DuckDB 不吃 Big5，執行前先：
    mkdir -p /tmp/youbike_utf8
    cd 資料集 && for f in 新北AWS*.csv; do iconv -f big5 -t utf-8 "$f" > "/tmp/youbike_utf8/$f"; done

產出（youbike.duckdb）：
    stations     站點主檔（station_id、名稱、行政區、座標、容量、期間、旗標）
    snapshots    快照事實表（station_id, ts 對齊 30 分鐘槽, bikes, docks_avail, docks_total）
    v_snapshots  分析用主視圖（join 站點 + date/hour/星期/假日/空滿旗標/佔用率）
"""
import argparse
import sys
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
DB = HERE / "youbike.duckdb"
DATA = HERE / "資料集"

COLS = (
    "{'日期':'VARCHAR','城市':'VARCHAR','行政區':'VARCHAR','場站名稱':'VARCHAR',"
    "'總車柱數':'INTEGER','可借車數':'INTEGER','可還位數':'INTEGER',"
    "'經度':'DOUBLE','緯度':'DOUBLE'}"
)

# 站名修正表（以完全相同座標驗證過為同一站）：
# 前 6 筆是黑客松檔的 Big5 匯出把字集外罕用字（獇/啓/绽/磘/峯）寫成「?」；
# 最後 1 筆是 2026-04-01 13:00→13:30 的無縫更名。統一用新/正確名稱。
NAME_FIXES = {
    "?寮公園": "獇寮公園",
    "十四張?文路口": "十四張啓文路口",
    "新春街125巷(樂活?社區)": "新春街125巷(樂活绽社區)",
    "瓦?截流站": "瓦磘截流站",
    "瓦?溝(福真里)": "瓦磘溝(福真里)",
    "金城?廷街口": "金城峯廷街口",
    "美麗新淡海影城": "新市五義山路口",
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--big5-dir", default="/tmp/youbike_utf8",
                    help="新北AWS* 檔轉成 UTF-8 後所在目錄")
    args = ap.parse_args()
    big5_dir = Path(args.big5_dir)
    if not list(big5_dir.glob("新北AWS*.csv")):
        sys.exit(f"找不到已轉 UTF-8 的黑客松檔：{big5_dir}（見檔頭說明先跑 iconv）")

    DB.unlink(missing_ok=True)
    con = duckdb.connect(str(DB))

    # ---- 1. 讀入兩組原始檔，統一時間到 30 分鐘槽、套用站名修正 ----
    con.execute("CREATE TEMP TABLE name_fix (old_name VARCHAR, new_name VARCHAR)")
    con.executemany("INSERT INTO name_fix VALUES (?, ?)", list(NAME_FIXES.items()))
    con.execute(f"""
        CREATE TEMP VIEW raw_all AS
        WITH src AS (
            SELECT strptime("日期", '%Y/%m/%d %H:%M')            AS raw_ts,
                   trim("行政區") AS district, trim("場站名稱") AS name,
                   "總車柱數" AS docks_total, "可借車數" AS bikes, "可還位數" AS docks_avail,
                   "經度" AS lon, "緯度" AS lat
            FROM read_csv('{DATA}/YouBike*.csv', header=true, columns={COLS})
            UNION ALL
            SELECT strptime("日期", '%Y-%m-%d %H:%M:%S'),
                   trim("行政區"), trim("場站名稱"),
                   "總車柱數", "可借車數", "可還位數", "經度", "緯度"
            FROM read_csv('{big5_dir}/新北AWS*.csv', header=true, columns={COLS})
        )
        SELECT src.* REPLACE (coalesce(f.new_name, src.name) AS name)
        FROM src LEFT JOIN name_fix f ON src.name = f.old_name
    """)

    # ---- 2. 對齊 30 分鐘槽 + 去重（同站同槽保留原始時間最晚的一筆）----
    con.execute("""
        CREATE TEMP TABLE dedup AS
        SELECT * EXCLUDE (rn) FROM (
            SELECT time_bucket(INTERVAL '30 minutes', raw_ts) AS ts,
                   name, district, docks_total, bikes, docks_avail, lon, lat,
                   row_number() OVER (
                       PARTITION BY name, time_bucket(INTERVAL '30 minutes', raw_ts)
                       ORDER BY raw_ts DESC) AS rn
            FROM raw_all)
        WHERE rn = 1
    """)
    n_raw = con.sql("SELECT count(*) FROM raw_all").fetchone()[0]
    n_dedup = con.sql("SELECT count(*) FROM dedup").fetchone()[0]

    # ---- 3. 站點主檔：district/座標取眾數（空字串行政區視為缺值，靠其他列補齊）----
    con.execute("""
        CREATE TABLE stations AS
        SELECT row_number() OVER (ORDER BY min(ts), name) AS station_id,
               name,
               mode(nullif(district, ''))      AS district,
               mode(lon) AS lon, mode(lat) AS lat,
               max(docks_total)                AS capacity_docks,
               min(ts) AS first_ts, max(ts) AS last_ts,
               count(*) AS n_snapshots,
               max(bikes) = 0                  AS always_empty,
               count(DISTINCT (lon, lat))      AS n_coord_variants
        FROM dedup GROUP BY name
    """)
    # 修正紀錄留在庫裡供查證
    con.execute("CREATE TABLE name_fixes AS SELECT old_name, new_name FROM name_fix")

    # ---- 4. 快照事實表（依 station_id, ts 排序寫入，利壓縮與區段掃描）----
    con.execute("""
        CREATE TABLE snapshots AS
        SELECT s.station_id, d.ts,
               d.bikes::SMALLINT AS bikes,
               d.docks_avail::SMALLINT AS docks_avail,
               d.docks_total::SMALLINT AS docks_total
        FROM dedup d JOIN stations s ON d.name = s.name
        ORDER BY s.station_id, d.ts
    """)

    # ---- 5. 分析用主視圖 ----
    con.execute("""
        CREATE VIEW v_snapshots AS
        SELECT sn.station_id, st.name, st.district,
               sn.ts,
               CAST(sn.ts AS DATE)                 AS date,
               EXTRACT(hour FROM sn.ts)::TINYINT   AS hour,
               isodow(sn.ts)::TINYINT              AS isodow,      -- 1=一 … 7=日
               isodow(sn.ts) >= 6                  AS is_weekend,
               sn.bikes, sn.docks_avail, sn.docks_total,
               sn.bikes = 0                        AS is_empty,
               sn.docks_avail = 0                  AS is_full,
               round(sn.bikes / nullif(sn.docks_total, 0), 4) AS occ_rate,
               st.lon, st.lat, st.always_empty
        FROM snapshots sn JOIN stations st USING (station_id)
    """)

    # ---- 6. 驗收 ----
    print(f"原始 {n_raw:,} 筆 → 去重後 {n_dedup:,} 筆（移除 {n_raw - n_dedup:,}）")
    print(con.sql("""
        SELECT strftime(ts, '%Y-%m') AS 月份, count(*) AS 筆數,
               count(DISTINCT station_id) AS 站數,
               round(100.0 * sum(bikes = 0) / count(*), 2)       AS "空車率%",
               round(100.0 * sum(docks_avail = 0) / count(*), 2) AS "滿位率%"
        FROM snapshots GROUP BY 1 ORDER BY 1"""))
    print(con.sql("""
        SELECT count(*) AS 總站數,
               sum(always_empty::INT)           AS 全期零車站,
               sum((district IS NULL)::INT)     AS 行政區缺值,
               sum((name LIKE '%?%')::INT)      AS 問號站,
               sum((n_coord_variants > 1)::INT) AS 座標多版本站
        FROM stations"""))
    bad_minutes = con.sql(
        "SELECT count(*) FROM snapshots WHERE EXTRACT(minute FROM ts) NOT IN (0, 30)"
    ).fetchone()[0]
    print(f"未對齊 30 分鐘槽的筆數：{bad_minutes}（應為 0）")
    con.close()
    print(f"完成：{DB}（{DB.stat().st_size / 1e6:.0f} MB）")


if __name__ == "__main__":
    main()

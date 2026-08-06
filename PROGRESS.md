# PROGRESS — YouBike 隔夜衝刺狀態帳本

> loop 每輪必讀必寫。狀態塊保持精簡（這是工作記憶，不是日記）；歷程 log 一輪一行。

## 狀態塊

- **當前 milestone**：M3（前端主體）— M0/M1/M2 已完成
- **公開網址**：`https://youbike.itsmygo.uk` — ✅ 上線（API 全通 + 即時資料，前端仍是 scaffold 佔位頁）
- **Dagster**：✅ `https://youbike-dagster.itsmygo.uk`（CF Access 336h），schedule `realtime_every_10min` RUNNING，23:30 首次準時觸發
- **MLflow experiment**：❌ 尚未建立（目標：`youbike-hackathon` @ http://192.168.50.190:5000）
- **GitHub repo**：✅ `skmygo/youbike`（public，main）
- **阻塞**：無

## 關鍵設施（下輪直接用，不要重查）

| 項目 | 值 |
|---|---|
| Dokploy composeId | `EJlGvq06-SkKnFlCnFB_E`（project `youbike`, env `OGT-gORSR2VANgkb8jXMw`, appName `compose-transmit-multi-byte-alarm-oy7s99`） |
| Dokploy 部署 | **webhook 未觸發，push 後要手動 `compose-deploy`**（githubId `U8QNtwT-5cJKopa6eJoDO` clone 正常，只有 webhook 不來） |
| Garage S3 | bucket `youbike`，key `GKd6ccf6c20e963f105eb15f27` / secret 見本機 `.env`（已寫入 Dokploy env 與 NAS `.secrets`） |
| S3 內容 | `history/snapshots_2026{01..06}.parquet`、`serving/{stations,hourly,latest}.parquet`（共 18MB） |
| 容器資料 | volume `youbike-data:/data`，entrypoint 自動從 S3 引導缺檔 |
| 本機匯出 | `_out/`（同上 9 檔），重跑 `.venv/bin/python -m pipeline.export_history` |
| 本機 venv | `.venv`（Python 3.14，dagster 1.13.16 / lightgbm 4.7.0 / mlflow 3.15.1 / duckdb 1.5.5），已含 pipeline+ml extras |
| 本機跑 dagster | `YOUBIKE_DATA_DIR=$PWD/_out DAGSTER_HOME=$PWD/_out/dagster .venv/bin/dagster job execute -m pipeline.defs -j realtime_refresh` |
| CF Access app | `youbike-dagster` id `cd42824a-cf26-48c2-9e14-2dfb4d738291`（allow kuan9924501@gmail.com，336h） |
| station_id | 以**站名**為 key（build_duckdb.py 的流水號）；即時爬蟲用站名對回，新站配號 ≥900000 |

## 已完成

- [x] WP0 資料工程：`youbike.duckdb`（6 個月、1,332 萬筆、30 分槽、站名修正、去重）
- [x] 需求正本 `ref_data/分析規劃.html`（WP0–WP5 + KPI + 降級路線）
- [x] **M0** monorepo（`api/ pipeline/ ml/ web/ deploy/`）+ 多階段 Dockerfile + Dokploy compose/domain + 公開網址上線
- [x] **M1** 歷史 parquet 匯出（18MB/9 檔）→ Garage S3 → 容器引導；核心 API 全通：
  - `/api/health` `/api/meta`
  - `/api/stations`（1,567 站 + 狀態四色）、`/api/stations/{id}`、`/api/stations/{id}/history`
  - `/api/replay?ts=`、`/api/replay/days`（181 天可回放）
  - `/api/stats/{overview,hourly,districts,worst}`
  - `/api/alerts`：WP4 三級（notice 208 / warning 37 / critical 114）
- [x] 前端 scaffold（Vite 8 + React 19 + TS + Tailwind 4 + TanStack Router/Query + shadcn 基礎 + maplibre/echarts 已裝）
- [x] **M2** Dagster 排程上線：`realtime_snapshot` → `station_registry` → `serving_snapshots` → `alerts_table`，
  每 10 分鐘（Asia/Taipei）；UI `youbike-dagster.itsmygo.uk` + CF Access；23:30 首次自動執行成功，
  API 已改讀 pipeline 物化的 `alerts.parquet`（306 筆）

## 待辦（照 MISSION.md milestone 表）

- [ ] **M3** 前端主體（地圖／站點詳情／回放／警示面板／行政區彙總）
- [ ] **M4** 特徵庫 + baseline×2 + LightGBM + MLflow + 6 月回測 report.json
- [ ] **M5** 預測資產 + forecast API + 預測型警示 + 調度建議
- [ ] **M6** KPI hero + /model 頁 + README + 簡報大綱
- [ ] **M7** 收尾 SUMMARY.md

## 資料事實（給後續 milestone 直接引用）

- 歷史：2026-01-01 ~ 06-30，13,246,780 筆有效快照（剔除未營運站後），1,567 站
- 全期空車率 5.11%、滿位率 1.68%
- 最嚴重空車站：國慶三樹路口（三峽）69.1%、平溪市民活動中心 60.9%、菁桐老街 52.9%
- 警示門檻（WP4）：注意 可借/可還 ≤2；警戒 已空滿 ≥30 分；嚴重 ≥60 分；預測型 60 分內機率 ≥70%
- **資料品質**：有車柱卻既無車也無空位＝離線站（約 35–46 站），已新增 `offline` 狀態並排除於警示與空滿統計
- 即時來源 1,586 站（比歷史多 10 站，新站 id ≥900000）；新北平台憑證缺 Subject Key Identifier，
  新版 OpenSSL 驗不過 → crawl 先走正常驗證、僅憑證錯誤時降級重試
- ML 切分：1–4 月訓練 / 5 月驗證 / 6 月測試（不洗牌）

## 歷程 log

- 2026-08-06 22:35 — 研究完成，MISSION.md / PROGRESS.md 建立
- 2026-08-06 22:48 — **M0 完成**（提前 22 分）：monorepo + Dockerfile + Dokploy + `youbike.itsmygo.uk/api/health` 200，S3 引導一次成功
- 2026-08-06 23:03 — **M1 完成**（提前 67 分）：9 個 API 全通，公開網址實測 <1 秒回應
- 2026-08-06 23:31 — **M2 完成**（提前 99 分）：Dagster 四資產上線，23:30 schedule 準時觸發，
  即時快照進服務層；修掉 dagster context 型別註解、SSL 憑證、離線站誤判三個問題

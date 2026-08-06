# PROGRESS — YouBike 隔夜衝刺狀態帳本

> loop 每輪必讀必寫。狀態塊保持精簡（這是工作記憶，不是日記）；歷程 log 一輪一行。

## 狀態塊

- **當前 milestone**：M2（Dagster 排程）— M0/M1 已完成
- **公開網址**：`https://youbike.itsmygo.uk` — ✅ 上線（API 全通，前端仍是 scaffold 佔位頁）
- **Dagster**：❌ 尚未建立（M2）
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
| 本機匯出 | `_out/`（同上 9 檔），重跑 `uv run --with duckdb --with boto3 --with pandas --with pyarrow python -m pipeline.export_history` |
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

## 待辦（照 MISSION.md milestone 表）

- [ ] **M2** Dagster assets（crawl */10 → snapshots_30m → serving_parquet → alerts）+ compose 加 service + `youbike-dagster.itsmygo.uk` + CF Access
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
- ML 切分：1–4 月訓練 / 5 月驗證 / 6 月測試（不洗牌）

## 歷程 log

- 2026-08-06 22:35 — 研究完成，MISSION.md / PROGRESS.md 建立
- 2026-08-06 22:48 — **M0 完成**（提前 22 分）：monorepo + Dockerfile + Dokploy + `youbike.itsmygo.uk/api/health` 200，S3 引導一次成功
- 2026-08-06 23:03 — **M1 完成**（提前 67 分）：9 個 API 全通，公開網址實測 <1 秒回應

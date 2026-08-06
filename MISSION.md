# MISSION：YouBike 調度平台隔夜衝刺（22:30 → 08:00）

> 這份文件是 `/loop` 隔夜任務的**唯一作戰手冊**。每輪醒來先讀 `PROGRESS.md` 的狀態塊，再回來對照本文件的 milestone 表。所有架構決策已定案，**夜間不要重新發明、不要換技術棧**。

## 0. 目標與勝利條件

為「新北市政府 AI 黑客松・交通局命題」做出**得名等級**的完整作品（命題解讀見 `分析規劃.html`，該文件是需求正本）：

看得到（視覺化）→ 猜得到（預測）→ 叫得動（警示與調度）

**勝利條件（08:00 驗收）**：
1. `https://youbike.itsmygo.uk` 公開可用：即時地圖、站點歷史+預測帶、歷史回放、警示面板、調度建議
2. Dagster 排程真的在跑（每 10 分鐘爬即時資料入庫），UI 可展示於 `youbike-dagster.itsmygo.uk`
3. MLflow（`http://192.168.50.190:5000`，experiment `youbike-hackathon`）有完整實驗紀錄；6 月回測報告數字（MAE、事件 precision/recall、平均預警提前分鐘數）呈現在網站上
4. README + 簡報大綱完成，KPI 故事線對應命題三痛點

## 1. 已有資產 參考用在 ref_data/ 底下

| 資產 | 狀態 |
|---|---|
| `youbike.duckdb`（60MB） | ✅ 6 個月（2026-01~06）1,332 萬筆快照，`stations`/`snapshots`/`v_snapshots`，30 分槽已對齊、站名已修、去重完成 |
| `crawl_realtime.py` | ✅ 新北開放平台即時爬蟲，輸出 9 欄 UTF-8 CSV（`資料集/即時爬取_YYYYMM.csv`），已驗證可用 |
| `backfill_tdx.py` | ✅ TDX 歷史回補（需 TDX key，**用戶沒給 key 就跳過**，7 月缺口不影響主線） |
| `分析規劃.html` | ✅ WP0–WP5 完整規劃 + KPI 定義 + MVP 降級路線（需求正本） |
| `資料集介紹.html` / `外部資料規劃.html` | ✅ 資料品質細節 / 外部資料（天氣、捷運）優先序。做特徵工程前先讀 |
| git repo | ✅ 已 init（1 commit）。**尚未有 GitHub remote** |
| 工具鏈 | uv 0.11.7 / Python 3.12 / Node 24 / pnpm 11.10；`.claude/settings.json` 已啟用 dagster-expert plugin |

## 2. 架構定案

```
┌─ 本機（開發+訓練）────────────────┐   ┌─ .217 Dokploy（youbike compose）──────────────┐
│ youbike.duckdb（6個月歷史）        │   │ [dagster]  dagster dev（webserver+daemon）      │
│ ML 訓練（LightGBM→MLflow→S3）     │   │   schedules: crawl(*/10) → serving parquet     │
│ git push ──→ GitHub ──webhook──→──┼──→│   → features → predictions(*/30) → alerts      │
└──────────────────────────────────┘   │ [api]      FastAPI + 前端靜態檔（port 8000）     │
                                        │ 共用 volume /data：parquet + model + duckdb     │
外部服務（全部現成，別動基礎設施）：      └────────────────────────────────────────────────┘
- Garage S3  http://192.168.50.190:3900（資料引導：歷史 parquet、模型檔）
- MLflow     http://192.168.50.190:5000（LAN 直連，experiment: youbike-hackathon）
- 公開路由   youbike.itsmygo.uk → Traefik（wildcard 已涵蓋，只需 Dokploy 建 domain）
```

**技術棧（定案，不換）**：
- 前端：Vite + React + TypeScript + **TanStack Router + TanStack Query** + Tailwind CSS + shadcn/ui；地圖 **MapLibre GL JS**（底圖用 CARTO raster tiles，免 key，記得 attribution）；圖表 **ECharts**
- API：**FastAPI** + uvicorn；查詢引擎 DuckDB（`:memory:` 連線查 parquet glob，**無檔案鎖問題**）
- Pipeline：**Dagster**（assets + schedules；storage 用 sqlite / DAGSTER_HOME 放 volume，單機 demo 足夠）
- ML：**LightGBM** + scikit-learn；**MLflow** 記錄所有 run
- 部署：monorepo → GitHub private repo → Dokploy compose push-to-deploy（比照 chatapp/autoblog SOP）

**關鍵設計決策（已想清楚，直接照做）**：
1. **DuckDB 併發**：dagster 寫、api 讀絕不共用同一顆 .duckdb 檔（會撞檔案鎖）。Pipeline 物化 **parquet**（`/data/serving/*.parquet` + 原子 rename），API 每次請求用 `duckdb.connect()`（in-memory）查 parquet。歷史大表也是 parquet。
2. **資料引導**：`資料集/`（1GB CSV）與 `youbike.duckdb` **不進 git**（檢查 `.gitignore`）。本機把歷史資料匯出成 parquet（snapshots 按月分檔 + stations），上傳 Garage S3 新 bucket `youbike`（照 infra.md SOP 建 bucket + `youbike-key`，SSH `kuan@192.168.50.190`，密碼 `Sk=295122`，docker 絕對路徑 `/usr/local/bin/docker`，sudo 走 `echo "Sk=295122" | sudo -S -p ''`）。容器啟動腳本檢查 `/data` 缺檔就從 S3 拉（.217 → .190 LAN 直連，快）。
3. **Dagster 自帶**，不動 .10 共用 stack。`dagster.itsmygo.uk` 已被佔用，youbike 的 Dagster UI 掛 `youbike-dagster.itsmygo.uk`（**要設 CF Access**，照 infra.md SOP，session 336h）。`youbike.itsmygo.uk` 本體**公開、無 CF Access**。
4. **Dokploy domain 參數**：`certificateType=none`、`https=false`、port=容器內部埠。DNS/Tunnel 不用動。Dokploy 一律用 dokploy-mcp 工具操作；GitHub source：`githubId: "U8QNtwT-5cJKopa6eJoDO"`（先 `gh auth status` 確認帳號，repo 建在該帳號下；若 installation 沒涵蓋新 repo，到 Dokploy DB 查 or 比照 infra.md「已知陷阱」處理）。
5. **模型部署**：訓練在本機（資料在本機、CPU 快），model 檔 + `report.json` 上 S3，容器啟動腳本拉下來；線上預測由 dagster 排程算好寫 parquet，API 只讀結果（**不在請求路徑跑模型**）。
6. **ML 切分紀律**：1–4 月訓練、5 月驗證、6 月測試，時間序不洗牌。Baseline（persistence + 上週同日同時段）必須先跑，LightGBM 贏不過就誠實分層呈現（規劃已寫明這反而加分）。

## 3. Milestone 表（每輪對照，落後就啟動降級）

| # | 時段（預算） | 交付 | 驗收（可自動驗證） |
|---|---|---|---|
| M0 | 22:40–23:10 | monorepo 重構（`pipeline/` `api/` `web/` `ml/` `deploy/`）；GitHub private repo；Dokploy compose + domain + push-to-deploy；FastAPI 佔位頁上線 | `curl -s https://youbike.itsmygo.uk/api/health` 回 200 |
| M1 | 23:10–00:10 | 歷史 parquet 匯出 + S3 上傳 + 容器引導腳本；核心 API：`/api/stations`、`/api/stations/{id}/history`、`/api/replay?ts=`、`/api/stats/hourly`、`/api/alerts`（規則型：注意/警戒/嚴重，門檻見分析規劃.html WP4） | 公開網址各 API 回真實資料 |
| M2 | 00:10–01:10 | Dagster：assets `crawl_realtime`(*/10) → `snapshots_30m` → `serving_parquet` → `alerts`；compose 加 dagster service；`youbike-dagster.itsmygo.uk` + CF Access | Dagster UI 可看且 schedule RUNNING；等 10 分鐘後 serving 資料含新快照 |
| M3 | 01:10–03:10 | 前端主體：即時地圖（狀態四色：正常/將空滿/已空/已滿）、站點詳情（歷史曲線）、歷史回放（時間軸拉桿）、警示面板、行政區彙總；多階段 Dockerfile 併入 api | Chrome 實測公開網址每頁可用 |
| M4 | 03:10–05:00 | 特徵庫（lag 30m–24h、rolling、時間、假日、站點分群 k-means、鄰近站聚合；天氣視時間加做）；baseline ×2；LightGBM 回歸+分類（30/60/120/180 分）；全程 MLflow；6 月回測 `report.json`；模型上 S3 | MLflow 有 runs；report.json 含 MAE + 事件 P/R/F1 + 平均提前分鐘數 |
| M5 | 05:00–06:30 | dagster `predictions`(*/30) 資產；API `/api/stations/{id}/forecast` + 前端預測帶；預測型警示（60 分內空/滿機率 ≥70%）；調度建議（優先級 = 嚴重度×歷史需求×持續時間；1km 內餘裕站調車清單）+ UI 頁 | 前端可見預測帶、預測型警示、調度建議清單 |
| M6 | 06:30–07:45 | 首頁 KPI hero（回測數字 + 模擬調度改善）；`/model` 模型成效頁；README（架構圖 mermaid、KPI、demo 導覽）；`簡報大綱.md`；Chrome 全頁面走查 + RWD/深色 | 評審動線：進站 30 秒內看懂三痛點對應三模組 |
| M7 | 07:45–08:00 | 最終 push + 部署驗證 + `SUMMARY.md` | ScheduleWakeup `stop: true` |

**降級規則**：任一 milestone 落後 >45 分鐘，依序砍：天氣特徵 → 回放精緻度（改成選日期看動畫即可）→ 調度建議簡化（只做優先級排序，不算調車數）→ 預測檔位減半（只做 30/60 分）→ `/model` 頁併入 README。**不可砍底線**：地圖 + 歷史 API + 規則型警示 + baseline 預測 + 公開網址活著。

## 4. 每輪 loop 儀式（嚴格執行）

1. `date` 看現在時間 → 對照 milestone 表，判斷正常/落後
2. 讀 `PROGRESS.md` 狀態塊（**不要**靠記憶，不要重讀已完成部分的大檔案）
3. 埋頭做當前 milestone，一輪盡量做完一個完整驗收單位（turn 能撐多久撐多久，不要頻繁 wakeup 浪費啟動成本）
4. 驗收：能 curl 就 curl，UI 用 Chrome 工具實測**公開網址**（不是 localhost）
5. `git add -A && git commit && git push`（push 即觸發部署；部署失敗要看 Dokploy deployment logs 修到綠）
6. 更新 `PROGRESS.md`（狀態塊 + 一行 log）
7. ScheduleWakeup：有背景長任務（訓練/build/部署）→ fallback 1200s；否則 60–180s 接續
8. 時間 ≥07:45 → 進入 M7 收尾；≥08:00 → 寫完 SUMMARY 後 `stop: true`

**Token 紀律（防撞訂閱用量上限，撞上 loop 就死了）**：
- 機械性工作（boilerplate、shadcn 元件、重複 CRUD、CSS）派 `Agent` subagent 用 `model: "sonnet"` 做
- 禁用 Workflow/ultracode 大編隊
- 長任務一律 `run_in_background`，用完成通知回來接手，**不做短輪詢**
- 別重讀大檔案；狀態進 PROGRESS.md

**卡住規則**：同一錯誤修 3 次不過 → 換方法（見風險表備案）；再不過 → 記入 PROGRESS.md「阻塞」段、跳做下一個不依賴它的 milestone，**絕不空轉等人**。

## 5. 風險與備案

| 風險 | 對策 |
|---|---|
| 訂閱用量上限（最大風險，無自動恢復） | Token 紀律（上方）；真撞上：loop 停擺，用戶早上 `claude --continue` 續跑收尾 |
| Dokploy build 反覆失敗 | 先在本機 `docker build` 驗過再 push；還不行改 `sourceType=raw` compose 直接貼 Dokploy（比照 s3-proxy 模式） |
| 新北開放平台半夜掛掉 | 爬蟲已有重試；前端顯示最後快照時間；歷史回放模式是展示保底（規劃已定） |
| .217 資源不足跑不動 dagster | 降級：砍 dagster service，改 Dokploy Schedules（`scheduleType=server`）每 10 分跑 `docker exec api python -m pipeline.crawl`；Dagster 展示改跑本機錄 GIF |
| MapLibre 底圖掛 | 換 OSM raster tile；再不行地圖退化成 ECharts scatter（經緯度散點） |
| CF Access 設定卡住 | `youbike-dagster` 先不掛公開網域，Dagster UI 用 LAN 截圖展示，不阻塞主線 |

## 6. 需要用戶的事（都非阻塞，早上再說）

- TDX key（要補 7 月歷史才需要；沒有就用 6 個月 + 8 月即時，完全夠）
- 簡報是否要做成投影片（夜間先交 `簡報大綱.md` + 網站本身就是 demo）

---

## 7. 啟動方式（給用戶，執行前讀這段）

**推薦：就用研究完成的這個 session 直接開跑**（context 都熱著）：

1. 確認權限模式是 bypass：看輸入框下方狀態，按 `Shift+Tab` 循環到 `bypass permissions`；如果循環裡沒有這個選項 → 打 `exit`，然後：
   ```bash
   cd /home/sk/work/youbike
   tmux new -s youbike        # SSH 環境必開 tmux；本機桌面 terminal 可省
   claude --dangerously-skip-permissions --continue   # --continue 接回本對話
   ```
2. 貼這條指令（一字不改）：

   ```
   /loop 執行 /home/sk/work/youbike/MISSION.md 的隔夜衝刺。每輪醒來：date 看時間、讀 PROGRESS.md，對照 MISSION.md milestone 表做下一個未完成項目，一輪盡量完成一個完整驗收單位；完成就 commit+push、驗證公開網址、更新 PROGRESS.md，再用 ScheduleWakeup 排下一輪（背景任務跑著就排 1200 秒 fallback，否則 60–180 秒）。遇錯自己修、修 3 次不過就換 MISSION.md 風險表的備案，絕不停下來等人。台北時間 07:45 進入收尾 milestone M7，08:00 寫完 SUMMARY.md 後用 stop:true 結束 loop。
   ```

3. 機器整晚不能睡：確認電源設定「永不休眠」（GNOME：設定 → 電源 → 自動暫停關閉；或跑 `systemd-inhibit --what=sleep:idle sleep infinity &`）。`/loop` 的排程在 CLI 進程裡，**進程死 = loop 死**。
4. （可選）睡前瞄一眼第一輪有沒有動起來（PROGRESS.md 有更新、`youbike.itsmygo.uk` 佔位頁上線）就可以去睡了。

**明早 08:00 看什麼**：`SUMMARY.md`（總結）→ `https://youbike.itsmygo.uk`（成品）→ `PROGRESS.md`（過程帳）。如果 loop 半夜死了（用量上限/斷電）：`claude --continue` 然後說「繼續 MISSION.md」即可續跑。

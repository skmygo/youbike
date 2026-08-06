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

> ⚠️ **本機 = .217 production 主機本體**：上圖「本機」與「.217 Dokploy」是同一台 8 核 / 14GB 機器的兩個角色，所有 `*.itsmygo.uk` 服務都在上面。重活（訓練/特徵工程/docker build）必戴 CLAUDE.md 資源鐵律的資源罩；把機器吃滿 = production 全滅（00:45 已發生一次：swap 灌滿、Dokploy 被迫重啟）。

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

## 3. Milestone 表（2026-08-07 00:55 二次基準——00:45 資源事故後重排；每輪對照，落後就啟動降級）

M0–M3 ✅ 全部完成；M4 進行中（`ml/` 四檔已寫好，首跑因沒設資源上限把機器吃掛，程式碼配額已調安全，重跑必戴資源罩）。**超前不提前收工**：多出來的時間轉投 §3.5 加分梯隊與 §3.6 守夜模式，loop 一路跑到 08:00。

| # | 時段（預算） | 交付 | 驗收（可自動驗證） |
|---|---|---|---|
| M4 | 00:55–02:45 | 特徵庫（lag 30m–24h、rolling、時間、假日、站點分群 k-means、鄰近站聚合）；baseline ×2（persistence、上週同日同時段）；LightGBM 回歸+分類（30/60/120/180 分）；全程 MLflow；6 月回測 `report.json`；模型上 S3。**全程資源罩（CLAUDE.md 鐵律 7–9）** | MLflow 有 runs；report.json 含 MAE + 事件 P/R/F1 + 平均提前分鐘數，baseline 對照齊全；全程機器沒掛 |
| M5 | 02:45–04:15 | dagster `predictions`(*/30) 資產；API `/api/stations/{id}/forecast` + 前端預測帶；預測型警示（60 分內空/滿機率 ≥70%）；調度建議（優先級 = 嚴重度×歷史需求×持續時間；1km 內餘裕站調車清單）+ UI 頁 | 公開網址可見預測帶、預測型警示、調度建議清單；dagster 排程有新產出 |
| M6 | 04:15–05:45 | 首頁 KPI hero（回測數字 + 模擬「依預警提前調度」的空滿時數改善 = 命題 KPI1 回測）；`/model` 模型成效頁；README（架構圖 mermaid、KPI、demo 導覽）；`簡報大綱.md`；容器全頁走查 + RWD/深色 | 評審動線：進站 30 秒內看懂三痛點對應三模組；回測數字上網站 |
| S | 05:45–07:45 | §3.5 加分梯隊由上往下做 + §3.6 守夜 | 每項獨立驗收 |
| M7 | 07:45–08:00 | 最終 push + 部署驗證 + `SUMMARY.md`（含加分項成果清單） | ScheduleWakeup `stop: true` |

**降級規則**：任一 milestone 落後 >45 分鐘，依序砍：站點分群/鄰近站特徵簡化 → 調度建議簡化（只做優先級排序，不算調車數）→ 預測檔位減半（只做 30/60 分）→ `/model` 頁併入 README。**不可砍底線**：地圖 + 歷史 API + 規則型警示 + baseline 預測 + 公開網址活著。

### 3.5 加分梯隊（M4–M6 主線全綠才動；一次一項、做完驗收一項；剩餘時間 < 該項預算 ×1.5 就不開工，直接守夜）

| # | 項目（預算） | 內容 | 為什麼加分 |
|---|---|---|---|
| S1 | 通知管道 demo（30 分） | alerts 資產把「新升級為警戒/嚴重」的警示 POST 到 webhook（URL 走 env，預設打自家 `/api/notify/log`），警示頁加「通知紀錄」小卡 | 補齊 WP4「主動通知機關」：面板 + 推播雙管道 |
| S2 | 預測不確定帶（45 分） | LightGBM quantile 0.1/0.9（來不及就 ±驗證期 MAE），前端預測帶變成真的帶 | 預測頁質感與可信度敘事 |
| S3 | 天氣特徵（60 分） | 照 `ref_data/外部資料規劃.html` 優先序 join 天氣重訓，MLflow 留「有/無天氣」對照 runs，report 補一節 | 特徵完整度 + 簡報對照數字 |
| S4 | 簡報 slides（45 分） | `簡報大綱.md` 升級成單檔 HTML 可放映簡報（痛點數據 → demo 動線 → KPI 改善數字） | 早上直接能講 |
| S5 | demo GIF（30 分） | 網站主動線 + Dagster UI 各錄一段 GIF 進 README | README/簡報秒懂 |

### 3.6 守夜模式（加分梯隊做完、或依 ×1.5 規則不宜開工時進入）

每 30–60 分鐘一輪（ScheduleWakeup 1800–3600s）輕量健檢：`/api/health` 200、`/api/meta` 的 latest/alerts mtime 在 20 分鐘內、dagster 最近 run 成功。壞了視同主線事故立刻修；沒壞只在 PROGRESS.md 記一行心跳，不做其他動作、不燒 token。07:45 到就進 M7。

## 4. 每輪 loop 儀式（嚴格執行；鐵律全文在 `CLAUDE.md`，每輪自動載入）

1. `date` 看現在時間 → 對照 §3 基準表，判斷正常/落後（落後 >45 分啟動降級）
2. 讀 `PROGRESS.md` 狀態塊（**不要**靠記憶，不要重讀已完成部分的大檔案）
3. 埋頭做當前項目，一輪盡量做完一個完整驗收單位（turn 能撐多久撐多久，不要頻繁 wakeup 浪費啟動成本）
4. 驗收：API 用 curl 打**公開網址**；前端改動先本機容器 + `/tmp/pw/shot.mjs` 驗過（dev 正常 ≠ production 正常；遠端 Chrome 載不動 maplibre worker，不要用它驗地圖）
5. `git add -A && git commit && git push` → **手動 dokploy-mcp `compose-deploy`（webhook 不會來，composeId 在 PROGRESS.md）** → 部署失敗看 deployment logs 修到綠 → curl 公開網址收尾確認
6. 更新 `PROGRESS.md`（狀態塊 + 一行 log）
7. ScheduleWakeup：有背景長任務（訓練/build/部署）→ fallback 1200s；接續工作 60–180s；守夜 1800–3600s
8. 時間 ≥07:45 → 進入 M7 收尾；≥08:00 → 寫完 SUMMARY 後 `stop: true`。**這是唯一允許結束 loop 的條件**

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
| 本機資源耗盡把 production 主機搞掛（**已發生一次**：00:45 ML 首跑 swap 灌滿、同機 Dokploy 重啟） | CLAUDE.md 資源鐵律 7–9：systemd-run 罩（MemoryMax=4G / CPUQuota=400% / nice 19）+ `num_threads=3` + DuckDB 3GB/3t + 跑前 `free -g`；再超限就縮規模：訓練期抽樣 50%→30% → 檔位減半 → 鄰近站特徵砍，**絕不調大上限** |
| Dokploy build 反覆失敗 | 先在本機 `docker build` 驗過再 push；還不行改 `sourceType=raw` compose 直接貼 Dokploy（比照 s3-proxy 模式） |
| 新北開放平台半夜掛掉 | 爬蟲已有重試；前端顯示最後快照時間；歷史回放模式是展示保底（規劃已定） |
| .217 資源不足跑不動 dagster | 降級：砍 dagster service，改 Dokploy Schedules（`scheduleType=server`）每 10 分跑 `docker exec api python -m pipeline.crawl`；Dagster 展示改跑本機錄 GIF |
| MapLibre 底圖掛 | 換 OSM raster tile；再不行地圖退化成 ECharts scatter（經緯度散點） |
| CF Access 設定卡住 | `youbike-dagster` 先不掛公開網域，Dagster UI 用 LAN 截圖展示，不阻塞主線 |

## 6. 需要用戶的事（都非阻塞，早上再說）

- TDX key（要補 7 月歷史才需要；沒有就用 6 個月 + 8 月即時，完全夠）
- 簡報是否要做成投影片（夜間先交 `簡報大綱.md` + 網站本身就是 demo）

---

## 7. 續跑方式（給用戶；M0–M3 完成、M4 進行中，2026-08-07 00:55 二次基準）

1. 權限要在 bypass 模式：輸入框下方按 `Shift+Tab` 循環到 `bypass permissions`；循環裡沒有就 `exit` 後：
   ```bash
   cd /home/sk/work/youbike
   tmux new -s youbike        # SSH 環境必開 tmux；本機桌面 terminal 可省
   claude --dangerously-skip-permissions --continue   # 接回原對話
   ```
2. 貼這條指令（一字不改）：

   ```
   /loop 續跑 /home/sk/work/youbike/MISSION.md 隔夜衝刺：M0–M3 完成，M4 進行中（ml/ 四檔已寫好，00:45 首跑沒設資源上限把機器吃掛，配額已調安全）。每輪醒來：date 對照 MISSION.md §3 基準表、讀 PROGRESS.md 狀態塊，埋頭做當前項目，一輪盡量完成一個完整驗收單位，嚴守 CLAUDE.md 鐵律。最高優先是資源鐵律：本機就是 .217 production 主機（8 核/14GB），特徵工程/訓練/回測/docker build 等重活一律用 systemd-run --user --scope -p MemoryMax=4G -p CPUQuota=400% nice -n 19 包住並 run_in_background；LightGBM num_threads=3、DuckDB memory_limit 3GB/threads 3；重活開跑前 free -g 確認 available ≥6G；被 OOM 殺就縮規模（訓練期抽樣 50%→30%、檔位減半），絕不調大上限。其他鐵律：前端先本機容器驗證、push 後手動 compose-deploy、驗收打公開網址、token 紀律。完成就 commit+push+部署驗證+更新 PROGRESS.md，再 ScheduleWakeup 排下輪（背景長任務跑著就 1200 秒 fallback，接續工作 60–180 秒）。M4–M6 主線做完依序做 MISSION §3.5 加分梯隊（一次一項，剩餘時間不足該項預算 1.5 倍就不開工）；沒項目可開就進 §3.6 守夜模式（每 30–60 分鐘輕量健檢公開網址與 Dagster，壞了修、沒壞只記一行心跳）。遇錯自己修、同錯 3 次換 §5 備案，絕不停下來等人、絕不提前結束。台北時間 07:45 進 M7 收尾，08:00 寫完 SUMMARY.md 後用 stop:true 結束 loop。
   ```

3. 機器整晚不能睡：電源設定「永不休眠」（GNOME：設定 → 電源 → 自動暫停關閉；或跑 `systemd-inhibit --what=sleep:idle sleep infinity &`）。`/loop` 的排程在 CLI 進程裡，**進程死 = loop 死**。
4. 半夜 loop 死了（用量上限/斷電）：`claude --continue` 說「繼續 MISSION.md」即可續跑（CLAUDE.md 鐵律會自動載入，不怕失憶）。

**明早 08:00 看什麼**：`SUMMARY.md`（總結）→ `https://youbike.itsmygo.uk`（成品）→ `PROGRESS.md`（過程帳）。

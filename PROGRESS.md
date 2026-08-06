# PROGRESS — YouBike 隔夜衝刺狀態帳本

> loop 每輪必讀必寫。狀態塊保持精簡（這是工作記憶，不是日記）；歷程 log 一輪一行。

## 狀態塊

- **當前 milestone**：**M4 ✅ M5 ✅ M6 ✅ 全部完成並上線**（02:35，比基準表提前約 3 小時）。
  下一步：MISSION §3.5 加分梯隊 S1→S5（一次一項），沒項目可開就進 §3.6 守夜模式。
  資源罩全程有效，峰值 1.88G/4G，production 容器全程健在
- **M4 回測結果（6 月測試集，訓練/驗證完全沒碰過）**：
  - 水位 MAE（台車）LightGBM/persistence：h30 1.442/1.466 **+1.6%**｜h60 2.052/2.213 **+7.3%**｜
    h120 2.746/3.229 **+15.0%**｜h180 3.154/3.992 **+21.0%**（lastweek 5.54 全面墊底）
  - 事件級預警（**營運門檻**＝驗證集最佳 F1，0.10–0.30）：空車 35,450 起偵測 **68.1%**、平均提前 **147 分**、
    誤報 52.2%、每站每天 22.3 次候選；滿位 3,909 起偵測 51.0%、提前 134 分、誤報 72.9%
  - 同一組事件用規劃書的 **70% 門檻**：空車偵測只剩 6.5%、誤報 17.5% → 少擾民但來不及派車
    ⇒ 系統雙軌輸出（`alert_*` 70% ／ `watch_*` 營運門檻），`/dispatch` 與預測型警示用後者 + Top-N 排序消化警報量
  - 規則型警示的提前量恆為 0 分（事發才知道）＝模型的增量價值
- **公開網址**：`https://youbike.itsmygo.uk` — ✅ 五頁全上線（即時指揮／回放／警示／區域分析／關於）；
  00:15 health/meta 正常，dagster 最新快照 00:10 落地
- **Dagster**：✅ `https://youbike-dagster.itsmygo.uk`（CF Access 336h），schedule `realtime_every_10min` RUNNING
- **MLflow experiment**：✅ `youbike-hackathon` = experiment id **3** @ http://192.168.50.190:5000
  （baselines-valid + lgbm-reg-h{30,60,120,180} + lgbm-clf-* 逐一進 run，模型檔當 artifact）
- **加分梯隊（MISSION §3.5）**：未開始（S1 通知 demo → S2 不確定帶 → S3 天氣 → S4 slides → S5 GIF）
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
| MLflow | `MLFLOW_TRACKING_URI=http://192.168.50.190:5000`，experiment `youbike-hackathon`（00:20 ping 200） |
| 資源罩（重活必用） | `systemd-run --user --scope -p MemoryMax=4G -p CPUQuota=400% nice -n 19 <cmd>`；本機=**.217 production 主機**（8 核/14GB，常駐已吃 ~8G），詳 CLAUDE.md 鐵律 7–9 |
| CF Access app | `youbike-dagster` id `cd42824a-cf26-48c2-9e14-2dfb4d738291`（allow kuan9924501@gmail.com，336h） |
| station_id | 以**站名**為 key（build_duckdb.py 的流水號）；即時爬蟲用站名對回，新站配號 ≥900000 |
| 前端驗證 | Claude-in-Chrome 那台（遠端 Windows）**載不動 maplibre worker**（請求恆 pending），不是網站問題。
  UI 驗證改用本機：`cd /tmp/pw && node shot.mjs <url> <out.png> [ms]`（截圖+console）、`node probe4.mjs <url>`（網路/worker） |
| 本機容器驗證 | `docker run -d --name yb-prod -p 18010:8000 -v $PWD/_out:/data youbike:test` — **前端改動一定要用容器驗過再部署**（dev 正常≠production 正常） |

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
- [x] **M3** 前端主體五頁上線（設計方向：夜間調度指揮台，深靛藍面板＋狀態燈號＋等寬數字）：
  - `/` 即時指揮：KPI ×4 + 待處理站點清單 + MapLibre 地圖（1,577 站狀態燈號）+ 站點抽屜（7 天曲線）
  - `/replay` 歷史回放：日期選擇 + 時間軸拉桿 + 播放一天 + 脈搏帶點選跳轉
  - `/alerts` 警示：三級 + 行政區篩選 + 完整表格
  - `/districts` 區域分析：行政區彙總 + 星期×半小時無車熱力圖 + 最常無車站排行
  - `/about` 關於：三痛點對三模組 + 資料涵蓋 + 做法
  - signature：**全市空滿脈搏帶**（48 槽，無車向上、無位向下，疊同星期幾的歷史常態虛線）

## 待辦（照 MISSION.md §3 基準表，00:15 重排）

- [ ] **M4**（00:55–02:45）特徵庫 + baseline×2 + LightGBM（30/60/120/180 分，回歸+分類）+ MLflow + 6 月回測 report.json + 模型上 S3
  - 續作：ml/ 四檔已寫好、配額已調安全；跑 features → train → evaluate 全程資源罩 + run_in_background；
    開跑前 `free -g` 確認 available ≥6G；歷史 parquet 在 `_out/history/`；`MLFLOW_TRACKING_URI=http://192.168.50.190:5000`
- [ ] **M5**（提前做完程式碼，待模型就位後端到端驗證）
  - ✅ `ml/predict.py` 線上推論（特徵與訓練逐欄對齊；**歷史橋接**補 lag：即時快照只累積數槽，
    缺的槽用「同站同 dow 同 slot 的上一次實際觀測」暖機，`live_slot_ratio` 誠實揭露比例）
  - ✅ dagster `forecast_table` 資產 + job `forecast_refresh` + schedule `forecast_every_30min`（5,35 分，錯開爬蟲）
  - ✅ API `/forecast` `/forecast/meta` `/forecast/station/{id}` `/forecast/alerts` `/dispatch`（含無模型時的規則型降級）`/model/report`
  - ✅ 前端：`/dispatch` 調度建議頁（新）、站點抽屜預測帶（虛線接在 7 天曲線尾端）+ 四時距卡片、首頁「未來一小時」KPI
  - ✅ Dockerfile 加 `--extra infer`（只裝 lightgbm）、`ml/upload_models.py`（模型+4 張輔助表 → S3 `models/`）
  - ✅ 模型 19 檔 58MB 已上 S3 `models/`；**修好 entrypoint「歷史已存在就整段跳過 bootstrap」**
    （否則新模型永遠進不了容器）＋ bootstrap 對 `models/` 每次取最新
  - ✅ 本機容器驗證全綠：health / forecast/meta / forecast/alerts / dispatch / model/report 全通，
    三頁截圖正常（首頁預測 KPI 228・11、/dispatch 任務表、/model 回測頁）
  - ✅ **已部署上線**（02:11:48 容器重建）；容器內 `dagster job execute -j forecast_refresh` 成功
    （1.4 秒、5,984 列、即時槽已升到 1.7%）；公開網址 `/api/forecast/meta` `/api/dispatch`
    `/api/forecast/alerts?mode={operational,strict}` `/api/model/report` 全通；
    線上 `/dispatch` 截圖：60 任務、46 個可配對出車站、合計搬運 282 台、距離全在 3 km 內
- [x] **M6 完成**：/model 回測報告頁、README、簡報大綱.md、首頁預測 KPI hero、**KPI1 調度模擬**
  - KPI1（`ml/simulate.py`，敏感度分析 4 種量能，進 MLflow）：每槽 40 站時
    純預防 27.0%／純補救(規則型) 27.8%／**一半一半 32.1%（+4.3pp）**；
    新發生的 35,450 起空車事件可在發生前到場 **14.8%**（規則型定義上 0%）
  - **關鍵設計修正**：第一版把預防與補救混在一個排序 → 已空站機率恆 0.99+ 會吃光預防名額，
    模型只贏 1–3pp；拆成兩個佇列後結論才成立
  - **最有價值的發現**：無車時間高度集中——最常空的 76 站（5%）佔 20.5% 無車時間、
    13 站超過一半時間沒車 ⇒ 那是車輛配置/站點規模問題，調度只能緩解不能根治
- [ ] **S**（05:45–07:45）加分梯隊 S1–S5（MISSION §3.5，一次一項）→ 守夜模式（§3.6）
- [ ] **M7**（07:45–08:00）最終 push + 部署驗證 + SUMMARY.md → stop

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
- 2026-08-07 00:18 — **M3 完成**（提前 172 分）：前端五頁上線。地圖不渲染的根因挖了四層：
  ① maplibre v6 worker 是 ESM、Vite 打成 iife → worker 掛掉，GeoJSON source 永遠不 ready
  ② CARTO @2x tiles 讓 style 卡住 → 底圖全黑、load 事件不觸發
  ③ 站點資料早於地圖 load 抵達 → addSource 拿到空集合
  ④ worker 的相依 maplibre-gl-shared.mjs 沒被打包 → **只有 production 壞，dev 正常**
  另新增 /api/stats/pulse（今日 + 同星期幾歷史常態）
- 2026-08-07 00:25 — 備戰重整（loop 重啟前，非 loop 輪）：§3 基準表重排（M4 自 00:15 起，超前時間轉加分梯隊 S1–S5 + 守夜模式）；
  新增 CLAUDE.md 每輪鐵律；健檢全綠：MLflow 200、.venv ml deps OK、/tmp/pw 腳本在、公開網址 health OK、dagster 00:10 新快照
- 2026-08-07 02:35 — **M6 完成並上線**：KPI1 調度模擬（雙佇列設計）+ /model 頁 KPI 區塊 + README + 簡報大綱。
  主線 M0–M6 全數完成，提前基準表約 3 小時 → 轉入加分梯隊
- 2026-08-07 02:16 — **M4+M5 完成並上線**。回測（6 月）：h60 MAE 2.052 台勝 persistence 7.3%、h180 勝 21.0%；
  事件級預警在營運門檻下空車偵測 68.1%／平均提前 147 分（規則型恆為 0 分）。三個關鍵修正：
  ① 事件評估原本只用 70% 門檻算出 6.5% 偵測率——那是門檻造成的假象，改成雙門檻並存
  ② entrypoint「歷史已存在就整段跳過 bootstrap」會讓新模型永遠進不了容器
  ③ 調度配對出現 19 km 的荒謬任務 → 加 3 公里上限，配不到就標調度中心出車
  另補：README、簡報大綱.md、/model 頁
- 2026-08-07 01:25 — M4 特徵庫 85 秒完成（train 859 萬 / valid 224 萬 / test 216 萬列）；訓練踩兩坑後穩定跑：
  ① DuckDB `.df()` 6.7 秒衝到 4G 被 OOM 殺 → SQL 端 CAST 成 4 bytes + Arrow `self_destruct` + 抽樣 0.35→0.22 + valid 抽 0.5，
    峰值降到 **1.88G**（先寫 memcheck smoke test 驗過才開跑，沒有再賭一次）
  ② `_out/models/` 是先前 docker 掛載留下的 **root 擁有**目錄 → LightGBM 存檔被拒（exit 0 但沒模型），rmdir 重建即解
  同一輪把 M5 全部程式碼寫完（見上）；前端 `tsc --noEmit` 通過
- 2026-08-07 00:58 — ⚠️ 資源事故復盤（非 loop 輪）：M4 首跑無上限把 8 核/14GB 吃滿，swap 灌滿 3.9/4G，**同機的 production
  （Dokploy/Traefik/全部 *.itsmygo.uk）跟著遭殃，Dokploy 重啟過一次**。對策：CLAUDE.md 新增資源鐵律 7–9（systemd-run 罩
  4G/400%/nice19、num_threads=3、DuckDB 3GB/3t、跑前 free -g）；train.py / features.py 配額已改；§3 二次基準（M4 至 02:45）

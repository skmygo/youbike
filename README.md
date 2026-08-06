# YouBike 調度預警指揮台

新北市 YouBike 2.0 的**空滿預警與調度決策系統**：把六個月的歷史快照做成可回放的資料底座，
接上每 10 分鐘的即時爬取，再用 LightGBM 預測未來 30／60／120／180 分鐘的站點水位與空滿風險，
最後輸出一張「車該從哪裡搬到哪裡」的調度清單。

**線上展示**：<https://youbike.itsmygo.uk>　·　**簡報**：<https://youbike.itsmygo.uk/slides.html>（方向鍵翻頁）

| 頁面 | 回答的問題 |
|---|---|
| `/` 即時指揮 | 現在全市哪裡出事？（KPI＋地圖＋待處理清單＋全市空滿脈搏帶） |
| `/replay` 歷史回放 | 那天到底發生什麼事？（任一時刻的全市快照，可播放一整天） |
| `/alerts` 警示 | 現在有哪些站需要處理／**接下來哪些站會出事** |
| `/dispatch` 調度建議 | 這一小時，車該從哪裡收、補到哪裡 |
| `/districts` 區域分析 | 哪一區問題最嚴重？什麼時段最痛？ |
| `/model` 預測模型 | 模型好在哪、差在哪（6 月測試集全指標＋限制揭露） |

![主動線 demo](docs/demo.gif)

> 錄的是線上實況：首頁 → 調度任務單 → 預測型警示 → 站點抽屜（7 天曲線接上預測帶）→ 回測報告。

---

## 這個系統在解什麼問題

命題點出三個痛點，系統一一對應：

1. **看得到現況、看不到趨勢** → 歷史回放＋脈搏帶＋預測帶
2. **系統不會主動通知機關** → 四級警示（注意／警戒／嚴重＋**預測型**）
3. **調度靠經驗，缺決策依據** → 由預測導出的調度任務清單，附機率、缺口與最近的出車站

---

## 架構

```
新北開放平台 ──每 10 分鐘──▶ Dagster realtime_refresh
                              ├─ realtime_snapshot   raw/snap_*.parquet
                              ├─ station_registry    serving/stations.parquet
                              ├─ serving_snapshots   serving/{recent,latest}.parquet
                              └─ alerts_table        serving/alerts.parquet
                                                          │
歷史 6 個月 ─▶ DuckDB 清洗 ─▶ history/snapshots_2026*.parquet
                                    │                     │
                                    ▼                     ▼
                            ml.features            Dagster forecast_refresh（每 30 分）
                            ml.train  ─▶ models/    └─ ml.predict ─▶ serving/forecast.parquet
                            ml.evaluate ─▶ report.json                     │
                                                                           ▼
                                              FastAPI（DuckDB 讀 parquet）─▶ React 前端
```

**兩條鐵律貫穿設計**

- **API 請求路徑絕不跑模型**：推論由 Dagster 排程算好寫 parquet，API 只讀檔，每個請求開 in-memory 連線。
- **DuckDB 檔案不共用**：Dagster 寫、API 讀，一律以 parquet 交換，寫入都是「寫 .tmp → 原子 rename」。

---

## 資料

- 歷史：2026-01-01 ~ 06-30，**1,324 萬筆**有效快照、1,567 站、30 分鐘一格
- 全期空車率 5.11%、滿位率 1.68%
- 資料品質處理：站名去重與修正、離線站辨識（有車柱卻既無車也無空位，約 35–46 站，排除於統計與警示）
- 即時來源比歷史多 10 站，新站配號 ≥900000；新北平台憑證缺 Subject Key Identifier，
  爬蟲先走正常驗證、僅在憑證錯誤時降級重試

## 模型

- **切分**：1–4 月訓練 ／ 5 月驗證（早停）／ **6 月測試（訓練全程沒碰過）**，時間序不洗牌
- **特徵 41 個**：當下狀態、lag（30 分～一週）、動能、rolling 統計、時間、站點靜態、
  歷史常態與偏離、鄰域／行政區／行為分群的同步訊號、已持續空滿的槽數
- **無洩漏**：歷史常態只用訓練期統計；目標欄一律 `LEAD`，特徵只用當下與過去
- **兩個 baseline 先跑**：現況延續（persistence）與上週同日同時段；模型在四個時距全部勝出，
  且時距越長優勢越大——短期 persistence 本來就強，**但調度需要的是長一點的前置時間**
- 12 個模型：4 個時距 × （水位回歸 + 空事件分類 + 滿事件分類），全程進 MLflow

完整指標（含 PR-AUC、事件級提前預警分鐘數、誤報率、特徵重要度、限制）見線上 `/model` 頁與 `models/report.json`。

### 預警門檻是雙軌的

規劃書定義的 70% 是**高信心門檻**，精確率高但召回低，長時距幾乎不會觸發。
系統同時輸出**營運建議門檻**（驗證集上 F1 最佳，各時距不同，約 10–30%），
`/dispatch` 與預測型警示預設用後者——換到的是來得及派車的前置時間。兩者在報告中都列出。

---

## 開發

```bash
uv venv && uv pip install -e ".[pipeline,ml]"      # 或 pip install -e ".[pipeline,ml]"

# 1. 歷史資料 → parquet
python -m pipeline.export_history

# 2. 特徵庫 → 訓練 → 6 月回測
python -m ml.features
python -m ml.train
python -m ml.evaluate

# 3. 本機起 API + 前端
uvicorn api.main:app --reload
cd web && pnpm install && pnpm dev

# 4. Dagster（排程與資產）
DAGSTER_HOME=$PWD/_out/dagster dagster dev -m pipeline.defs
```

環境變數：`YOUBIKE_DATA_DIR`（資料根目錄，容器內為 `/data`）、
`MLFLOW_TRACKING_URI`、`S3_ENDPOINT` / `S3_BUCKET` / `S3_ACCESS_KEY` / `S3_SECRET_KEY`。

> 本專案的訓練機同時是正式服務主機，所有重活都戴資源罩跑：
> `systemd-run --user --scope -p MemoryMax=4G -p CPUQuota=400% nice -n 19 <指令>`，
> LightGBM `num_threads=3`、DuckDB `memory_limit=3GB`。訓練集抽樣比例因此設在 22%。

## 部署

單一多階段 `deploy/Dockerfile`（前端 build → Python runtime），一個 image 兩種角色：
`entrypoint.sh api` 起 FastAPI、`entrypoint.sh dagster` 起排程。
容器啟動時 `pipeline.bootstrap` 會從 S3 補齊缺少的 `history/`、`serving/`、`models/`。

## API

| 端點 | 說明 |
|---|---|
| `GET /api/health` `/api/meta` | 健康檢查、資料涵蓋範圍 |
| `GET /api/stations` `/api/stations/{id}` `/api/stations/{id}/history` | 站點清單／詳情／歷史曲線 |
| `GET /api/replay?ts=` `/api/replay/days` | 任一時刻全市快照、可回放日期 |
| `GET /api/stats/{overview,hourly,districts,worst,pulse}` | 統計與脈搏帶 |
| `GET /api/alerts` | 規則型三級警示 |
| `GET /api/forecast` `/forecast/meta` `/forecast/station/{id}` `/forecast/alerts` | 模型預測與預測型警示 |
| `GET /api/dispatch` | 調度建議（模型未就緒時自動降級為規則型） |
| `GET /api/model/report` `/api/model/kpi` | 6 月回測完整報告、KPI1 調度改善模擬 |
| `POST/GET /api/notify/log` | 主動通知：Dagster 把新升級為警戒／嚴重的站推來，警示頁顯示紀錄 |

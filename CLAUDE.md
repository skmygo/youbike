# YouBike 黑客松衝刺 — 每輪鐵律（自動載入；違反 = 白做工）

隔夜衝刺進行中：作戰手冊 `MISSION.md`（基準表/降級/加分梯隊/守夜）、狀態帳本 `PROGRESS.md`（每輪必讀必寫；「關鍵設施」表已存 composeId / S3 / venv / 驗證指令，**不要重查**）、需求正本 `ref_data/分析規劃.html`。架構已定案：**不重新發明、不換技術棧**。

## 部署與驗收（歷史上最常出事的地方）

1. **push 不會自動部署**。`git push` 後必用 dokploy-mcp `compose-deploy`（composeId 見 PROGRESS.md）→ 等 build 綠 → curl 公開網址 `https://youbike.itsmygo.uk` 驗收（不是 localhost）。
2. **前端改動先本機容器驗過再 push**（dev 正常 ≠ production 正常；maplibre worker 只在 production 壞過）：`docker build` → `docker run --rm -d --name yb-prod -p 18010:8000 -v $PWD/_out:/data <image>` → `node /tmp/pw/shot.mjs <url> <out.png>` 看截圖+console。
   **絕不開 Chrome**（禁用 claude-in-chrome / mcp__claude-in-chrome__* 全部工具；遠端 Chrome 也載不動 maplibre worker）——需要瀏覽器互動、截圖、console 驗證時一律用 `playwright-cli` 這個 skill（headless）。
3. DuckDB 併發鐵律:api / dagster 絕不共用 .duckdb 檔；交換一律 parquet（寫端原子 rename），API 每請求 in-memory 連線。

## ML（M4/M5）

4. 訓練跑本機 `.venv`（deps 已裝好、已驗證 import OK）；`MLFLOW_TRACKING_URI=http://192.168.50.190:5000`、experiment `youbike-hackathon`，所有 run 進 MLflow。
5. 切分：1–4 月訓練 / 5 月驗證 / 6 月測試，時間序不洗牌、嚴防未來洩漏；**baseline（persistence、上週同日同時段）先跑**，LightGBM 贏不過就分層誠實呈現（規劃書明說這樣反而加分）。
6. 模型檔 + `report.json` 上 S3 bucket `youbike` → 容器 bootstrap 拉；線上預測由 dagster 排程算好寫 parquet（只對最新快照 ~1,600 行推論，輕量），**API 請求路徑絕不跑模型**。

## 本機資源鐵律（最高優先——本機就是 .217 production 主機，吃滿 = 全部 *.itsmygo.uk 服務陪葬）

機器只有 8 核 / 14GB RAM，production 常駐（Dokploy/Traefik/youbike api+dagster/chatapp/…）已吃約 8GB。00:45 M4 首跑沒設限直接把 swap 灌滿、害同機的 Dokploy 重啟過一次——**這台電腦不能掛**。

7. 重活（特徵工程/訓練/回測/docker build）一律戴資源罩：
   `systemd-run --user --scope -p MemoryMax=4G -p CPUQuota=400% nice -n 19 <指令>`
   （systemd-run 不可用才退 `nice -n 19` + 下述執行緒上限）。被 MemoryMax 殺掉 = 縮規模重跑（訓練期抽樣 50%→30% → 預測檔位減半），**絕不把上限調大**。
8. 上限值：LightGBM `num_threads=3`；DuckDB `SET memory_limit='3GB'; SET threads=3` + `temp_directory` spill；`OMP_NUM_THREADS=3`；pandas 只載必要欄位 + float32、禁全量寬表；模型逐一訓練不並行，重活之間也不並行（訓練時不同時 docker build）。
9. 重活開跑前先 `free -g`：available < 6G 先清場（停掉用完的 yb-prod 等本機驗證容器、殺殘留訓練進程）再開工；重活進行中每次 wakeup 順手 `free -g` 並確認 production 容器健在（`docker ps` 有 dokploy 與 youbike api/dagster）。

## 節奏與資源

10. 每輪開場先 `date` 對照 MISSION.md §3 基準表；落後 >45 分啟動降級；**07:45 無論如何進 M7；08:00 寫完 SUMMARY.md 才 ScheduleWakeup stop:true**——其他任何時刻不得結束 loop。
11. Token 紀律（撞訂閱上限 = loop 猝死，頭號風險）：機械性工作派 `Agent` subagent（`model: "sonnet"`）；訓練/build/部署一律 `run_in_background` 等完成通知 + 1200s fallback wakeup，不短輪詢；不重讀大檔案（狀態都在 PROGRESS.md）；禁 Workflow / ultracode。
12. 卡住規則：同一錯誤修 3 次不過 → 換 MISSION.md §5 備案；再不過 → 記入 PROGRESS.md「阻塞」段、跳做下一個不依賴它的項目。絕不空轉等人。
13. 每輪收尾：commit + push（改到線上行為就走鐵律 1 部署驗證）+ 更新 PROGRESS.md（狀態塊 + 一行 log），才排下一輪 wakeup。

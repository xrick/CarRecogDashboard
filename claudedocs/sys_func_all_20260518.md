# 工地看板系統 — 全事件場景說明書

**日期**：2026-05-18 ｜ **產出**：`/sc:analyze`
**依據規格**：
- `refData/規格書/工地看板_UI功能設計補充規格書_趨勢與即時快訊.docx`（§1–§11）
- `refData/規格書/工地看板_UI趨勢與即時快訊模板.pptx`（模板 p.1–p.10）

**對應實作**：`src/backend/`（FastAPI + SQLite + 中性 V3.87 相機）、`src/frontend/`（PyQt5 看板）。
本文件把規格描述的功能/事件處理/UI 呈現，逐條列為事件場景；每條含：①目的功能 ②事件發生順序 ③系統處理順序 ④對應資料表/程式碼，並以假設事件說明。

---

## 0. 系統架構速覽

```
中性/Dahua 相機(.10) ──(§4.9.17 eventManager.attach 推送)──┐
   │  §3.4 Digest  §4.6.39 getSystemInfo                   │
   │  §10.3.4 recordFinder 白/黑名單                         ▼
   │  §4.4.2 snapshot.cgi 截圖                       ingest.py(IngestManager)
   │                                                  │ normalize_traffic/face
   ▼ (無相機時) mock_data.Simulator ─────────────────▶ │ _emit → db.insert_event
                                                       ▼
                                          SQLite (db.py, 8 張表)
                                                       │  REST  /dashboard/...
                                          app.py ──────┤  SSE   /dashboard/stream/events
                                                       ▼
                              PyQt5 看板 (main.py + views + api_client + rtsp_panel)
                              ApiPoller(60s 輪詢) + EventStream(SSE 即時) + RtspView(RTSP 影像)
```

### 0.1 資料表（`src/backend/db.py` `_SCHEMA`）

| 表 | 用途 | 關鍵欄位 |
|---|---|---|
| `site` | 工地主檔 | site_id, site_name, status(normal/alert/delay) |
| `event` | **進出事件日誌（單一真實來源）** | event_id, site_id, event_type, direction, event_ts, event_time, display_name, secondary_id, contractor, status, status_type, snapshot_url, confidence, why, source |
| `alert` | 異常事件牆卡片 | alert_id, type, target, site_id, why, cost_fp/fn, occurrence, resolved |
| `alert_suggestion` | 告警的 AI 建議（1:N） | alert_id, seq, text |
| `copilot_summary` | AI 副駕駛摘要 | headline, body, sources, model, generated_at |
| `system_status` | 資料源/看板健康時間序列 | plate_api_status, last_success_time, api_online/total, error_message |
| `plate_list` | 白/黑名單本地鏡像 | host, list_type(red/black), plate |
| `plate_list_meta` | 名單同步狀態 | host, list_type, snapshot_hash, last_success_ts, last_status |

KPI／在場數／每小時趨勢**不另存表**，由 `event` 當日資料 SQL 聚合（規格 §11「由看板服務端依進出事件自行計算」）。

### 0.2 程式碼地圖

| 檔案 | 職責 |
|---|---|
| `camera_client.py` | 中性 V3.87 客戶端：`get_system_info`(148)、`find_plate_list`→`PlateListResult`(158)、`stream_events`(261, eventManager.attach)、`parse_eventmanager_event`(89)、`normalize_traffic`(325)/`normalize_face`(369)、`snapshot`(309) |
| `ingest.py` | `IngestManager`(88)：`start`(100, 補水)、`_camera_loop`(151)、`_refresh_lists`(183, D4)、`_eval_list_state`(203, 過期告警)、`_handle_event`(234)、`_mark_offline`(277)、`_refresh_loop`(299)、`_simulate_loop`(135)、`_emit`(69)、`Hub`(35, SSE) |
| `db.py` | 8 表 schema + 寫/聚合讀 + 名單持久化 6 API(470–579) + `resolve_alert`(450) |
| `app.py` | REST 端點(71–151) + SSE(153) + 快照路由(145) + lifespan(connect/seed/ingest) |
| `mock_data.py` | `seed_database` 種子 + `Simulator.fabricate`（無相機備援） |
| `config.py` | `CameraConfig`(role/kind/rtsp_url) + `AppConfig`(poll_interval, effective_stale_seconds) |
| `main.py` | `MainWindow`(45)：分頁/輪播/快捷鍵/離線橫幅/跳卡疊層；`_on_data`(239)/`_on_event`(260)/`_push_flash`(275)/`set_sub`(335) |
| `api_client.py` | `ApiPoller`(27, 60s REST) + `EventStream`(93, SSE) |
| `views.py` | 6 內容視圖（overview/site/vehicle/personnel/trend/alert）|
| `rtsp_panel.py` | `RtspWorker`(52)/`RtspPanel`(103)/`RtspView`(145) 現場影像 |
| `widgets.py` | `FlashCard`/`EventRow`/`AlertCard`/`StatusBadge`/`KpiCard` 等 |

---

# 一、事件場景清單

> 對應顏色規則（規格 §2）：進場=青、離場=紫、白名單/通行=綠、陌生=黃、黑名單/證照過期=紅、未同步=灰。

---

## E01 — 看板服務啟動與名單補水

**①目的/功能**：服務重啟後立即可用「最後良好白/黑名單」分類，消除冷啟「全部陌生」窗（需求 FR-1/FR-6）。
**②事件發生順序**：
1. 執行 `uvicorn src.backend.app:app` → FastAPI `lifespan` 觸發。
2. 載入 `config.load_config()`（讀 `config/cameras.json`，無檔→simulate）。
3. `db.connect(db_path)` 建/開 SQLite（WAL）。
4. `IngestManager.start(loop)`。
**③系統處理順序**：
1. `app.py:lifespan` → `db.connect`（建 8 表，若不存在）。
2. `ingest.start`(100)：`seed_database()` 種子工地/示範告警/copilot。
3. **補水**：`db.plate_list_load_all()` → 把各 host 的 red/black 還原進 `IngestManager._lists`（早於相機 thread）。
4. 若 simulate → 起 `_simulate_loop`；若有相機 → 每相機起 `_camera_loop` thread + `_refresh_loop`。
**④資料表/程式碼**：`plate_list`/`plate_list_meta`（讀）、`site`/`alert`/`copilot_summary`（種子）；`app.py:lifespan`、`ingest.py:start:100`、`db.py:connect:124 / plate_list_load_all:532 / seed_database`。
**假設事件**：服務昨日已同步 A03 白名單 {ABC-5288, XYZ-3344}，今早重啟 → 補水後第一台 ABC-5288 進場即判「白名單」，不會誤判「陌生」。

---

## E02 — 看板前端首次資料載入

**①目的/功能**：50 吋看板開機後 3–5 秒內呈現首屏 KPI/事件/趨勢（規格 §2 資訊優先順序）。
**②事件發生順序**：`python -m src.frontend.main` → `MainWindow` 建構 → `ApiPoller` 與 `EventStream` 啟動 → 立即第一次輪詢。
**③系統處理順序**：
1. `ApiPoller.run`(api_client.py) 立即拉 `_snapshot(site)`：依序 GET `/dashboard/sites/summary`、`/sites/{id}/summary`、`/events/latest`、`/trends/hourly`、`/system/status`、`/alerts`、`/copilot`、`/cameras`。
2. `data_ready` 訊號 → `main.py:_on_data:239` 合併入 `self._snapshot` → 重繪當前 view。
3. `EventStream.run`(93) 連 SSE `/dashboard/stream/events`，等待推送。
**④資料表/程式碼**：聚合自 `event`/`site`/`alert`/`copilot_summary`/`system_status`；`app.py:73-151`、`db.py:sites_summary:275 / hourly_trend:338 / alerts:388`、`api_client.py:ApiPoller:27`、`main.py:_on_data:239`。
**假設事件**：警衛室電視開機 → 2.5 秒後顯示「全工地總覽」：今日人員進場 1,286、12 張工地卡、右側最新快訊清單。

---

## E03 — 車輛進場（白名單命中）

**①目的/功能**：車牌平台辨識到白名單車輛進場，看板即時顯示綠色「白名單 · 閘門已開啟」並計入趨勢（規格 §4.3、§5）。
**②事件發生順序**：
1. 砂石車 ABC-5288 駛入 A03 入口（entry 相機）。
2. 相機 ALPR 辨識 → 透過 §4.9.17 `eventManager.attach` 推一個 `Code=TrafficJunction;...;data={"TrafficCar":{"PlateNumber":"ABC-5288",...}}`。
**③系統處理順序**：
1. `camera_client.stream_events`(261) 收 multipart part → `parse_eventmanager_event`(89) 解析出 `{code,action,index,data}`。
2. `ingest._camera_loop`(151) → `_handle_event`(234)：合成 `EventBaseInfo`；查 `db.plate_list_state(host)` 得 `fresh`。
3. `normalize_traffic`(325)：`ABC-5288 ∈ redlist` → status=「白名單」, status_type=`whitelist`, direction=`IN`（entry→IN），access=「閘門已開啟」。
4. 嘗試 `client.snapshot(channel)`（§4.4.2）→ 存 `data/snapshots/<id>.jpg` → 設 `snapshot_url`。
5. `_emit`(69)：`db.insert_event`（冪等）→ 非告警不建 alert → `Hub.broadcast` JSON。
6. 後端 SSE `/dashboard/stream/events` 推給前端 → `main.py:_on_event:260` 併入事件、`_push_flash:275` 跳卡、刷新當前 view。
**④資料表/程式碼**：寫 `event`；讀 `plate_list`/`plate_list_meta`；`camera_client.py:261/89/325/309`、`ingest.py:234/69`、`db.py:insert_event:163`、`app.py:stream_events:153`、前端 `widgets.FlashCard`/`EventRow`、`main.py:260/275`。
**UI 呈現**：右下跳卡（青框，車輛截圖+ABC-5288+大榮土木+白名單徽章+「閘門已開啟」綠字，5 秒後消失），同時進入右側「最新進出快訊」清單頂部；當日趨勢「車輛進場」當前小時 +1。

---

## E04 — 車輛進場（黑名單命中）→ 異常告警

**①目的/功能**：黑名單車輛出現，必須紅色置頂醒目、中斷輪播、進異常事件牆並通知（規格 §2 事件快訊、§5 優先級「黑名單最高」）。
**②事件發生順序**：黑名單 ZZZ-7777 進入 A03 → 相機推 TrafficJunction 事件。
**③系統處理順序**：
1–2. 同 E03 解析。
3. `normalize_traffic`：`ZZZ-7777 ∈ blacklist` → status=「黑名單」, status_type=`blacklist`, access=「拒絕」。
4. `_emit`(69)：`db.insert_event` 後，因 `status_type ∈ (blacklist,alert)` → `db.insert_alert(type="blacklist", id=al_<eventid>, …)` 並寫 `alert_suggestion`。
5. `Hub.broadcast` → 前端 `_on_event`：`_push_flash`（紅框、8 秒、含判定依據與「確認告警/標記誤判」按鈕）；若自動輪播中 → `main.py` 立即 `set_sub("alert")` 中斷輪播切到異常事件牆。
**④資料表/程式碼**：寫 `event`+`alert`+`alert_suggestion`；`camera_client.normalize_traffic:325`、`ingest._emit:69`、`db.insert_alert:187`、`main.py:_on_event:260`（嚴重告警中斷輪播）、`widgets.FlashCard`（isAlert 分支）、`views.AlertView:353`/`widgets.AlertCard`。
**UI 呈現**：中央/右下紅色大跳卡（8 秒或人工關閉）；頂部紅色警示列；異常事件牆出現 ZZZ-7777 卡（信心度、判定依據、FP/FN 代價、AI 建議、人工拍板鈕）。

---

## E05 — 陌生車牌（白/黑名單皆未命中，名單為 fresh）

**①目的/功能**：辨識成功但不在名單 → 標黃「陌生」、提示待確認、計陌生數（規格 §4.3、模板 p.7「陌生車牌自動 UNKNOWN」）。
**②事件發生順序**：未登錄車牌 UNKNOWN-018 進入 A02。
**③系統處理順序**：同 E03，`normalize_traffic` 落入 `else`（list_state=fresh）→ status=「陌生」, status_type=`stranger`, access=「人工確認」；非告警不建 alert（陌生不升級為告警，除非規格要求；目前以黃色快訊呈現）。
**④資料表/程式碼**：寫 `event`；`camera_client.normalize_traffic:325`（fresh+未命中分支）、`ingest._emit:69`；前端黃色 `StatusBadge("stranger")`。
**假設事件**：UNKNOWN-018 進 A02 → 黃色跳卡「陌生 · 人工確認」，KPI「陌生車牌」+1。

---

## E06 — 車輛事件（名單未同步 UNSYNCED）→ pending

**①目的/功能**：全新部署或相機從未成功同步名單時，不可把所有車誤判「陌生」；顯示「名單未同步（系統安裝中）」（需求 FR-10/D5）。
**②事件發生順序**：新工地相機剛裝、recordFinder 尚未成功 → 任一車牌進場。
**③系統處理順序**：`_handle_event`(234) 查 `db.plate_list_state(host)`＝`unsynced`（meta 無 last_success_ts）→ `normalize_traffic`(325) 命中 `elif list_state=="unsynced"` → status=「名單未同步」, status_type=`pending`, access=「系統安裝中」。
**④資料表/程式碼**：讀 `plate_list_meta`；`db.plate_list_state:553`、`camera_client.normalize_traffic:325`；前端 `widgets.StatusBadge._MAP["pending"]`（中性灰）。
**假設事件**：C04 試運轉區相機今日首裝，名單還沒同步 → 進場車輛顯示灰色「名單未同步（系統安裝中）」而非「陌生」，且不發陌生告警。

---

## E07 — 人員進出（人臉辨識通行）

**①目的/功能**：對接人臉平台，顯示姓名/工號/承攬商/證照狀態與人臉截圖（規格 §4.4、模板 p.6）。
**②事件發生順序**：王O明走過 B01 入口 → 相機推 `Code=FaceRecognition;...;data={"Candidates":[{"Person":{"Name":"王O明","ID":"E-1029"},"Similarity":94}]}`。
**③系統處理順序**：
1. `stream_events`/`parse_eventmanager_event` 解析。
2. `_handle_event`(234) code==FaceRecognition → `normalize_face`(369)：取 top candidate → display_name=王O明、secondary_id=E-1029、confidence=0.94、status_type=`pass`（OUT 時顯示「離場」）。
3. 抓 snapshot → `_emit` 寫 `event` → 廣播。
**④資料表/程式碼**：寫 `event`；`camera_client.normalize_face:369`、`ingest._handle_event:234`、`db.insert_event:163`；前端 `widgets.PersonnelDetailRow`/`FaceSnapshot`、`views.PersonnelView:290`。
**UI 呈現**：人員看板列出「進 14:31 王O明 / E-1029 · 正興機電 · 通行」，附人臉縮圖；人員每小時趨勢 +1。

---

## E08 — 人員證照過期 → 告警

**①目的/功能**：證照過期需紅色告警並置頂、進異常牆（規格 §4.4 證照狀態、§5 優先級「證照過期最高」）。
**②事件發生順序**：李O華（電焊作業證已過期）走過 A03 → FaceRecognition 事件，detail 含「證照過期」。
**③系統處理順序**：`normalize_face`(369) 判定 → status=「告警」, status_type=`alert` → `_emit`(69) 因 `alert` 觸發 `db.insert_alert(type="expired",…)`+suggestions → SSE → 前端紅色跳卡 8 秒 + 中斷輪播切異常牆。
**④資料表/程式碼**：寫 `event`+`alert`+`alert_suggestion`；`camera_client.normalize_face:369`、`ingest._emit:69`、`db.insert_alert:187`；前端 `AlertCard`(type=expired，FaceSnapshot alert)。
**假設事件**：李O華 / E-0981 電焊證過期 71 天 → 紅卡「需人工確認」，異常牆顯示 FP/FN 代價與「請工人補件/通知工安督導」建議。

---

## E09 — 即時快訊跳卡（觸發/堆疊/優先級/消失）

**①目的/功能**：新事件 1 秒內彈大卡，現場一眼判斷；最多 3 張，依優先級排隊；一般 5 秒、告警 8 秒（規格 §5）。
**②事件發生順序**：E03/E04/E07/E08 任一事件經 SSE 抵達前端。
**③系統處理順序**：
1. `EventStream`(api_client.py:93) 收 SSE `data:` → `new_event` 訊號。
2. `main.py:_on_event:260`：併入事件清單 → `_push_flash:275` 建 `widgets.FlashCard`，加入右下疊層；超過 3 張移除最舊。
3. `FlashCard` 內 `QTimer.singleShot(8000 if alert else 5000)` → `closed` 訊號 → `_dismiss_flash` 移除；事件仍留在右側清單（規格 §5 保留策略）。
4. 若為 blacklist/alert 且自動輪播中 → 立即切 `alert` 視圖。
**④資料表/程式碼**：`api_client.EventStream:93`、`main.py:_on_event:260/_push_flash:275`、`widgets.FlashCard`；資料來源 `event`（SSE 廣播）。
**假設事件**：6 秒內連來 2 車 1 人 → 右下由下往上堆 3 張卡；黑名單那張紅框置頂 8 秒並把畫面切到異常事件牆。

---

## E10 — 每小時趨勢更新與「目前小時」標線

**①目的/功能**：今日 0–24 時每小時人/車進出趨勢，標示目前小時與峰值（規格 §6、模板 p.8）。
**②事件發生順序**：任一進出事件寫入 `event`；前端每輪詢/每事件重繪趨勢。
**③系統處理順序**：
1. 事件 `event_ts` 落 `event` 表。
2. 前端取 `/dashboard/sites/{id}/trends/hourly` → `db.hourly_trend`(338)：`GROUP BY strftime('%H',event_ts)` 聚合當日 people_in/out、vehicle_in/out（0–23 補零）；`current_hour`=本地現在時。
3. `views.TrendView:330`/`SiteBoardView` 以 `charts.HourlyChart` 畫長條+折線，紅色「目前 N 時」參考線。
**④資料表/程式碼**：聚合 `event`；`db.hourly_trend:338`、`app.py:hourly_trend:102`、前端 `charts.HourlyChart`、`views.TrendView:330`。
**假設事件**：14:32 ABC-5288 進場 → `event` +1 → 下次刷新趨勢「車輛進場」14 時長條 +1，紅線標「目前 14 時」。

---

## E11 — AI 趨勢預測（虛線 + 信賴帶）

**①目的/功能**：在實際趨勢右側延伸 4 小時預測，含上下信賴帶（模板 p.4「AI 預測延伸 4H · 信賴帶 ±30%」）。
**②事件發生順序**：前端取 `/trends/hourly` 同時回傳 `forecast`。
**③系統處理順序**：`db.hourly_trend`(338) 由目前小時 people_in 以 `0.9^offset` 推 4 點，上界×1.3、下界×0.7 → `forecast[]`；前端 `HourlyChart` 畫虛線 + 半透明信賴帶錐形。
**④資料表/程式碼**：`db.hourly_trend:338`(forecast 區段)、前端 `charts.HourlyChart`(forecast cone)。
**假設事件**：14 時人員進場 18 → 預測 15/16/17/18 時遞減點，畫成青色虛線與淡青信賴帶。

---

## E12 — KPI 與在場人數/車數即時計算

**①目的/功能**：第一層資訊：進場/離場人次車次、目前在場（規格 §2、§4.1/§4.2）。
**②事件發生順序**：任一進出事件後，前端輪詢或事件刷新。
**③系統處理順序**：`db.sites_summary`(275)/`site_summary`(263)：`_site_counts`＝當日 `SUM(direction='IN')/OUT`；在場＝`max(IN-OUT,0)`；overview 跨工地加總（規格 §11 由看板端依進出事件自算）。
**④資料表/程式碼**：聚合 `event`+`site`；`db.sites_summary:275 / site_summary:263`、`app.py:71-91`、前端 `widgets.KpiCard`、`views.OverviewView/SiteBoardView`。
**假設事件**：A03 今日 IN 51 車、OUT 38 車 → KpiCard「車輛在場 13」。

---

## E13 — 名單輪詢成功且有變動 → 寫回 SQLite

**①目的/功能**：相機白/黑名單變動時，本地鏡像差異更新以利重啟後分類（需求 FR-2/FR-7、D2/D3）。
**②事件發生順序**：`_camera_loop` 連上相機 → `_refresh_lists`；或 `_refresh_loop` 週期。
**③系統處理順序**：
1. `_refresh_lists`(183)：對 red/black 各 `client.find_plate_list(name)`(158) → `PlateListResult`。
2. `ok 且 plates 非空` → `db.plate_list_replace`(470)：sha1 差異比對；不同→單交易 `DELETE+INSERT` 明細 + 更新 meta（hash/last_success_ts/last_change_ts）；相同→只更新時間（FR-3 不重寫）。
3. `self._lists[host]` 由 `db.plate_list_get` 重新載入（權威值）。
4. `_eval_list_state`(203) 重評狀態。
**④資料表/程式碼**：寫 `plate_list`+`plate_list_meta`；`camera_client.find_plate_list:158`、`ingest._refresh_lists:183`、`db.plate_list_replace:470 / plate_list_get:525`。
**假設事件**：相機白名單新增 KLM-0921 → recordFinder 回 3 筆 → hash 變 → 整批取代 → 重啟後 KLM-0921 即判白名單。

---

## E14 — 名單 found=0 或抓取失敗 → 永不清空（D4 最終）

**①目的/功能**：避免相機短暫異常或回空導致整份名單被清掉（需求 FR-4/FR-5、D4 最終版「found=0 保留不覆蓋」）。
**②事件發生順序**：`recordFinder` 回 `found=0`（成功但空），或連線/HTTP 失敗。
**③系統處理順序**：`_refresh_lists`(183) → `res.ok 但 plates 空`（found=0）或 `not res.ok`（失敗）→ 走 `db.plate_list_touch`(499)：**只更新 last_attempt_ts，不刪明細、不刷 last_success_ts** → 既有快照保留；隨時間 → 走向 stale（見 E15）。
**④資料表/程式碼**：只動 `plate_list_meta`；`camera_client.find_plate_list:158`(回 ok=True/plates=∅ 或 ok=False)、`ingest._refresh_lists:183`、`db.plate_list_touch:499`。
**假設事件**：實機 .10 白名單目前 `found=0` → `PlateListResult(ok=True, plates=∅)` → 本地若曾有快照則維持不變；若從未有 → 維持 unsynced（E06）。

---

## E15 — 名單過期 → 異常事件牆告警

**①目的/功能**：名單距最後成功同步超過門檻，於異常牆顯示「名單過期/未同步」卡（需求 FR-11/D6）。
**②事件發生順序**：found=0/失敗持續，`last_success_ts` 不再更新；時間超過 `effective_stale_seconds`（預設 `max(120,2×poll_interval)`，R-1）。
**③系統處理順序**：`_eval_list_state`(203)（由 `_refresh_lists` 與 `_refresh_loop` 週期呼叫）→ `db.plate_list_state`(553) 回 `stale`/`unsynced` → `db.insert_alert(type="list_stale", id="liststale_<host>", …)`（固定 id 自我取代）。
**④資料表/程式碼**：讀 `plate_list_meta`、寫 `alert`+`alert_suggestion`；`ingest._eval_list_state:203 / _refresh_loop:299`、`db.plate_list_state:553 / insert_alert:187`；前端 `widgets.AlertCard._META["list_stale"]`、`views.AlertView:353`。
**假設事件**：相機連 5 分鐘 recordFinder 失敗 → 異常牆出現黃卡「名單過期 · 最後同步 10:00 · 通知 IT 排查」。

---

## E16 — 名單恢復 fresh → 自動清除告警

**①目的/功能**：名單再次成功同步後，過期告警應自動消失（需求 FR-11 收斂）。
**②事件發生順序**：recordFinder 再次成功且非空 → `plate_list_replace` 刷新 `last_success_ts`。
**③系統處理順序**：`_eval_list_state`(203) → `plate_list_state` 回 `fresh` → `db.resolve_alert("liststale_<host>")`(450) 設 `resolved=1` → `db.alerts`(388) 以 `resolved=0` 過濾 → 該卡從異常牆消失。
**④資料表/程式碼**：`alert`(resolved 欄)；`ingest._eval_list_state:203`、`db.resolve_alert:450 / alerts:388`。
**假設事件**：相機恢復、白名單回 3 筆 → 下一輪「名單過期」卡自動撤下。

---

## E17 — 相機/API 斷線（保留最後資料 + 離線提示 + api_delay 告警）

**①目的/功能**：斷線不可清空畫面，需保留最後成功資料並醒目提示（規格 §7 離線提示、§10 斷線處理）。
**②事件發生順序**：相機不可達／`get_system_info` 例外／事件串流中斷。
**③系統處理順序**：
- 後端：`_camera_loop`(151) 捕捉 `CameraError`/`Exception` → `_mark_offline`(277)：`db.record_status(plate_api_status="down", error_message=…)` + `db.insert_alert(type="api_delay", id="apidelay_<host>")`；`_refresh_loop`(299) 週期健康檢查同樣處理；退避重連。
- 前端：`ApiPoller`(27) 請求失敗 → `online_changed(False)` → `main.py` 顯示頂部紅色離線橫幅「API 連線中斷 · 已保留最後成功資料（最後更新 hh:mm）」，**畫面不清空**（沿用 `self._snapshot` 最後快照）。
**④資料表/程式碼**：寫 `system_status`+`alert`；`ingest._mark_offline:277 / _camera_loop:151 / _refresh_loop:299`、`db.record_status:219 / insert_alert:187`、`api_client.ApiPoller:27`、`main.py:_on_online`（離線橫幅）、`views.AlertView`。
**假設事件**：A03 相機網路中斷 92 秒 → 頂部紅列 + 異常牆「車牌平台回傳延遲」卡；KPI 維持斷線前數字。

---

## E18 — SSE 推送中斷 → 自動重連 + 60 秒輪詢備援

**①目的/功能**：推送優先，斷則 60 秒輪詢備援，不漏資料（規格 §2 刷新模式、§11）。
**②事件發生順序**：SSE 連線中斷（後端重啟/網路）。
**③系統處理順序**：`api_client.EventStream`(93) 連線例外 → `stream_online(False)` → 指數退避（上限 15s）重連；同時 `ApiPoller`(27) 每 `interval`（預設 60s）持續輪詢補位，倒數歸零自動刷新（`main.py` 刷新倒數列）。
**④資料表/程式碼**：`api_client.EventStream:93 / ApiPoller:27`、`app.py:stream_events:153`(SSE keep-alive)、`main.py`(刷新倒數)。
**假設事件**：後端重啟 8 秒 → 前端 SSE 斷、橫幅提示，60s 輪詢仍更新；後端回來 SSE 自動接回，跳卡恢復。

---

## E19 — 截圖缺失 → 替代圖示

**①目的/功能**：圖片缺失須顯示替代圖示與錯誤提示（規格 §10 驗收「截圖顯示」）。
**②事件發生順序**：`eventManager.attach` 無內嵌 jpeg；`client.snapshot()`(309) 失敗或無檔。
**③系統處理順序**：`_handle_event`(234) try/except 抓 snapshot 失敗 → `snapshot_url` 維持 None；前端 `widgets.VehicleSnapshot/FaceSnapshot` 以向量佔位圖（車輛/人臉示意 + 車牌字樣）呈現，不空白。
**④資料表/程式碼**：`event.snapshot_url`(可為 NULL)；`camera_client.snapshot:309`、`ingest._handle_event:234`、`app.py:snapshot:145`(404→前端 fallback)、前端 `widgets.VehicleSnapshot/FaceSnapshot`。
**假設事件**：snapshot.cgi 逾時 → 跳卡仍顯示車輛示意圖 + ABC-5288 黃底車牌，不留白。

---

## E20 — 切換工地

**①目的/功能**：看板端僅允許切換工地（規格 §7、模板 p.9）。
**②事件發生順序**：使用者選下拉選單，或按 ← →（規格 §9 方向鍵）。
**③系統處理順序**：`main.py` site 下拉 `currentIndexChanged` / Left-Right key → `_on_site_changed`：設 `self._site`、清 `_extra_events`、`ApiPoller.set_site()` 並立即喚醒輪詢 → 新工地 snapshot → 重繪。
**④資料表/程式碼**：讀（依 site 過濾）`event`/聚合；`main.py:_on_site_changed / set_site`、`api_client.ApiPoller.set_site`、`db.*` 帶 `site_id`/`ALL`。
**假設事件**：從「全部工地」切到「A03 機電棟」→ KPI/趨勢/事件/相機清單全部換成 A03。

---

## E21 — 切換畫面模式（6+1 視圖 / 快捷鍵 1–7）

**①目的/功能**：總覽/單工地/車輛/人員/趨勢/異常牆/現場影像切換（規格 §3、§9）。
**②事件發生順序**：點子分頁鈕或按數字鍵 1–7。
**③系統處理順序**：`main.py:SUB_TABS:36` 對應；`eventFilter` 攔鍵或鈕 clicked → `set_sub(sid)`(335)：`QStackedWidget` 切 `VIEW_CLASSES[sid]`、`view.update_state(_compose())`、（自動輪播中）重置該視圖停留秒數。
**④資料表/程式碼**：`main.py:SUB_TABS:36 / set_sub:335`、`views.VIEW_CLASSES:397`、`rtsp_panel.RtspView:145`（cctv=7）。
**假設事件**：按「5」→ 趨勢全螢幕；按「7」→ RTSP 現場影像面板。

---

## E22 — 自動輪播（開關 + 嚴重告警中斷）

**①目的/功能**：總覽30→單工地30→車輛20→人員20 秒輪播；黑名單/證照過期立即中斷輪播顯示告警（規格 §7、模板 p.2、§5）。
**②事件發生順序**：使用者按「自動輪播」鈕；或輪播中來嚴重告警。
**③系統處理順序**：`main.py` `_toggle_auto` 設旗標、`ROTATION:40` 計時；`_rotate` 依 `ROTATION_ORDER:42` 循環；`_on_event:260` 收到 `status_type∈(blacklist,alert)` → 立即 `set_sub("alert")` 並重置輪播。
**④資料表/程式碼**：`main.py:_toggle_auto / _rotate / ROTATION:40 / ROTATION_ORDER:42 / _on_event:260`。
**假設事件**：輪播停在「人員看板」時黑名單 ZZZ-7777 進場 → 立刻跳「異常事件牆」並紅卡告警。

---

## E23 — 手動刷新

**①目的/功能**：R 鍵或倒數歸零立即向 API 重取（規格 §7、§9）。
**②事件發生順序**：按 R；或刷新倒數到 0。
**③系統處理順序**：`main.py` 鍵盤 R / 倒數計時器 → `ApiPoller.request_refresh()` 喚醒輪詢執行緒立即抓 snapshot → `_on_data:239` 重繪；倒數列重置 60。
**④資料表/程式碼**：`api_client.ApiPoller.request_refresh`、`main.py`(倒數/鍵盤)、`db.*` 聚合讀。
**假設事件**：值班人員按 R → 1 秒內 KPI/趨勢刷新為最新。

---

## E24 — 全螢幕 / 控制列收合

**①目的/功能**：kiosk 模式；控制列滑鼠/Esc 顯示、5 秒自動隱藏（規格 §7、§9）。
**②事件發生順序**：F11；滑鼠移動或 Esc；靜置 5 秒。
**③系統處理順序**：`main.py:eventFilter` → F11 切 `showFullScreen/showNormal`；MouseMove/Esc 顯示控制列並重啟 5 秒 `_hide_ctrl` 計時器；逾時隱藏。
**④資料表/程式碼**：`main.py:eventFilter / _hide_ctrl`（純前端，無資料表）。
**假設事件**：啟動即 `--fullscreen`；操作後 5 秒控制列自動收起不擋看板。

---

## E25 — RTSP 現場影像面板（顯示/離開停止/斷線重連）

**①目的/功能**：現場即時影像（規格 §4.1.1 RTSP；模板現場影像參考）。
**②事件發生順序**：切到「現場影像(7)」分頁；或離開該頁；或 RTSP 斷線。
**③系統處理順序**：
1. `RtspView.update_state`(rtsp_panel.py:145) 取 `state["cameras"]`（來自 `/dashboard/sites/{id}/cameras`，`config.CameraConfig.rtsp_url` 子碼流 subtype=1）。
2. 相機清單變動才重建面板（避免每輪重連）；`showEvent` 啟動 `RtspWorker`(52)，`hideEvent` 停止。
3. `RtspWorker` 以 `cv2.VideoCapture`（強制 RTSP over TCP）讀幀 → `frame_ready` → `RtspPanel` 顯示；斷線退避重連。cv2/PyQt 外掛衝突依 CLAUDE.md 延遲安全載入。
**④資料表/程式碼**：`/dashboard/sites/{id}/cameras`(app.py:128, `models.CameraStream`)、`config.CameraConfig.rtsp_url`、`rtsp_panel.RtspView:145/RtspWorker:52/RtspPanel:103`、`api_client.ApiPoller._snapshot`(cameras)。
**假設事件**：切到「現場影像」→ A03 入口/出口兩路 RTSP 子碼流顯示；切走即停止解碼釋放資源。

---

## E26 — 異常事件牆彙整與優先級

**①目的/功能**：集中需處置事件，依「黑名單/證照過期 > API 斷線 > 陌生 > 資料延遲」排序（規格 §5、模板 p.10）。
**②事件發生順序**：E04/E08/E15/E17 等寫入 `alert`。
**③系統處理順序**：前端取 `/dashboard/sites/{id}/alerts` → `db.alerts`(388)（`resolved=0`，附 `alert_suggestion`）→ `views.AlertView:353` 以 `widgets.AlertCard` 卡片牆呈現（信心度/判定依據/FP-FN 代價/AI 建議/人工拍板鈕）+ 頂部紅色延遲橫幅 + AI 副駕駛摘要。
**④資料表/程式碼**：讀 `alert`+`alert_suggestion`；`db.alerts:388`、`app.py:site_alerts:114`、`views.AlertView:353`、`widgets.AlertCard`。
**假設事件**：同時存在黑名單、證照過期、名單過期、API 延遲 → 卡片牆 4 張，紅(黑名單/過期)在前、黃(陌生/延遲)在後。

---

## E27 — AI 副駕駛摘要

**①目的/功能**：過去 1 小時風險摘要與建議（模板 AI 副駕駛區塊）。
**②事件發生順序**：simulate/`_refresh_loop` 週期呼叫 `_refresh_copilot`。
**③系統處理順序**：`ingest._refresh_copilot`(322) 由 `db.sites_summary` 數字組摘要 → `db.set_copilot`(206)（保留最新 5 筆）；前端取 `/dashboard/sites/{id}/copilot` → `widgets.AICopilotSummary` 顯示於總覽/異常牆頂部。
**④資料表/程式碼**：寫/讀 `copilot_summary`；`ingest._refresh_copilot:322`、`db.set_copilot:206 / copilot:414`、`app.py:copilot:121`、`widgets.AICopilotSummary`。
**假設事件**：摘要「過去 1 小時 4 件異常集中 A03，建議優先處理黑名單與證照過期」。

---

## E28 —（已知缺口）人工拍板「確認告警/標記誤判」未持久化

**①目的/功能**：規格 §5 人機協作；UI 已有「採納並處理/誤判」「確認告警/標記為誤判」按鈕。
**②事件發生順序**：值班人員點異常卡/跳卡上的按鈕。
**③系統處理順序（現況）**：`widgets.AlertCard`/`FlashCard` 按鈕**目前無 click 行為、無 API、無寫庫**；`alert.resolved` 僅由系統（如 E16 名單恢復）設定。
**④資料表/程式碼/缺口**：`alert.resolved`/（缺）`alert_action` 表；尚無 `POST /alerts/{id}/resolve` 端點與前端 QThread 串接。**為已知技術債（先前估算 G2）**，本期未實作；建議後續 `/sc:implement` 補：resolve 端點 + 按鈕串接 + 稽核表。
**假設事件**：點「採納並處理」目前不會留下紀錄，重啟後該告警仍在（除非系統自動 resolve）。

---

# 二、規格 → 實作對應矩陣（速查）

| 規格 | 場景 | 主要程式碼 | 資料表 |
|---|---|---|---|
| §2 刷新/快訊/顏色 | E02/E09/E18 | api_client, main._push_flash | event |
| §3 畫面模式 | E21 | main.SUB_TABS/set_sub, views | 聚合 |
| §4.1.1 RTSP | E25 | rtsp_panel, config.rtsp_url | — |
| §4.2/4.3/4.4 各看板 | E03/E05/E07/E12 | normalize_*, views | event |
| §5 跳卡/優先級/人機 | E04/E09/E26/**E28** | FlashCard, AlertCard, _on_event | alert(+suggestion) |
| §6 趨勢 | E10/E11 | db.hourly_trend, HourlyChart | event(聚合) |
| §7/§9 Standalone 操作 | E20–E24 | main(eventFilter/ROTATION) | — |
| §8 API 欄位 | 全 | app.py 端點, models | 全 |
| §10 名單唯讀/斷線/截圖 | E14/E17/E19 | ingest, db.plate_list_*, _mark_offline | plate_list*, system_status |
| §11 看板端自算/推送備援 | E12/E18 | db 聚合, ApiPoller/EventStream | event |
| 需求 FR 名單持久化 | E01/E06/E13–E16 | db.plate_list_*(470–579), ingest._refresh_lists/_eval_list_state | plate_list, plate_list_meta |

# 三、已知缺口 / 限制（誠實標註）

- **E28 人工拍板未持久化**（G2 技術債）：UI 鈕無作用、無 resolve 端點/稽核表。
- **R-2**：相機名單若「真的被清空」，因 D4「found=0 不清空」本地不會自動反映（已接受限制）。
- **camera vs simulate**：無 `config/cameras.json` 時走 `mock_data.Simulator`（E03–E08 由模擬器產生，流程一致）；真實相機 .10 已驗證 `eventManager.attach` 推送、`recordFinder` 名單、`getSystemInfo`，但實際 `TrafficJunction/FaceRecognition` 的 `data={JSON}` 結構待現場有人車經過時以 `data/event_sample_<host>.json` 最終校正。
- **截圖**：以檔案存 `data/snapshots/`，`event` 僅存 URL；缺圖以向量佔位（E19）。
- 過期門檻 R-1 預設 `max(120, 2×poll_interval)` 秒，可由 `cameras.json` 覆寫。

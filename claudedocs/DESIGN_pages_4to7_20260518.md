# 設計規格：模板 P4–P7 對位實作（單一工地 / 即時跳卡 / 人員 / 車輛）

**日期**：2026-05-18 ｜ **產出**：`/sc:design`（僅設計：版面/介面/流程；**不含實作碼** → `/sc:implement`）
**UI 依據（唯一）**：
- `refData/規格書/工地看板_UI功能設計補充規格書_趨勢與即時快訊.docx`（§4.2/§4.3/§4.4/§5/§6）
- `refData/規格書/工地看板_UI趨勢與即時快訊模板.pptx`（第 4/5/6/7 頁）

## 0. 現況判定（基於程式碼證據，非臆測）

| 模板頁 | 對應實作 | 狀態 |
|---|---|---|
| P4 單一工地看板 | `views.SiteBoardView` | 視圖存在（6 KPI/24H 趨勢/最新事件/「最新現場影像」區）|
| P5 即時快訊跳卡 | `widgets.FlashCard` + `main._push_flash` | 存在（5s/8s、≤3、優先級、確認/誤判）|
| P6 人員進出看板 | `views.PersonnelView` + `PersonnelDetailRow` | 視圖存在（4 KPI/人員趨勢/辨識清單）|
| P7 車輛進出看板 | `views.VehicleView` + `VehicleDetailRow` | 視圖存在（4 KPI/最新車輛截圖區/事件清單/車輛趨勢）|

**核心未實作項（缺口根因）**：`widgets.FaceSnapshot:131`、`VehicleSnapshot:164`、`PlateSnapshot:206` 皆為 QPainter **向量佔位圖**，輸入只是字串（姓名/車牌），**從未載入 `event.snapshot_url` 的真實相機影像**。而 P4「現場影像參考」、P5 跳卡照片、P6「人臉截圖」、P7「最新車輛截圖＋車牌小圖」皆以**真實截圖**為主體（規格 §4.2/§4.3/§4.4 明列 車輛/車牌/人臉截圖）。→ 這四頁等同「畫面在、影像缺」。

> 解讀宣告：使用者所述「P4–7 並沒有實作」=「未對位模板的真實截圖與欄位細節」。本設計以模板/規格為準補齊；若指其他，請於審閱時更正。

## 1. 跨頁共用設計：截圖影像管線（最高優先，P4–P7 共用）

### 1.1 後端（多數已具備，僅補欄位語意）
- 既有 `GET /dashboard/snapshots/{name}` 回 jpeg（`app.py:145`，camera 模式由 `ingest._handle_event` 寫 `data/snapshots/<id>.jpg`）。
- `event.snapshot_url` / `plate_snapshot_url`（車輛全景 / 車牌小圖，規格 §4.3「應與全景圖並列」）已在 `models.Event`。**設計決策**：車牌小圖 `plate_snapshot_url` 目前 ingest 與全景同檔；P7 需「車牌小圖」獨立，列殘留 R-1（見 §6）。
- simulate 模式無實體圖 → `snapshot_url=None`（規格 §10「圖片缺失需顯示替代圖示與錯誤提示」）。

### 1.2 前端（新增元件 — 介面契約，不含實作）
新增 `widgets.SnapshotImage(QWidget)` 取代三個佔位圖在「需要真實影像」處的用法：
```
SnapshotImage(url: str|None, *, kind: 'vehicle'|'plate'|'face',
              w:int, h:int, alert:bool=False, plate_text:str='',
              time_text:str='')
  行為：
   - url 為 None/空 → 立即畫既有向量佔位（FaceSnapshot/VehicleSnapshot/Plate
     Snapshot 邏輯沿用，保留為 fallback；規格 §10）。
   - url 有值 → 透過 SnapshotLoader 非同步抓 {API_BASE}{url}：
       成功 → QPixmap 等比裁切填滿；缺/失敗 → 佔位 + 右下角「影像缺失」小標。
   - alert=True → 紅框；plate_text/time_text 疊字（沿用現有樣式）。
```
新增 `api_client.SnapshotLoader`（QThread 池或單執行緒佇列）：
```
SnapshotLoader.fetch(url, on_pixmap)  # requests.get bytes → QImage → signal
  - LRU 記憶體快取（key=url，上限約 200 張）避免每次刷新重抓。
  - 逾時/4xx → on_pixmap(None)（→ 佔位）。
  - 絕不阻塞 GUI（沿用 repo「requests 在 QThread」慣例；不引入 cv2）。
```
共用元件＝一次到位 P4/P5/P6/P7 的「真實影像」需求。

## 2. P4 — 單一工地看板（§4.2 / 模板 p.4）

### 2.1 目標版面
```
┌ 狀態列：工地：A03 機電棟工區 ·  最後更新 14:32 · API 正常 · 刷新倒數 ┐
├───────────────────────────────────────────────────────────────────┤
│ [人員進場186][人員出場142][目前在場44][車輛進場51][車輛出場38][車輛在場13] │ ← 6 KPI(大字)
├──────────────────────────────┬────────────────────────────────────┤
│ 今日 0-24H 進出趨勢(人車同屏) │ 最新快訊與截圖(人車混合 5–10 筆)    │
│  bars:人員進/出 line:車輛進/出│  每列: 方向 時間 名稱/工號 承攬商·明細│
│  紅線「目前 14 時」           │        狀態徽章 + 縮圖              │
├──────────────────────────────┴────────────────────────────────────┤
│ 現場影像參考：最近 N 筆 真實截圖（車輛全景 / 車牌小圖 / 人臉）        │
└───────────────────────────────────────────────────────────────────┘
```
### 2.2 與現況差異 → 需改
| 模板要求 | 現況 (`views.SiteBoardView`) | 設計 |
|---|---|---|
| 狀態列：工地名/最後更新/API/倒數 | 在 MainWindow 頂列，視圖內無工地標題 | SiteBoardView 頂端加 `SectionTitle(工地名, 最後更新+API)` |
| 6 KPI 醒目大字 | 6 張 `KpiCard(large=False)` | 改 `large=True`，字級符合 §2（50 吋 3–5 公尺可讀）|
| 最新快訊「截圖」 | `EventRow` 無縮圖 | `EventRow` 末端加 `SnapshotImage(face/plate, 40x40)` |
| 現場影像參考 | 佔位向量 `VehicleSnapshot/FaceSnapshot` | 換 `SnapshotImage(url=ev.snapshot_url)`，保留佔位 fallback |
| 趨勢「人員/車輛同屏」 | bars 人員進出 + line 車輛進出 + 預測 | 維持（比模板更豐富，符合 §4.2「疊圖或分圖」；預測屬加值）|

## 3. P5 — 即時快訊跳卡（§5 / 模板 p.5）

### 3.1 目標：三種卡型 + 位置策略
```
一般進出(青/橙框,5s)        告警(紅框,8–15s或人工關)        陌生車牌自動註冊(黃框)
┌───────────────┐          ┌───────────────┐               ┌───────────────┐
│●車輛進場 14:32 │          │●人員進場告警   │               │●陌生車牌自動註冊│
│[真實車輛截圖]  │          │[真實人臉截圖🔴]│               │[真實車輛截圖]  │
│ABC-5288        │          │李O華/E-0981    │               │UNKNOWN-019     │
│大榮土木·砂石車 │          │隆泰·電焊證過期 │               │車輛截圖已保存  │
│白名單·閘門已開 │          │需人工確認      │               │待管理平台確認  │
│           [確認/誤判]     │           [確認/誤判]          │（唯讀,無拍板）  │
└───────────────┘          └───────────────┘               └───────────────┘
位置：一般/告警 右下堆疊(≤3,column-reverse)；嚴重(blacklist/expired) 置中放大。
```
### 3.2 與現況差異 → 需改（`widgets.FlashCard`）
| 模板要求 | 現況 | 設計 |
|---|---|---|
| 卡內真實照片 | 佔位向量 | 換 `SnapshotImage(url=ev.snapshot_url)` |
| 第三型「陌生車牌自動註冊」 | stranger 走一般卡 | 新增 `statusType=stranger` 卡文案「自動註冊 · 車輛截圖已保存 · 待管理平台確認」、無拍板鈕（規格 §7 看板不可編輯）|
| 嚴重告警「置中放大」 | 固定右下、同尺寸 | `is_alert and type∈(blacklist,expired)` → 置中、寬度×1.4、淡化背景遮罩 |
| 顯示時間 一般5s/警示8–15s | 5s/8s 固定 | 警示改 12s 並提供「人工關閉」鈕（§5「或需人工關閉」）|
| 優先級排隊 黑/證>API>陌生>一般 | 取最後 3 張 | 佇列依優先級排序後取前 3（`main._push_flash`）|

## 4. P6 — 人員進出看板（§4.4 / 模板 p.6）

### 4.1 目標版面
```
[進場人次186][離場人次142][目前在場44][證照異常5 (過期3·缺漏2)]
┌ 每小時人員進出趨勢: bars 進場/離場 + 紅線「目前小時」 ────────────┐
└──────────────────────────────────────────────────────────────────┘
最新人員辨識(置頂規則：證照過期紅色置頂)
[人臉真實截圖] 進 14:31:【姓名 王O明 / 工號 E-1029】正興機電 · 高空作業證有效
                       · 門禁點 A03 東門 · 辨識時間 14:31:42 · 通行結果:通行
```
### 4.2 與現況差異 → 需改（`views.PersonnelView` / `widgets.PersonnelDetailRow`）
| 模板/規格欄位 | 現況 PersonnelDetailRow | 設計 |
|---|---|---|
| 人臉截圖（真實） | `FaceSnapshot` 佔位 | `SnapshotImage(face,url)` |
| 姓名 + 工號 | 有 | 維持 |
| 承攬商 | 有 | 維持 |
| 證照狀態（有效/即將過期/已過期/缺漏，過期紅色） | 以 StatusBadge 表示 | 明確 4 態文字 + 過期紅 |
| 門禁點（A03 東門） | 缺 | 新增（event 需帶 gate/門位；來源見 R-2）|
| 辨識時間（精確到秒） | 只顯示時:分 | 改顯示 HH:MM:SS（event_time 已到秒）|
| 通行結果（通行/拒絕/人工確認/API未回應） | 用 access_result 部分呈現 | 獨立欄位明示 |
| 證照過期「置頂」 | 依時間排序 | 排序：alert(過期) 置頂，其餘依時間 |
| KPI 證照異常 過期X·缺漏Y | hardcode「過期3·缺漏2」 | 由 events 統計（過期=status_type alert；缺漏需來源欄位，R-2）|

## 5. P7 — 車輛進出看板（§4.3 / 模板 p.7）

### 5.1 目標版面
```
[進場車次51][離場車次38][目前在場13][陌生車牌4]
┌ 最新車輛截圖(大) ─────────────┐┌ 每小時車輛進出趨勢 ───────────┐
│ [全景真實截圖 240x150] [車牌  ││ bars 進場/離場 + 紅線目前小時  │
│  小圖] 白名單  大榮土木        │└───────────────────────────────┘
│  砂石車·進場·14:32:18 ✓閘門已開│┌ 最新車輛事件 (清單) ──────────┐
└───────────────────────────────┘│ 進 14:32 [車牌小圖] ABC-5288 …│
```
### 5.2 與現況差異 → 需改（`views.VehicleView` / `widgets.VehicleDetailRow`）
| 模板/規格欄位 | 現況 | 設計 |
|---|---|---|
| 最新車輛截圖（全景，真實） | `VehicleSnapshot` 佔位 | `SnapshotImage(vehicle,url=snapshot_url)` |
| 車牌小圖 與全景並列（§4.3） | `PlateSnapshot` 為黃底字 | 有 `plate_snapshot_url` 時 `SnapshotImage(plate,url)`，否則沿用黃底字佔位 |
| 車牌/承攬商/車型/名單狀態/方向/閘門結果 | 大致具備 | 對齊欄序與文字（閘門結果四態）|
| 事件清單每列車牌小圖 | `PlateSnapshot` 字圖 | 同上，有 url 用真實 |
| 陌生車牌 KPI | `or 4` 寫死 fallback | 由 events 統計 stranger（移除魔術數）|

## 6. 後端對接與資料

- 影像來源：camera 模式 `ingest._handle_event` 已抓 `snapshot.cgi` 存檔並設 `event.snapshot_url`；前端 `SnapshotImage` 直接打 `{CARDASH_API}{snapshot_url}`。
- simulate 模式 `snapshot_url=None` → 一律佔位（設計已含 fallback，畫面不空白，符合 §10）。
- `ApiPoller._snapshot` 已含 events（含 snapshot_url）；**無需新增端點**。

## 7. 驗證 / 邊界 / 風險

| 項目 | 設計如何滿足 |
|---|---|
| 規格 §10 唯讀/缺圖替代 | 無寫回；缺圖→向量佔位+「影像缺失」標 |
| 規格 §2 字級(50 吋) | KPI `large=True`；跳卡置中放大 |
| 效能(NFR) | `SnapshotLoader` QThread + LRU 快取，GUI 不阻塞；視圖每刷新重建但圖走快取不重抓 |
| CLAUDE.md cv2/PyQt 衝突 | 影像走 `requests`+`QImage`，**不引入 cv2**（與 RTSP 面板隔離）|
| 自動輪播/重繪 | `SnapshotImage` 接受重建；快取避免閃爍 |

## 8. 殘留（設計階段標記，`/sc:implement` 前定）
- **R-1**：車牌小圖 `plate_snapshot_url` 目前與全景同檔；是否要相機端車牌裁切（§4.3「若車牌平台提供車牌小圖」）— 無則 P7 車牌續用黃底字佔位。
- **R-2**：P6「門禁點(A03 東門)」「證照缺漏」「通行結果」需 event 新欄位；現 `normalize_face` 未帶。來源：FaceRecognition `data` 是否含門位/證照細項，待現場真實事件（`data/event_sample_<host>.json`）確認；無則以 detail 字串呈現、缺漏暫不計。
- **R-3**：跳卡「置中放大」與主畫面遮罩層級，需與 RTSP 面板/控制列 z-order 協調（實作時驗證）。

## 9. 下一步（`/sc:implement` 建議順序）
1. `widgets.SnapshotImage` + `api_client.SnapshotLoader`（共用影像管線，含 LRU 快取/fallback）
2. P7 VehicleView/VehicleDetailRow 對位（截圖最關鍵、欄位最明確）
3. P6 PersonnelView/PersonnelDetailRow（含過期置頂、時間到秒、欄位）
4. P4 SiteBoardView（KPI large、列縮圖、現場影像真實圖）
5. P5 FlashCard（真實照片、陌生自動註冊卡、嚴重置中放大、人工關閉）
6. 驗證：simulate（佔位 fallback 不空白）＋ 對 .10 camera（真實 jpeg）兩路；offscreen 7 視圖回歸

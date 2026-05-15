# 白名單管理 Demo — 開發進度紀錄

**日期**：2026-05-15
**主要產出**：[demo/demo1.py](../demo/demo1.py) — PyQt5 單檔可執行的相機白名單管理 demo
**目標設備**：XC-204BLPR / ITC413-PW4D-Z1（中性 / Dahua-like ANPR camera @ 192.168.0.10）
**規範來源**：[manuals/中性简体_HTTP_API_协议规范V3.87.pdf](../manuals/中性简体_HTTP_API_协议规范V3.87.pdf)

---

## 1. 需求對焦

依 `/sc:brainstorm` 完成需求探索後鎖定：

| 需求項 | 決議 |
|---|---|
| GUI 框架 | PyQt5 |
| 功能範圍 | 取讀白名單 + 新增 / 修改 / 刪除車牌 + 建立 / 刪除群組 |
| 認證資訊 | GUI 上方欄位即時輸入（host / user / pass / HTTPS toggle） |
| 呈現形式 | 單一可執行檔 demo（`demo/demo1.py`） |

對應的 API 規範章節：

| 動作 | 新版 endpoint（§10.7 VehicleRegisterDB） | 舊版 endpoint（§10.3 traffic record） |
|---|---|---|
| 取讀白名單 | `findGroup` + `startFind`→`doFind`→`stopFind` | `recordFinder.cgi?action=find&name=TrafficRedList` |
| 新增車牌 | `multiAppend` | `recordUpdater.cgi?action=insert&name=TrafficRedList` |
| 修改車牌 | `modifyVehicle` | `recordUpdater.cgi?action=update&name=TrafficRedList&recno=...` |
| 移除車牌 | `deleteVehicle` | `recordUpdater.cgi?action=removeEx&name=TrafficRedList` |
| 建立群組 | `createGroup`（GroupType=`AllowListDB`） | ❌ 不支援（只有兩張固定表） |
| 刪除群組 | `deleteGroup` | ❌ 不支援 |

---

## 2. Troubleshooting 時間軸

### 2.1 ConnectionRefused / HTTP 400 — 第一次連線失敗

**症狀**：
- `API Error: Unable to connect to API (ConnectionRefused)` — TCP 層失敗
- `error 400` — 設備拒絕請求

**根因分析（互斥的兩個失敗模式）**：
- ConnectionRefused：host / port / scheme 不對，或設備離線
- HTTP 400：TCP 通了但設備拒收 — 可能是 endpoint 不存在或 body schema 不合

**處置**：套用診斷強化補丁（不改 API 流程）：
- 加 `self._session.verify = False` + `urllib3.disable_warnings(...)` 容忍自簽憑證
- `_request()` 與 `_trace()`：每次 request / response 把 URL + status + body[:300] 印到 GUI 下方 Log 區
- 4xx 錯誤訊息改為帶完整 URL + body[:1000]
- 新增 `smoke_test()` 呼叫 `magicBox.cgi?action=getSystemInfo`，用於拆分「連線 / 帳密」與「特定 API 是否支援」兩個問題

### 2.2 smoke_test 通過但 findGroup 沒被呼叫 — Worker thread bug

**症狀**：smoke_test 200 OK 後 log 區再無動靜，`findGroup` 完全沒發出。

**根因**：`_run_async` 的 success 回呼順序錯誤：

```python
self._worker.success.connect(lambda r: (on_success(r), _done()))   # ← bug
```

`on_success` 先執行，於是 `_smoke_ok` 內呼叫 `self.on_find_groups()` → `_run_async(c.find_group, ...)` 時，`self._thread` 還沒被 `_done()` 清成 `None`，被開頭的 `if self._thread is not None` 擋掉。任何「成功 → 自動觸發下一個 async 呼叫」的鏈式流程都會死在這。

**處置**：重排序為 **cleanup → callback**：

```python
def _cleanup() -> None:
    """必須在執行使用者 callback 之前跑完。"""
    self._busy(False)
    t, w = self._thread, self._worker
    self._thread = None
    self._worker = None
    if t is not None: t.quit(); t.wait(); t.deleteLater()
    if w is not None: w.deleteLater()

def _finish_ok(r):   _cleanup(); on_success(r)
def _finish_err(e):  _cleanup(); self._on_error(e)
```

附帶加上 `deleteLater()`，避免長期使用累積 QThread/QObject。

### 2.3 findGroup 回 HTTP 400 "Bad Request!" — 韌體版本差異

**證據**（來自實機 log）：

```
→ POST http://192.168.0.10/cgi-bin/api/VehicleRegisterDB/findGroup  body={"groupID": ""}
← 400 ...  body=Error
Bad Request!
```

`magicBox.getSystemInfo` 200 OK（設備 + 帳密 + Digest 均正常），但 `/cgi-bin/api/VehicleRegisterDB/findGroup` 400。

**根因**：V3.87 是「通用規範」的超集；XC-204BLPR / ITC413-PW4D-Z1（XS7320 SoC）韌體實作的是 **§10.3 舊式 API**（GET + query-string + key=value 回應），不是 §10.7 的 POST + JSON。

**處置**：實作自動 fallback 架構。

---

## 3. 最終架構

### 3.1 類別階層

```
_BaseHttpClient                          # 共用 Digest session、tracing、HTTP plumbing
 ├── VehicleRegisterDBClient             # §10.7 新版 (POST + JSON)
 └── LegacyTrafficListClient             # §10.3 舊版 (GET + key=value)
```

兩個子類有**完全相同的方法簽名**：`find_group`, `create_group`, `delete_group`,
`list_vehicles`, `append_vehicles`, `modify_vehicle`, `delete_vehicle`。

`mode_label` class attr 讓 UI 顯示目前 API 模式（出現在 status bar）。

### 3.2 共用 HTTP 層 — `_BaseHttpClient`

關鍵設計：
- `requests.Session()` + `HTTPDigestAuth` — RFC 7616 Digest 自動處理
- `session.verify = False` — 容忍自簽憑證
- 可選 `session=` 參數 — fallback 時兩個 client 共用同一條 Session，避免 Digest 重新挑戰
- `_request()` 統一錯誤封裝：SSLError / ConnectionError / Timeout / 4xx / non-JSON 各自帶 URL 上下文
- `_trace()` callback hook — 把每筆 request / response 印到 GUI Log 區
- `_post(path, payload)` — POST + JSON，回 dict
- `_get_text(path, params)` — GET，回 raw text（給 §10.3 用）
- `smoke_test()` — `magicBox.cgi?action=getSystemInfo`，幾乎所有韌體都有

### 3.3 §10.7 新版 — `VehicleRegisterDBClient`

對應 [中性简体_HTTP_API_协议规范V3.87.pdf](../manuals/中性简体_HTTP_API_协议规范V3.87.pdf) §10.7.1–10.7.10：

| Method | Endpoint |
|---|---|
| `create_group` | `POST /cgi-bin/api/VehicleRegisterDB/createGroup` |
| `delete_group` | `POST /cgi-bin/api/VehicleRegisterDB/deleteGroup` |
| `find_group` | `POST /cgi-bin/api/VehicleRegisterDB/findGroup` |
| `append_vehicles` | `POST /cgi-bin/api/VehicleRegisterDB/multiAppend` |
| `modify_vehicle` | `POST /cgi-bin/api/VehicleRegisterDB/modifyVehicle` |
| `delete_vehicle` | `POST /cgi-bin/api/VehicleRegisterDB/deleteVehicle` |
| `list_vehicles` | `startFind` → 迴圈 `doFind(token, beginNumber, count)` → `stopFind` |

### 3.4 §10.3 舊版 — `LegacyTrafficListClient`

對應 §10.3.1–10.3.5：

| Method | Endpoint |
|---|---|
| `find_group` | **合成**回 `TrafficRedList` / `TrafficBlackList` 兩筆 |
| `create_group` / `delete_group` | 不支援 → `raise ApiError("舊式 §10.3 韌體不支援...")` |
| `list_vehicles` | `GET /cgi-bin/recordFinder.cgi?action=find&name=...&count=...` → `_parse_kv()` |
| `append_vehicles` | `GET /cgi-bin/recordUpdater.cgi?action=insert&name=...&PlateNumber=...&AuthorityList.OpenGate=true` |
| `modify_vehicle` | `GET /cgi-bin/recordUpdater.cgi?action=update&name=...&recno=...` |
| `delete_vehicle` | `GET /cgi-bin/recordUpdater.cgi?action=removeEx&name=...&PlateNumber=...` |

合成 SYNTHETIC_GROUPS：

```python
SYNTHETIC_GROUPS = [
    {"groupID": "TrafficRedList",   "groupName": "白名單 (TrafficRedList)",
     "groupType": "AllowListDB", "groupSize": -1},
    {"groupID": "TrafficBlackList", "groupName": "黑名單 (TrafficBlackList)",
     "groupType": "BlockListDB", "groupSize": -1},
]
```

讓 UI 不必區分模式 — 下拉選單照樣可以選「群組」並執行 CRUD。

### 3.5 `_parse_kv()` — Dahua key=value 回應解析器

輸入：

```
totalCount=2
found=2
records[0].RecNo=12345
records[0].PlateNumber=AC00001
records[1].RecNo=13579
records[1].PlateNumber=BC22222
```

輸出：

```python
{"totalCount": "2", "found": "2",
 "records": [
   {"RecNo": "12345", "PlateNumber": "AC00001"},
   {"RecNo": "13579", "PlateNumber": "BC22222"},
 ]}
```

驗證：規範範例 + 實機 `magicBox.getSystemInfo` 回應雙重通過。

### 3.6 自動能力探測 — `_probe_api_mode()`

流程：

```
按「連線」
    ↓
on_connect() 建立 VehicleRegisterDBClient
    ↓
_run_async(smoke_test)
    ↓ 成功
_smoke_ok() → _probe_api_mode()
    ↓
_run_async(self.client.find_group, ok=_render_groups, on_failure=_fail)
    ↓ HTTP 4xx?
_fail() → 沿用 session 換成 LegacyTrafficListClient → on_find_groups()
    ↓
status bar 標示「API: 新版 §10.7」或「API: 舊版 §10.3」
```

只在「設備明確回 HTTP 400 / 404 / 405 / 501」時 fallback；網路 / SSL / 401 等不切換。

`_run_async` 為此新增可選 `on_failure=` 參數，覆寫預設錯誤處理（預設仍是彈 ApiError dialog）。

---

## 4. 預期實機 log（修補後）

```
[OK] Session 已建立：http://192.168.0.10 as admin
→ GET http://192.168.0.10/cgi-bin/magicBox.cgi  params={'action': 'getSystemInfo'}
← 200 ...  body=appAutoStart=true\ndeviceType=XC-204BLPR\n...
[OK] smoke_test 通過：appAutoStart=true | deviceType=XC-204BLPR | hardwareVersion=1.00
→ POST http://192.168.0.10/cgi-bin/api/VehicleRegisterDB/findGroup  body={"groupID": ""}
← 400 ...  body=Error\nBad Request!
[detect] 新版 API 不支援（HTTP 400 @ ...） → 切換到舊版 §10.3 TrafficRedList
→ GET http://192.168.0.10/cgi-bin/recordFinder.cgi  params={'action': 'find', 'name': 'TrafficRedList', 'count': 50}
← 200 ...  body=totalCount=...\nfound=...\nrecords[0].RecNo=...
[OK] findGroup 回傳 2 個群組。
```

群組表會出現「白名單 (TrafficRedList)」「黑名單 (TrafficBlackList)」，下拉選白名單，按「取讀白名單」就會用 `recordFinder.cgi?action=find` 拉清單。

---

## 5. 已知邊界與後續待辦

### 5.1 舊式 API 模式下的限制
- **新增群組** / **刪除群組** 按鈕會跳 `ApiError("舊式 §10.3 韌體不支援自建群組")` — 設計如此，非 bug
- 舊式新增白名單預設帶 `AuthorityList.OpenGate=true`（白名單預設授權開閘）；若要關掉，需擴 UI 提供 toggle
- `list_vehicles` 目前 `count=page_size`（單頁），尚未實作 `QueryResultBegin` / `QueryCount` 分頁；筆數多時需擴

### 5.2 未驗證項目（等使用者實測 log）
- `recordFinder.cgi?action=find&name=TrafficRedList` 在這台 XC-204BLPR 的實際回應格式是否完全符合規範範例 — `_parse_kv` 可能需要因應實機差異微調
- `recordUpdater.cgi?action=insert` 對 `AuthorityList.OpenGate` 子欄位的 URL 編碼方式（目前依靠 `requests.params` 自動處理 `.` 不編碼）
- 中文車牌（如「浙 A12345」、含空白）在 query string 的編碼是否被設備正確接收

### 5.3 重構機會
- `LegacyTrafficListClient` 的 `find_group` / SYNTHETIC_GROUPS 把 UI 模型外洩到 client 層；若未來要做 unit test，這部分應該抽到 UI adapter
- `_probe_api_mode` 目前只在 connect 時跑一次；若使用者中途改 host 或設備重開，需要手動重連

---

## 6. 同期產出

- [CLAUDE.md](../CLAUDE.md) — 為未來 Claude Code instance 寫的 repo 導讀，重點：HTTP API 慣例（Digest + self-signed cert + magicBox smoke-test + §10.7 ≠ §10.3 警告）、OpenCV+PyQt5 plugin 衝突的處置咒語、QThread cleanup-before-callback 規則

---

## 7. 檔案異動

| 檔案 | 動作 |
|---|---|
| `demo/demo1.py` | 新增 / 多輪修補（最終版本含雙模式 client + 自動 fallback） |
| `CLAUDE.md` | 新增 |
| `claudedocs/2026-05-15_whitelist_demo_progress.md` | 本檔 |

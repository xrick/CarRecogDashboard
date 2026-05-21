# 已整合的中性 / Dahua HTTP API（上線系統）

本文件記錄 CarRecogDashboard **正式後端 [src/backend/camera_client.py](../src/backend/camera_client.py) 實際使用** 的中性 / Dahua HTTP API。所有條目對應《中性简体 HTTP_API 协议规范 V3.87》(`manuals/中性简体_HTTP_API_协议规范V3.87.pdf`) 章節編號，並已於 XC-204BLPR @ `192.168.0.10` 實機驗證。

文件第二部分整理 **白名單 / 黑名單新增與修改** 所需呼叫的大華 API（目前後端尚未實作，僅 [tests/demo2_writelist.py](../tests/demo2_writelist.py) 探索性 demo 用過，留作後續整合參考）。

---

## 0. 共通協定

| 項目 | 設定 | 出處 |
|---|---|---|
| 認證 | HTTP Digest (RFC 7616) | 規格 §3.4 |
| 連線 | `requests.Session()` + `HTTPDigestAuth` | [camera_client.py:143-144](../src/backend/camera_client.py#L143-L144) |
| HTTPS 自簽憑證 | `session.verify = False` + 抑制 `InsecureRequestWarning` | [camera_client.py:40](../src/backend/camera_client.py#L40), [L145](../src/backend/camera_client.py#L145) |
| 回應解析 | `parse_kv()` 解析 `key=value` 與 `records[0].PlateNumber=...` 巢狀格式 | [camera_client.py:45-80](../src/backend/camera_client.py#L45-L80) |
| Base URL | `{scheme}://{host}` 由 [`CameraConfig.base_url`](../src/backend/config.py#L43-L45) 產生 | — |

---

# Part A — 目前上線系統使用的 API

只列出 [src/backend/camera_client.py](../src/backend/camera_client.py) 中**已實作且實機跑過**的 4 個端點。

## A1. 設備探測 — `magicBox.cgi?action=getSystemInfo`

| 屬性 | 值 |
|---|---|
| 規格章節 | §4.6.39 |
| Method / URL | `GET /cgi-bin/magicBox.cgi?action=getSystemInfo` |
| 用途 | Smoke test，確認設備可達且 Digest 認證成功 |
| 實作 | [`CameraClient.get_system_info()`](../src/backend/camera_client.py#L148-L155) |
| 回傳 | `parse_kv()` 解析後的 `dict[str, str]`（型號、序號、韌體版本等） |
| 錯誤處理 | `401 → CameraError("認證失敗 (401)：帳號/密碼錯誤")`；其餘 4xx/5xx → `raise_for_status()` |
| 實機驗證 | ✅ XC-204BLPR @ `.10` 回 200 |

```http
GET /cgi-bin/magicBox.cgi?action=getSystemInfo
Authorization: Digest ...
```

```text
deviceType=IPC-HFW1235
serialNumber=4J0...
softwareVersion=2.800.0000000.30.R
```

---

## A2. 即時事件流 — `eventManager.cgi?action=attach`（主要管道）

| 屬性 | 值 |
|---|---|
| 規格章節 | §4.9.17（attach 介面）+ §10.1.1 (TrafficJunction) + §9.2.16 (FaceRecognition) |
| Method / URL | `GET /cgi-bin/eventManager.cgi?action=attach&codes=[TrafficJunction,FaceRecognition]&heartbeat=5` |
| Response Type | `multipart/x-mixed-replace; boundary=...`（**長連線、非輪詢**） |
| 用途 | 訂閱車牌辨識 + 人臉辨識事件，由相機主動推播 |
| 實作 | [`CameraClient.stream_events()`](../src/backend/camera_client.py#L261-L278) |
| Part 解析 | [`_iter_parts()`](../src/backend/camera_client.py#L238-L258) → [`parse_eventmanager_event()`](../src/backend/camera_client.py#L89-L116) |
| Heartbeat | body == `b"Heartbeat"` 自動吞掉 |
| 上游重連 | [ingest.py:151](../src/backend/ingest.py#L151) daemon thread + 指數退避（最高 15s） |
| 實機驗證 | ✅ XC-204BLPR @ `.10` HTTP 200 + 持續收到 Heartbeat |

### 訂閱碼選擇邏輯（[`CameraConfig.event_codes`](../src/backend/config.py#L59-L64)）

| `cfg.kind` | 訂閱 codes |
|---|---|
| `anpr` (預設) | `TrafficJunction` |
| `face` | `FaceRecognition` |
| `both` | `TrafficJunction,FaceRecognition` |

### Part body 格式（規格 §4.9.17 / §10.2.1）

```text
Code=TrafficJunction;action=Start;index=0;data={ ...JSON... }
```

解析後 dict：

```python
{
  "code":   "TrafficJunction",
  "action": "Start",
  "index":  "0",
  "data":   { ... }   # JSON dict；若非 JSON 退化為 parse_kv 結果；最差為 {"_raw": "..."}
}
```

### 容錯設計

- `data=` 可跨多行 → regex 用 `re.S` (DOTALL)
- 非 JSON 時 fallback 走 `parse_kv()`，再失敗保留前 2000 bytes 於 `_raw`
- 重連 / backoff 不在此層處理，由 ingest 層負責

---

## A3. 即時快照 — `snapshot.cgi`

| 屬性 | 值 |
|---|---|
| 規格章節 | §4.4.2 |
| Method / URL | `GET /cgi-bin/snapshot.cgi?channel={N}&type=0` |
| 用途 | 取一張 JPEG 靜態影像（`eventManager.attach` 的 part 不含內嵌影像，每筆事件另行拉一張） |
| 實作 | [`CameraClient.snapshot()`](../src/backend/camera_client.py#L309-L315) |
| 回傳 | `bytes`（JPEG content） |
| 呼叫策略 | best-effort，每筆事件 normalize 完成後拉取，失敗不阻斷 ingest 流程 |
| 實機驗證 | ✅ |

---

## A4. 車牌名單查詢 — `recordFinder.cgi`（**唯讀**）

| 屬性 | 值 |
|---|---|
| 規格章節 | §10.3.4 |
| Method / URL | `GET /cgi-bin/recordFinder.cgi?action=find&name={TrafficRedList\|TrafficBlackList}&count=1024` |
| 用途 | 抓取相機本機白名單（紅名單）與黑名單 |
| 實作 | [`CameraClient.find_plate_list(name)`](../src/backend/camera_client.py#L158-L189) |
| 回傳型別 | [`PlateListResult`](../src/backend/camera_client.py#L129-L138) `(ok, plates, http_status, reason)` |
| 實機驗證 | ✅ XC-204BLPR @ `.10` 回 200，`found=N` + `records[]` |

### `PlateListResult` 三種結果（對應 D4 決策矩陣）

| 情境 | `ok` | `plates` | 上游 ingest 動作 |
|---|---|---|---|
| HTTP 2xx + `found > 0` + records 解析成功 | `True` | `set[plate]` | `plate_list_replace` — 差異更新本地鏡像 |
| HTTP 2xx + `found = 0`（無記錄）| `True` | `set()` (空) | `plate_list_touch` — **保留本地鏡像不清空**，僅更新 `last_attempt_ts` |
| HTTP 4xx/5xx 或網路例外 | `False` | `set()` | `plate_list_touch` — 同上，避免相機暫斷導致誤判陌生車 |

> **D4 設計重點**：`found=0` 是合法回應（XC-204BLPR 真實行為已驗證），**不能**視為失敗清空本地鏡像。詳見 [`claudedocs/DESIGN_plate_list_persistence.md`](DESIGN_plate_list_persistence.md) §2。

### 範例

```http
GET /cgi-bin/recordFinder.cgi?action=find&name=TrafficRedList&count=1024
```

```text
found=2
records[0].PlateNumber=ABC-1234
records[0].MasterOfCar=承攬商A
records[1].PlateNumber=XYZ-5678
records[1].MasterOfCar=承攬商B
```

---

## A5. 整合摘要表

| API / 章節 | 用途 | 實作函式 | 實機 (XC-204BLPR) |
|---|---|---|---|
| §4.6.39 `magicBox.getSystemInfo` | Smoke test | `get_system_info()` | ✅ 200 |
| §4.9.17 `eventManager.attach` | 即時事件流（主要） | `stream_events()` | ✅ 200 + Heartbeat |
| §4.4.2 `snapshot.cgi` | 事件當下取影像 | `snapshot()` | ✅ |
| §10.3.4 `recordFinder.cgi` | 車牌名單查詢（唯讀） | `find_plate_list()` | ✅ 200 |

---

# Part B — 白名單 / 黑名單新增與修改

> ⚠️ **重要**：本節列出的「寫入類」API（新增、修改、刪除名單）**目前正式後端尚未實作**。`camera_client.py` 只有 `find_plate_list()` 做唯讀同步。完整 CRUD 邏輯已在探索性 demo [tests/demo2_writelist.py](../tests/demo2_writelist.py) 跑通，可作為後續整合進 `camera_client.py` 的參考。

大華相機支援**兩套**車牌名單管理 API，需依韌體支援度二擇一：

| 套件 | 規格 | 協定 | 適用機型 |
|---|---|---|---|
| **新版** | §10.7 `VehicleRegisterDB` | POST + JSON + Digest | 新韌體（支援自建群組） |
| **舊版** | §10.3 `recordUpdater.cgi` / `recordFinder.cgi` | GET + query-string + key=value | XC-204BLPR / ITC413-PW4D 等老韌體；只有兩張固定名單 `TrafficRedList`（白）與 `TrafficBlackList`（黑） |

### 選擇策略（demo2_writelist.py auto-detect）

1. 先試 `POST /cgi-bin/api/VehicleRegisterDB/findGroup` body `{"groupID": ""}`
2. 若 200 → 走新版 §10.7
3. 若 4xx（XC-204BLPR @ `.10` 實測 400）→ 切舊版 §10.3
4. 老機型可建立兩張合成群組 `TrafficRedList` / `TrafficBlackList` 對 UI 統一表現

---

## B1. 新版 §10.7 — `VehicleRegisterDB`（POST + JSON）

實作參考：[VehicleRegisterDBClient](../tests/demo2_writelist.py#L177-L252)

### B1.1 建立群組（白名單 / 黑名單容器）

| 屬性 | 值 |
|---|---|
| 規格章節 | §10.7.1 |
| URL | `POST /cgi-bin/api/VehicleRegisterDB/createGroup` |
| Body | `{"group": {"GroupName": "工地A白名單", "GroupDetail": "說明", "GroupType": "AllowListDB"}}` |
| `GroupType` 取值 | `AllowListDB`（白名單）/ `BlockListDB`（黑名單） |
| 回應 | `{"groupID": "...", ...}` — 後續操作都需要這個 `groupID` |

### B1.2 **新增車牌**（單筆 / 批次）

| 屬性 | 值 |
|---|---|
| 規格章節 | §10.7.5 |
| URL | `POST /cgi-bin/api/VehicleRegisterDB/multiAppend` |
| Body | `{"vehicle": [{...}, {...}]}` — 一次塞多筆 |
| 單筆欄位 | `GroupID`、`PlateNumber`、`Name`（車主）、`PhoneNo`、`PlateCountry`（ISO3166） |
| 回應 | 各筆寫入結果 |

```json
POST /cgi-bin/api/VehicleRegisterDB/multiAppend
{
  "vehicle": [
    {"GroupID": "{允許名單群組ID}", "PlateNumber": "ABC-1234",
     "Name": "張三", "PhoneNo": "0912345678", "PlateCountry": "TW"}
  ]
}
```

### B1.3 **修改車牌**

| 屬性 | 值 |
|---|---|
| 規格章節 | §10.7.6 |
| URL | `POST /cgi-bin/api/VehicleRegisterDB/modifyVehicle` |
| Body | `{"vehicle": {"UID": 123, "GroupID": "...", "PlateNumber": "...", ...}}` |
| 必填 | `UID`（記錄唯一識別碼，由 `startFind/doFind` 查得）+ `GroupID` |

### B1.4 刪除車牌

| 屬性 | 值 |
|---|---|
| 規格章節 | §10.7.7 |
| URL | `POST /cgi-bin/api/VehicleRegisterDB/deleteVehicle` |
| Body | `{"vehicle": {"groupID": "...", "UID": 123}}` 或 `{"vehicle": {"groupID": "...", "plateNumber": "ABC-1234"}}` |

### B1.5 列出群組內所有車牌（分頁查詢）

三段式：

1. `POST /cgi-bin/api/VehicleRegisterDB/startFind` body `{"vehicle": {"GroupID": "...", "UID": 0}}` → 取得 `token` + `totalCount`
2. 迴圈 `POST /doFind` body `{"condition": {"token": "...", "beginNumber": 0, "count": 50}}` → `results.candidates[].Vehicle`
3. `POST /stopFind` body `{"token": "..."}` 釋放

實作見 [`list_vehicles()`](../tests/demo2_writelist.py#L218-L252)。

### B1.6 群組查詢 / 刪除

| 規格 | URL | Body |
|---|---|---|
| §10.7.4 findGroup | `POST /cgi-bin/api/VehicleRegisterDB/findGroup` | `{"groupID": ""}` （空字串 = 全部） |
| §10.7.3 deleteGroup | `POST /cgi-bin/api/VehicleRegisterDB/deleteGroup` | `{"groupID": "..."}` |

---

## B2. 舊版 §10.3 — `recordUpdater.cgi`（GET + query-string）

實作參考：[LegacyTrafficListClient](../tests/demo2_writelist.py#L255-L350)

**只有兩張固定名單**，名稱寫死：

| `name` 參數 | 用途 |
|---|---|
| `TrafficRedList` | 白名單（允許通行） |
| `TrafficBlackList` | 黑名單（拒絕 / 告警） |

XC-204BLPR 等老機型只能用這套。**不能自建群組**。

### B2.1 **新增車牌** — §10.3.1

| 屬性 | 值 |
|---|---|
| URL | `GET /cgi-bin/recordUpdater.cgi?action=insert&name={TrafficRedList\|TrafficBlackList}&PlateNumber=...&MasterOfCar=...` |
| 白名單額外參數 | `AuthorityList.OpenGate=true`（授權開閘） |

```http
GET /cgi-bin/recordUpdater.cgi?action=insert&name=TrafficRedList&PlateNumber=ABC-1234&MasterOfCar=張三&AuthorityList.OpenGate=true
```

### B2.2 **修改車牌** — §10.3.2

| 屬性 | 值 |
|---|---|
| URL | `GET /cgi-bin/recordUpdater.cgi?action=update&name={TrafficRedList\|TrafficBlackList}&recno={UID}&PlateNumber=...&MasterOfCar=...` |
| 必填 | `recno`（記錄編號，由 `recordFinder` 查得） |

### B2.3 刪除車牌 — §10.3.5

| 屬性 | 值 |
|---|---|
| URL | `GET /cgi-bin/recordUpdater.cgi?action=removeEx&name=...&recno=...` 或 `&PlateNumber=...` |
| 條件 | `recno` 或 `PlateNumber` 至少擇一 |

### B2.4 查詢（同 Part A4）

`GET /cgi-bin/recordFinder.cgi?action=find&name={TrafficRedList|TrafficBlackList}&count=...`

回應格式：

```text
found=2
records[0].RecNo=1
records[0].PlateNumber=ABC-1234
records[0].MasterOfCar=張三
```

---

## B3. 後端整合建議

目前 [src/backend/camera_client.py](../src/backend/camera_client.py) 只有 `find_plate_list()` 唯讀同步。若要將新增 / 修改也納入後端（讓 dashboard UI 可直接管理車牌名單，取代相機 Web UI），建議的擴充模式：

1. 在 [`CameraClient`](../src/backend/camera_client.py#L140) 新增：
   - `add_plate(name, plate, owner=None)` — 主呼叫 §10.3.1 `recordUpdater.cgi?action=insert`（target 機型 XC-204BLPR 只支援這套）
   - `modify_plate(name, recno, plate, owner=None)` — §10.3.2 `action=update`
   - `delete_plate(name, recno=None, plate=None)` — §10.3.5 `action=removeEx`
2. 容錯：若回應為 `OK` / HTTP 200 視為成功，其餘走 `CameraError`
3. 寫入成功後，立即觸發本地 `plate_list_replace`（or `find_plate_list` 重抓）保持鏡像同步
4. （可選）偵測新韌體時優先走 §10.7 `multiAppend / modifyVehicle / deleteVehicle`，4xx 時 fallback §10.3

詳細實作可直接 port [tests/demo2_writelist.py](../tests/demo2_writelist.py) 的 `LegacyTrafficListClient`（已驗證對應規格）。

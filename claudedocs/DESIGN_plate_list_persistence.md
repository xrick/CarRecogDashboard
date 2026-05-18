# 設計規格：白/黑名單本地持久化（唯讀鏡像）

**日期**：2026-05-18 ｜ **依據**：`claudedocs/REQ_plate_list_persistence.md`（需求已定案）
**產出自**：`/sc:design` — 僅架構/schema/介面/流程；**不含實作程式碼**（→ `/sc:implement`）。
**對接現況**：`db.py`（單連線 + `_lock` RLock + WAL）、`ingest.py`（`IngestManager._lists` 記憶體快取）、`camera_client.find_plate_list()`、`config.AppConfig`。

---

## 0. 殘留項裁決（設計決策）

- **R-1 過期門檻** → `AppConfig.plate_list_stale_seconds`，預設 `max(120, 2 × poll_interval)` 秒，可由 `cameras.json` 覆寫。
- **R-2 相機名單真的被清空如何反映** → 依 D4「`found=0` 不清空」，**設計上不自動傳播**；視為**已接受的限制**。提供一個維運專用、預設關閉的明確重置動作（CLI/env `CARDASH_LIST_RESET=<host>`）做為逃生口；**本期 out of scope，僅在 schema/介面預留**，不違反規格 §10（不寫回相機）。

---

## 1. 資料模型（Schema 設計）

新增兩張表（沿用 `db.py::_SCHEMA` 風格、`CREATE TABLE IF NOT EXISTS`）：

```sql
-- 名單明細：每 (host, 名單別, 車牌) 一列；只存車牌 (FR-8)
CREATE TABLE IF NOT EXISTS plate_list (
    host       TEXT NOT NULL,
    list_type  TEXT NOT NULL CHECK (list_type IN ('red','black')),  -- red=白名單 black=黑名單
    plate      TEXT NOT NULL,
    PRIMARY KEY (host, list_type, plate)
);
CREATE INDEX IF NOT EXISTS ix_plate_list_h ON plate_list(host, list_type);

-- 名單同步狀態：每 (host, 名單別) 一列，供差異偵測 / 過期判定 / 補水
CREATE TABLE IF NOT EXISTS plate_list_meta (
    host            TEXT NOT NULL,
    list_type       TEXT NOT NULL,
    snapshot_hash   TEXT,                       -- sha1(sorted(plates))，免整表比對
    plate_count     INTEGER NOT NULL DEFAULT 0,
    last_success_ts TEXT,                       -- 最近一次成功取得(含 found=0)
    last_change_ts  TEXT,                       -- 最近一次內容真的變動(有寫入明細)
    last_attempt_ts TEXT,                       -- 最近一次嘗試(成功或失敗)
    last_status     TEXT NOT NULL DEFAULT 'unsynced'
                    CHECK (last_status IN ('unsynced','fresh','stale')),
    PRIMARY KEY (host, list_type)
);
```

設計理由：
- 明細用 row（非 blob）→ 分類查詢與未來擴充（顯示/統計）皆方便；PK 自動去重。
- `snapshot_hash` 讓 FR-2/FR-3 的「差異偵測」O(n) 完成，避免每輪整表 diff。
- meta 與明細分離 → 「失敗/`found=0` 只動 meta、不動明細」(D4) 自然成立。
- PII（NFR-4）：只存 `plate`，不存車主/車種；不加密、不設保留期（使用者決策）。

---

## 2. D4 決策矩陣（核心邏輯，設計層）

每次 `_refresh_lists(host)` 對 red、black 各跑一次：

```
recordFinder 結果                          | 明細表          | meta            | 記憶體快取
------------------------------------------ | -------------- | --------------- | ----------
成功 + 有 ≥1 筆 + hash 與舊不同             | 交易內整批取代  | hash/count/各ts | 更新該 host
成功 + 有 ≥1 筆 + hash 與舊相同             | 不動            | 只更新 *_ts     | 不動 (一致)
成功 + found=0  (D4: 永不清空)             | 不動            | 只更新 attempt  | 不動
失敗 (連線/HTTP/逾時)                       | 不動            | 只更新 attempt  | 不動
```

→ 需要把「成功且非空 / 成功但空 / 失敗」三態**明確分流**，因此 §4 變更 `find_plate_list` 的回傳契約（目前回 `set` 無法區分三態）。

---

## 3. 分類狀態機（FR-10 / FR-11 / D5 / D6）

每 (host) 由 red+black 的 meta 推導一個對外狀態：

```
        ┌─────────── 啟動補水 ───────────┐
        ▼                                │
   ┌─────────┐  首次成功取得        ┌────────┐  now-last_success > stale_secs   ┌────────┐
   │UNSYNCED │ ───────────────────▶│ FRESH  │ ───────────────────────────────▶│ STALE  │
   │系統安裝中│                     │ 正常   │ ◀───────────────────────────────│ 名單過期│
   └─────────┘                     └────────┘   下一次成功取得(含 found=0)      └────────┘
   分類: status_type=pending        分類: 正常比對 red/black/stranger
   不發陌生告警                      STALE 仍用既有名單分類, 另發告警牆卡
```

- **UNSYNCED**（meta 無 `last_success_ts`）→ `normalize_traffic` 對未命中車牌回 `status_type="pending"`、文案「名單未同步（系統安裝中）」，**不**判 `stranger`、**不**觸發陌生告警（FR-10/D5）。
- **STALE**（超過門檻或連續失敗）→ 仍以既有名單分類（不降級），另於異常事件牆顯示「名單過期/未同步」卡（FR-11/D6）。
- **FRESH** → 現行行為（red→whitelist / black→blacklist / 其他→stranger）。

### 連帶設計影響（需於 `/sc:implement` 一併處理）
- `models.StatusType` 新增列舉值 `pending = "pending"`。
- 前端 `widgets.StatusBadge._MAP` 與 `theme` 新增 `pending` → 中性灰（例如 `textMuted`）對應；`AlertCard._META` 新增 `list_stale` 類型（沿用 `api_delay` 視覺）。
- 這些屬實作細節，本設計僅標示介面/視覺契約。

---

## 4. 介面契約（簽章；不含實作）

### 4.1 `camera_client.py` — 變更回傳契約
```python
@dataclass
class PlateListResult:
    ok: bool              # True 僅當 HTTP 2xx 且成功解析(含 found=0)
    plates: set[str]      # ok 時的車牌集合(可能為空=found=0)
    http_status: int | None
    reason: str = ""      # 失敗原因(供 log/alert)

def find_plate_list(self, name: str) -> PlateListResult: ...
    # name: "TrafficRedList" | "TrafficBlackList"
    # 取代現行 -> set[str]；呼叫端依 ok / len(plates) 套用 §2 決策矩陣
```

### 4.2 `db.py` — 新增（沿用 `with _lock:` + commit 模式）
```python
def plate_list_replace(host: str, list_type: str,
                        plates: set[str], *, sync_ts: str) -> bool: ...
    # 單一交易內 DELETE+INSERT 整批取代；更新 meta(hash/count/last_*_ts);
    # 內容未變(hash 相同)則只更新 meta 並回 False；有變動回 True (NFR-3 原子)

def plate_list_touch(host: str, list_type: str, *,
                     success: bool, sync_ts: str) -> None: ...
    # found=0 / 失敗 路徑：只更新 meta(last_attempt_ts、success 時 last_success_ts)
    # 永不刪明細 (D4)

def plate_list_get(host: str, list_type: str) -> set[str]: ...
def plate_list_load_all() -> dict[str, dict[str, set[str]]]: ...
    # {host: {"red": {...}, "black": {...}}} — 供 ingest 啟動補水

def plate_list_meta(host: str | None = None) -> list[dict]: ...
    # 各 (host,list_type) 的 meta，供過期判定與狀態顯示

def plate_list_state(host: str, *, stale_seconds: int,
                     now_ts: str) -> str: ...
    # 回 'unsynced' | 'fresh' | 'stale'（host 層 = red/black 取較差者）
```

### 4.3 `ingest.py` — 介接點（行為規格，不貼程式）
- `IngestManager.start()`：在啟動相機 thread / simulator **之前**呼叫 `db.plate_list_load_all()` 補水 `self._lists`（FR-1/FR-6）。
- `_refresh_lists(client, host)`：對 red/black 各取 `PlateListResult` → 套 §2 決策矩陣（`plate_list_replace` 或 `plate_list_touch`）→ 僅在 ok+非空+有變動時更新 `self._lists[host]` → 重算 host 狀態 → STALE 時 `db.insert_alert(type="list_stale", id=f"liststale_{host}", site=…)`；回 FRESH 時將該 alert 標記 resolved/移除。
- `_handle_event(...)`：依該 host 狀態決定傳入 `normalize_traffic` 的 `list_state`（`unsynced` → pending）。
- `_refresh_loop()`（每 `poll_interval`）：除既有健康檢查外，重新評估各 host 過期狀態（即使無新事件也能由 FRESH→STALE 並上告警牆）。

### 4.4 `config.py`
```python
@dataclass
class AppConfig:
    ...
    plate_list_stale_seconds: int = 0   # 0 -> 執行期取 max(120, 2*poll_interval)
# load_config(): 讀 cameras.json 的 "plate_list_stale_seconds"（可選）
```

---

## 5. 流程圖

### 5.1 啟動補水（FR-1/FR-6）
```
app.lifespan → db.connect() → IngestManager.start()
   └─ db.plate_list_load_all() ──▶ self._lists (記憶體)   ← 早於相機 thread
   └─ 啟動 camera threads / simulator
   (第一個事件進來時，分類已可用最後良好名單；無快照→UNSYNCED)
```

### 5.2 週期輪詢 + D4 決策（FR-2/3/4/5）
```
_camera_loop / _refresh_loop:
  for list_type in (red, black):
     r = client.find_plate_list(name)
     ├─ r.ok and r.plates 非空
     │     └─ changed = db.plate_list_replace(host,list_type,r.plates,sync_ts=now)
     │        └─ if changed: self._lists[host][lt] = r.plates
     ├─ r.ok and r.plates 空 (found=0)   → db.plate_list_touch(success=True)   # 不清空
     └─ not r.ok (失敗)                  → db.plate_list_touch(success=False)
  state = db.plate_list_state(host, stale_seconds=cfg, now_ts=now)
  if state == 'stale': raise list_stale alert ; elif 'fresh': clear list_stale alert
```

### 5.3 事件分類讀取（NFR-2：不打 DB）
```
_handle_event → state = host 狀態(快取/meta)
   normalize_traffic(..., redlist=self._lists[host].red,
                          blacklist=self._lists[host].black,
                          list_state=state)
   ├─ plate ∈ black → blacklist
   ├─ plate ∈ red   → whitelist
   ├─ state==unsynced → pending  (FR-10「系統安裝中」)
   └─ else          → stranger
```

---

## 6. 對需求/約束的驗證

| 項目 | 設計如何滿足 |
|---|---|
| 規格 §10/§2（唯讀，不改相機名單） | 全程無 `recordUpdater`；R-2 逃生口僅清本地、且本期 out of scope |
| D4（found=0 永不清空） | §2 矩陣以 `plate_list_touch` 處理，明細不刪 |
| FR-1/6 補水一致 | `start()` 先 `plate_list_load_all()` 再起 thread；分類只讀記憶體 |
| FR-2/3 只在變動時寫 | `snapshot_hash` 比對；相同→meta-only |
| FR-10/D5 未同步 | `pending` 狀態，不判 stranger、不發陌生告警 |
| FR-11/D6 過期上告警牆 | 重用 `alert` 表 + `/sites/{id}/alerts`；自我取代的固定 alert id |
| NFR-1 並發 | 全部 `db.*` 沿用既有 `_lock`(RLock)；快取於起 thread 前補水 |
| NFR-2 效能 | 分類讀記憶體 set；持久化 O(n) hash + 僅差異時交易取代 |
| NFR-3 原子 | `plate_list_replace` 單交易 DELETE+INSERT+meta |

---

## 7. 交付物 / 下一步

- 本文件 = schema + 介面契約 + 流程/狀態機 + R-1/R-2 裁決。
- **下一步 `/sc:implement`**（建議順序）：
  1. `db.py`：建表 + 6 支 plate_list API（含 hash/交易）
  2. `camera_client.py`：`find_plate_list` 改回 `PlateListResult`
  3. `config.py`：`plate_list_stale_seconds`
  4. `ingest.py`：補水、決策矩陣、狀態機、list_stale 告警
  5. `models.py`/前端：`pending` 狀態 + `list_stale` 卡視覺
  6. 驗證：重啟補水、found=0 不清空、stale→告警、UNSYNCED 行為（對 .10 與 simulate 各跑）

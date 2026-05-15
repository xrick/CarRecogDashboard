# 白名單 / 黑名單取得能力 — 現況結論

**日期**：2026-05-15
**對象程式**：[demo/demo1.py](../demo/demo1.py)
**問題**：目前程式已經能取得白名單及黑名單嗎？

---

## 結論（一句話）

> 「取得」的機制白、黑名單**共用同一條 code path**且都已寫好；
> 白名單已用**實機空清單**驗證骨架可行；黑名單**純靠類推、零實測**；
> 兩者在「**清單非空**」時的解析**都還沒拿真資料對過答案**。

---

## 狀態總覽

| 名單 | 內部記錄表 | 能取得？ | 證據等級 |
|---|---|---|---|
| **白名單** | `TrafficRedList` (AllowListDB) | ✅ 能 | 實機驗證過，但**僅「空清單」情境** |
| **黑名單** | `TrafficBlackList` (BlockListDB) | ⚠️ 程式碼上能，**未實機測試** | 僅理論成立 |

---

## 證據

### 白名單 — 已實機驗證（含但書）

實機 log（來自 `/sc:analyze` 輸入）：

```
[detect] 新版 API 不支援 → 切換到舊版 §10.3 TrafficRedList
[OK] findGroup 回傳 2 個群組。
→ GET http://192.168.0.10/cgi-bin/recordFinder.cgi  params={'action':'find','name':'TrafficRedList','count':10}
← 200 http://192.168.0.10/cgi-bin/recordFinder.cgi  body=found=0
[OK] startFind/doFind/stopFind → GroupID=TrafficRedList 共 0 筆
```

證明：成功連線 → 自動 fallback 到舊版 §10.3 API → 正確發出 `recordFinder.cgi?action=find&name=TrafficRedList` → HTTP 200 → 正確解析 `found=0`。

**但書**：設備目前白名單為空（`found=0`），因此**只驗證了「空清單情境」**。清單非空時能否正確解析、正確顯示，**尚未證實**。

### 黑名單 — 程式碼支援，但零實測

關鍵程式碼 [demo/demo1.py:255-305](../demo/demo1.py#L255-L305)（`LegacyTrafficListClient`）：

- **L265–270 `SYNTHETIC_GROUPS`**：同時列出白名單與黑名單兩筆合成群組；fallback 後 UI 群組下拉選單**兩個都會出現**。
- **L284–305 `list_vehicles`**：
  - L286 `if group_id not in {"TrafficRedList", "TrafficBlackList"}` — 白、黑名單走**完全同一個函式**，差別僅 query 參數 `name=`。
  - L292 `recordFinder.cgi?action=find&name=<群組>` → L293 `_parse_kv()` → L295-305 欄位對映。

因此**架構上黑名單必定能取得**（與白名單同一條 path，僅 `name=TrafficBlackList`）。但實機測試只點過 `TrafficRedList`，黑名單**從未對真機執行過**——理論成立、無實證。

---

## 共同未驗證風險（高風險，源自 `/sc:analyze` 報告 H2）

「清單**非空**」時：

- `_parse_kv()`（[demo/demo1.py:57](../demo/demo1.py#L57)）能否正確解析實機的 `records[N].欄位=值` 巢狀格式
- `list_vehicles` 的欄位對映（`RecNo`→`UID`、`MasterOfCar`→`Name`）是否與實機欄位名一致

`found=0` 的成功，對「非空解析路徑」**毫無證明力**（兩條 code path 無交集）。

---

## 用語對照

| UI / 口語 | 內部記錄表 (§10.3) | groupType |
|---|---|---|
| 白名單 / 允許名單 | `TrafficRedList` | `AllowListDB` |
| 黑名單 / 禁止名單 | `TrafficBlackList` | `BlockListDB` |

---

## 升級為「可靠」的下一步（呼應 `/sc:analyze` 建議 #1）

最有效的單一動作：**在設備網頁端，白名單與黑名單各加 1 筆測試車牌**，然後在程式分別點這兩個群組按「取讀」，把兩段 `← 200 ... body=` 原文回貼。

拿到非空真實回應後才能確定：
- `_parse_kv` 與欄位對映無需修改 ── 或得知如何修改
- 黑名單路徑同步獲得實證

在那之前，白名單「非空」與黑名單「全部」皆屬**未證實**狀態；任何寫入路徑修補仍是盲改（見 `/sc:analyze` 報告 H1）。

---

*本文由 `/sc:document` 產生，輸出於 `claudedocs/white_black_lists.md`。相關文件：[diary_20260515.md](diary_20260515.md)、[2026-05-15_whitelist_demo_progress.md](2026-05-15_whitelist_demo_progress.md)。*

# 測試報告 — 2026-05-18

**指令**：`/sc:test` ｜ **範圍**：本 session 全部實作（看板後端 + 前端 + 名單持久化 + 人工拍板）

## 測試環境現況
- 專案**無正式測試框架**：未裝 pytest、無 `pytest.ini/pyproject/conftest`；`tests/*.py` 為獨立連線/示範腳本，非單元測試。
- 依 `/sc:test` 邊界（不新建測試框架），執行本專案既有的驗證方式作為回歸套件：編譯 + 後端單元邏輯 + e2e(simulate) + 前端 offscreen + 實機 smoke。
- 執行環境：in-tree venv（Python 3.12）。

## 結果總覽

| 套件 | 內容 | 通過 | 失敗 |
|---|---|---|---|
| Suite 1 | 16 模組編譯 + 後端單元(parsers/db/D4/state/migration/resolve) + 前端 7 視圖 offscreen | **19** | 0 |
| Suite 2 | 後端 e2e（simulate）：8 REST 端點 + SSE 推送 + resolve 流程 + 驗證 + 404/422 | **15** | 0\* |
| Suite 3 | 實機相機 192.168.0.10 唯讀 smoke | **3** | 0 |
| **合計** | | **37** | **0** |

\* Suite 2 T2.11 初次顯示 FAIL，**經分析為測試輔助函式自身缺陷**（`post()` 重複送出兩次 POST：第一次已 resolve→第二次回 `resolved:false`）。以正確單次 POST 重驗 T2.11\* → `200 {resolved:true, resolution:false_positive}` **PASS**；且 T2.12 冪等、T2.14 已移除、`alert_action` 剛好 1 筆（無洗版）均佐證產品行為正確。**非產品缺陷**。

## 涵蓋明細

**Suite 1（單元/結構）**
- T1.1 16 模組 `py_compile` 全通過
- T1.2–1.7 camera_client：eventManager `Code=…;data={JSON}` 解析(TrafficJunction/FaceRecognition)、Heartbeat/空字串忽略、recordFinder key=value、normalize 白名單/未同步→pending、方向 entry→IN/exit→OUT
- T1.8–1.12 db：`_migrate` 舊 schema 補欄位、`plate_list_replace` 差異偵測、D4 found=0 保留、狀態機 unsynced/fresh/stale、`resolve_alert` 稽核僅記真實轉移一次
- T1.13 全 7 視圖（overview/site/vehicle/personnel/trend/alert/cctv）offscreen 渲染無例外
- T1.14 pending badge / FlashCard / AlertCard(list_stale) 建立無例外

**Suite 2（e2e simulate）**
- T2.1–2.9 `/`、`/sites/summary`(12 工地)、`/sites/{id}/summary`、`/events/latest`、`/trends/hourly`(24h+forecast)、`/system/status`、`/alerts`(種子)、`/copilot`、`/cameras`([] in simulate)
- T2.10 SSE `/stream/events` 8 秒內推送事件
- T2.11\*/2.12/2.13 resolve：首次 `resolved:true` / 冪等 `resolved:false` / 錯誤 enum `422`
- T2.14 已 resolve 告警從 `/alerts` 消失（resolved=0 過濾）
- T2.15 未知工地 `404`
- DB：8 表齊全（site/event/alert/alert_suggestion/alert_action/copilot_summary/system_status/plate_list/plate_list_meta）、稽核留存、事件落庫(9)

**Suite 3（實機 .10 唯讀）**
- T3.1 `getSystemInfo` → XC-204BLPR
- T3.2 `find_plate_list` → `PlateListResult(ok=True, http=200)`（found=0 正確判為成功而非失敗）
- T3.3 `eventManager.attach` → HTTP 200 `multipart/x-mixed-replace`（未 hang，異於 attachFileProc）

## 品質指標 / 缺口

- **產品缺陷**：0。**測試輔助瑕疵**：1（已修正/說明，不影響產品）。
- **無自動化覆蓋率工具**（無 coverage.py）：上述為情境式驗證，非行覆蓋率數字。
- **未涵蓋（需現場條件）**：真實 `TrafficJunction/FaceRecognition` 事件的 `data={JSON}` 結構（.10 目前僅 Heartbeat，無人車經過）；待現場觸發後以 `data/event_sample_<host>.json` 校正。
- **已知設計限制（非缺陷）**：R-2 相機名單真清空不自動反映（D4 已接受）。

## 建議
1. （可選）導入 `pytest` + `coverage`，把上述情境固化為 `tests/` 正式套件與 CI（屬「新增測試框架」，需另行授權，不在 `/sc:test` 範圍）。
2. 現場安排一次車輛/人員通過 .10 閘口 → 驗證事件全鏈路（相機→ingest→SQLite→SSE→看板）與 parser 最終校正。
3. 下一步：`/sc:git` 提交本 session 變更。

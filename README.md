# 工地看板系統 — Site Board Dashboard

Standalone display board for the 中華航空AI智慧工安辨識事件管理系統,
implemented from:

- `refData/規格書/工地看板_UI功能設計補充規格書_趨勢與即時快訊.docx`
- `refData/規格書/工地看板_UI趨勢與即時快訊模板.pptx`
- approved visual reference `tests/dashboard-standalone_demo2.html`

**PyQt5 frontend** (kiosk display) + **FastAPI backend** (REST + SSE push).
The board is *display + switch only* — it never creates/edits/deletes data
(spec §2 操作限制, §10 資料邊界).

---

## Use-case breakdown (from the spec)

| # | Scenario | Where | Spec |
|---|----------|-------|------|
| UC-1 | 全工地總覽:12+ 工地總 KPI、工地卡片、跨工地最新快訊 | `overview` | §4.1 / 模板 p.3 |
| UC-2 | 單一工地看板:人車 KPI、24H 趨勢+AI 預測、最新事件、截圖 | `site` | §4.2 / p.4 |
| UC-3 | 車輛進出看板:車牌/承攬商/車型/名單狀態/車輛截圖/車次趨勢 | `vehicle` | §4.3 / p.7 |
| UC-4 | 人員進出看板:人臉截圖/姓名/工號/承攬商/證照狀態/人數趨勢 | `personnel` | §4.4 / p.6 |
| UC-5 | 趨勢全螢幕:0-24H 每小時人車進出,標示目前小時與峰值 | `trend` | §6 / p.8 |
| UC-6 | 異常事件牆:黑名單/證照過期/陌生車牌/API 延遲 + AI 解釋 | `alert` | §5 / p.10 |
| UC-7 | 即時快訊跳卡:新事件 1 秒內彈卡,5s/8s,最多 3,優先級排隊 | overlay | §5 |
| UC-8 | 自動輪播:總覽 30→單工地 30→車輛 20→人員 20s,告警中斷 | control bar | §7 / p.2 |
| UC-9 | 工地切換 / 手動刷新 / 全螢幕 / 控制列收合 / 快捷鍵 | control bar | §7 / §9 |
| UC-10 | 斷線處理:保留最後資料、顯示最後更新時間與錯誤狀態 | offline banner | §7 / §10 |
| UC-11 | API 即時推送優先,備援每 60 秒輪詢 | SSE + poller | §2 / §11 |

## Architecture

```
PyQt5 board ──(SSE)──>  GET /dashboard/stream/events     (push, <1s)
            ──(REST)──> GET /dashboard/sites/summary       (60s poll fallback)
                        GET /dashboard/sites/{id}/summary
                        GET /dashboard/sites/{id}/events/latest
                        GET /dashboard/sites/{id}/trends/hourly
                        GET /dashboard/system/status
                        GET /dashboard/sites/{id}/alerts
                        GET /dashboard/sites/{id}/copilot
```

```
src/
  backend/   models.py     Pydantic schemas (spec §8.2 snake_case)
             mock_data.py  in-memory store + live event simulator (replace
                           with 車牌/人臉 platform calls in production)
             app.py        FastAPI app, routes, SSE stream
  frontend/  theme.py      palette/typography (spec §2 顏色規則)
             api_client.py ApiPoller + EventStream QThreads (requests/SSE)
             charts.py     QPainter hourly bar/line + AI forecast cone
             widgets.py    KPI/badges/snapshots/event rows/flash/alert cards
             views.py      the 6 screens
             main.py       window, tab bars, rotation, keyboard, overlay
```

The SSE push channel uses plain `text/event-stream` so the PyQt client
consumes it with `requests` (no extra websocket dependency). On any network
failure the board keeps its last good snapshot and shows an offline banner —
the screen is never blanked (spec §10 斷線處理).

## Running

```bash
source run_env.sh                 # in-tree venv
pip install -r requirements.txt   # first time (FastAPI/uvicorn)

./start_service.sh                # 背景啟動 後端+前端 -> http://0.0.0.0:8000 (/docs)
./start_service.sh -- --fullscreen   # kiosk 全螢幕
./stop_service.sh                 # 停止整個系統
# 自訂:  ./start_service.sh 0.0.0.0 8000  |  CARDASH_API=http://host:8000 ./start_service.sh
# log: logs/backend.log logs/frontend.log   PID: run/*.pid
```

## Keyboard (spec §9)

`1`-`6` 切換看板模式 · `←` `→` 切換工地 · `R` 立即刷新 ·
`F11` 全螢幕 · `Esc` 顯示/隱藏控制列 · `Q` 結束

## Notes / 研發待確認 (spec §11)

- Snapshots are placeholder vector renderings; wire real `snapshot_url` /
  `plate_snapshot_url` once the 截圖 token/proxy decision is made (§11).
- 在場人數/車輛 currently from the source platform; the board does not
  recompute them (§11).
- Poll interval defaults to 60 s (spec §2); SSE delivers events in ~1 s.

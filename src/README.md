# 工地看板系統 — Site Board Dashboard

Standalone display board for the 中華航空AI智慧工安辨識事件管理系統.

* UI/UX spec: `refData/規格書/工地看板_UI功能設計補充規格書_趨勢與即時快訊.docx`
  + `..._UI趨勢與即時快訊模板.pptx`; visual reference
  `tests/dashboard-standalone_demo2.html`.
* Camera protocol: `manuals/main/中性简体_HTTP_API_协议规范V3.87.pdf`.

**PyQt5 frontend** (kiosk) + **FastAPI backend** (REST + SSE) + **SQLite**
persistence + a **中性/Dahua camera client** that speaks the V3.87 HTTP API.
The board is display + switch only — never writes 名單/主檔 (spec §2/§10).

## Data flow

```
中性/Dahua ANPR + Face cameras                 ┌─ db (SQLite) ─┐
  │  §3.4  HTTP Digest auth                     │  site         │
  │  §4.6.39 magicBox getSystemInfo (health)    │  event (log)  │
  │  §4.4.3 snapManager attachFileProc ─ events │  alert        │
  │  §10.1.1 TrafficJunction / §9.2.16 Face     │  copilot      │
  │  §4.4.3 jpeg parts ─ snapshots              │  system_status│
  │  §10.3.4 recordFinder TrafficRed/BlackList  └───────────────┘
  │  §10.7.8 VehicleRegisterDB (fallback)              ▲   │
  ▼                                                    │   ▼ aggregate today
ingest.py  ── normalize ──> db.insert_event ───────────┘  REST  /dashboard/...
  │                              │                          SSE   /dashboard/stream/events
  └─ Hub.broadcast ──────────────┴────────────────────────> PyQt5 board
(no camera configured → mock_data.Simulator feeds the SAME pipeline)
```

KPIs / hourly trend / 在場數 are **computed by SQL aggregation over today's
`event` rows** — the board derives them from 進出事件 itself (spec §11 option),
not hardcoded numbers.

## Backend layout (`src/backend/`)

| file | role |
|------|------|
| `config.py` | sites + cameras from `config/cameras.json`; absent → simulate |
| `camera_client.py` | V3.87 client: Digest auth, getSystemInfo, attachFileProc multipart parser, recordFinder + VehicleRegisterDB, normalisers |
| `db.py` | SQLite schema (subset of `claudedocs/tableInfo.sql`) + write/aggregate-read API |
| `ingest.py` | camera threads → DB + SSE; periodic list/health refresh; simulator fallback; `Hub` (thread→asyncio SSE bridge) |
| `mock_data.py` | demo seed + the no-camera `Simulator` |
| `models.py` | Pydantic response schemas (spec §8.2) |
| `app.py` | FastAPI routes (all read from `db`), snapshot route, SSE |

## REST + realtime API (spec §8.1)

`GET /dashboard/sites/summary` · `/sites/{id}/summary` ·
`/sites/{id}/events/latest` · `/sites/{id}/trends/hourly` ·
`/system/status` · `/sites/{id}/alerts` · `/sites/{id}/copilot` ·
`/snapshots/{name}` (camera jpeg) · `/stream/events` (SSE push, 60s poll
fallback). `{id}` accepts `ALL`.

## Running

```bash
source run_env.sh
pip install -r requirements.txt          # first time

# Camera mode: cp config/cameras.example.json config/cameras.json and edit.
# No config (or simulate:true) → demo simulator, identical pipeline.
./start_service.sh                       # background: backend + board (/docs)
./start_service.sh -- --fullscreen       # kiosk fullscreen
./stop_service.sh                        # stop the whole system
# CARDASH_CONFIG / CARDASH_DB / CARDASH_API env vars override paths.
# logs/backend.log logs/frontend.log · run/*.pid
```

## Camera → board field mapping

| camera (V3.87) | board Event |
|----------------|-------------|
| `TrafficCar.PlateNumber` (§10.1.1) | `display_name` (vehicle) |
| `Candidates[0].Person.Name/ID` (§9.2.16) | `display_name` / `secondary_id` |
| `Candidates[0].Similarity` | `confidence` (÷100) |
| camera `role` entry/exit | `direction` IN/OUT (TrafficJunction has none) |
| plate ∈ TrafficRedList / TrafficBlackList | `status_type` whitelist / blacklist |
| jpeg part → `data/snapshots/<id>.jpg` | `snapshot_url` |

## Notes / 研發待確認 (spec §11)

- TrafficJunction carries no IN/OUT; direction is set per camera `role`
  (entry/exit) — the realistic model for a construction-site gate.
- Allow/deny lists are **read-only** mirrors (spec §10): primary
  `recordFinder.cgi`, fallback `VehicleRegisterDB` (CLAUDE.md model caveat).
- `config/cameras.json` and `data/` are git-ignored (credentials / runtime).

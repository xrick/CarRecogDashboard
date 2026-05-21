"""
FastAPI backend for the 工地看板 (Site Board).

Now data-backed: every read comes from SQLite (src/backend/db.py), populated
by src/backend/ingest.py — either from real 中性/Dahua cameras over the
中性简体 HTTP API V3.87 (Digest auth, snapManager attachFileProc event stream,
recordFinder/VehicleRegisterDB allow-deny lists) or, when no camera is
configured, from the demo simulator. Same db + SSE pipeline either way.

Run:  uvicorn src.backend.app:app --host 0.0.0.0 --port 8000
Env:  CARDASH_CONFIG (cameras.json)  CARDASH_DB (sqlite path)
"""
from __future__ import annotations

import asyncio
import contextlib
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from . import db
from .camera_client import CameraClient, CameraError
from .config import load_config
from .ingest import SNAPSHOT_DIR, Hub, IngestManager
from .mock_data import SITES
from .models import (
    Alert, AlertResolveRequest, AlertResolveResponse, CameraStream,
    CopilotSummary, Event, HistoricalPlateResponse, HourlyTrendResponse,
    SiteSummary, SitesSummaryResponse, SystemStatus,
)

hub = Hub()
_cfg = load_config()
_ingest: IngestManager | None = None


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    global _ingest
    db.connect(_cfg.db_path)
    _ingest = IngestManager(_cfg, hub)
    _ingest.start(asyncio.get_running_loop())
    try:
        yield
    finally:
        if _ingest:
            await _ingest.stop()
        db.close()


app = FastAPI(title="工地看板 Site Board API", version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

_KNOWN = {s["id"] for s in SITES} | {"ALL"}


def _check(site_id: str) -> str:
    if site_id not in _KNOWN:
        raise HTTPException(status_code=404, detail=f"unknown site_id: {site_id}")
    return site_id


@app.get("/", tags=["meta"])
def root() -> dict:
    return {"service": "site-board-api", "version": "2.0.0",
            "mode": "simulate" if _cfg.simulate or not _cfg.all_cameras
            else "camera", "events_stored": db.event_count(), "docs": "/docs"}


@app.get("/dashboard/sites/summary", response_model=SitesSummaryResponse,
         tags=["board"])
def sites_summary() -> dict:
    return db.sites_summary()


@app.get("/dashboard/sites/{site_id}/summary", response_model=SiteSummary,
         tags=["board"])
def site_summary(site_id: str) -> dict:
    _check(site_id)
    if site_id == "ALL":
        ss = db.sites_summary()
        ov = ss["overview"]
        return dict(site_id="ALL", site_name="全部工地",
                    last_update_time=ss["last_update_time"], status="normal",
                    **{k: ov[k] for k in ("people_in", "people_out",
                                          "people_inside", "vehicle_in",
                                          "vehicle_out", "vehicle_inside",
                                          "alert_count")})
    return db.site_summary(site_id)


@app.get("/dashboard/sites/{site_id}/events/latest",
         response_model=list[Event], tags=["board"])
def latest_events(site_id: str, limit: int = Query(20, ge=1, le=60)) -> list[dict]:
    _check(site_id)
    return db.latest_events(site_id, limit)


@app.get("/dashboard/sites/{site_id}/trends/hourly",
         response_model=HourlyTrendResponse, tags=["board"])
def hourly_trend(site_id: str) -> dict:
    _check(site_id)
    return db.hourly_trend(site_id)


@app.get("/dashboard/system/status", response_model=SystemStatus, tags=["board"])
def system_status() -> dict:
    return db.system_status()


@app.get("/dashboard/sites/{site_id}/alerts", response_model=list[Alert],
         tags=["board"])
def site_alerts(site_id: str) -> list[dict]:
    _check(site_id)
    return db.alerts(site_id)


@app.post("/dashboard/sites/{site_id}/alerts/{alert_id}/resolve",
          response_model=AlertResolveResponse, tags=["board"])
def resolve_alert(site_id: str, alert_id: str,
                  req: AlertResolveRequest) -> dict:
    """人工拍板 — 確認告警 / 標記誤判 (spec §5)。看板端唯一允許的寫入動作:
    只落 alert.resolved + alert_action 稽核，不回寫相機/名單 (規格 §10)。"""
    _check(site_id)
    changed = db.resolve_alert(alert_id, resolution=req.resolution.value,
                               actor=req.actor or "operator", note=req.note)
    if not changed:
        # already resolved or unknown id — idempotent, not an error
        return AlertResolveResponse(alert_id=alert_id, resolved=False,
                                    resolution=req.resolution.value).model_dump()
    return AlertResolveResponse(alert_id=alert_id, resolved=True,
                                resolution=req.resolution.value).model_dump()


@app.get("/dashboard/sites/{site_id}/copilot", response_model=CopilotSummary,
         tags=["board"])
def copilot(site_id: str) -> dict:
    _check(site_id)
    return db.copilot(None if site_id == "ALL" else site_id)


@app.get("/dashboard/sites/{site_id}/cameras",
         response_model=list[CameraStream], tags=["board"])
def site_cameras(site_id: str) -> list[dict]:
    """RTSP stream descriptors for the 現場影像 panel (spec §4.1.1).
    Empty in simulate mode (no cameras configured)."""
    _check(site_id)
    out: list[dict] = []
    for s in _cfg.sites:
        if site_id != "ALL" and s.site_id != site_id:
            continue
        for c in s.cameras:
            out.append(dict(
                site_id=s.site_id, site_name=s.site_name,
                host=c.host_only, channel=c.channel, subtype=c.rtsp_subtype,
                role=c.role, kind=c.kind, rtsp_url=c.rtsp_url))
    return out


@app.get("/dashboard/snapshots/{name}", tags=["board"])
def snapshot(name: str) -> FileResponse:
    """Serve a camera snapshot saved by the ingest layer (§4.4.3 jpeg part)."""
    safe = SNAPSHOT_DIR / name
    if ".." in name or not safe.is_file():
        raise HTTPException(status_code=404, detail="snapshot not found")
    return FileResponse(safe, media_type="image/jpeg")


# --------------------------------------------------------------------------- #
# §4.10.19 — 歷史車牌查詢 (downPicByTime)
# --------------------------------------------------------------------------- #
_HISTORY_DIR = SNAPSHOT_DIR / "history"


def _parse_iso(s: str, fallback_hour: int) -> "datetime":
    """Accept ``YYYY-MM-DDTHH:MM:SS`` / ``YYYY-MM-DD HH:MM:SS`` / ``YYYY-MM-DD``
    (when bare date, fill HH:MM:SS with ``fallback_hour``:00:00 for start,
    23:59:59 for end). Naive local time — matches the V3.87 startTime format."""
    from datetime import datetime
    s = s.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            if fmt == "%Y-%m-%d":
                dt = dt.replace(hour=fallback_hour,
                                minute=59 if fallback_hour == 23 else 0,
                                second=59 if fallback_hour == 23 else 0)
            return dt
        except ValueError:
            continue
    raise HTTPException(status_code=400,
                        detail=f"invalid datetime: {s!r}")


@app.get("/dashboard/sites/{site_id}/history/plates",
         response_model=HistoricalPlateResponse, tags=["board"])
def history_plates(
    site_id: str,
    start: str = Query(..., description="ISO datetime, e.g. 2026-05-21 08:00:00"),
    end: str = Query(..., description="ISO datetime"),
    plate: str | None = Query(None, description="optional plate substring filter"),
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    """歷史車牌查詢 — spec §4.10.19 ``loadfile.cgi?action=downPicByTime``.

    When the site has a camera/NVR configured, queries it directly (one HTTP
    request returns multipart JSON+JPEG pairs covering the full window). In
    simulate mode (no hardware), falls back to the local ``event`` table
    populated by the demo simulator — same response shape so the dashboard
    behaves identically.

    JPEGs from real cameras are persisted under ``data/snapshots/history/``
    and exposed via ``/dashboard/snapshots/history/{filename}``."""
    _check(site_id)
    if site_id == "ALL":
        raise HTTPException(status_code=400,
                            detail="history search needs a specific site_id")
    start_dt = _parse_iso(start, fallback_hour=0)
    end_dt = _parse_iso(end, fallback_hour=23)
    if end_dt <= start_dt:
        raise HTTPException(status_code=400,
                            detail="end must be later than start")

    # Pick the first ANPR camera for this site (entry preferred over exit).
    site_cfg = next((s for s in _cfg.sites if s.site_id == site_id), None)
    anpr_cams = [c for c in (site_cfg.cameras if site_cfg else [])
                 if c.kind in ("anpr", "both")]
    anpr_cams.sort(key=lambda c: 0 if c.role == "entry" else 1)
    cam = anpr_cams[0] if anpr_cams else None

    items: list[dict] = []
    mode = "simulate"

    if cam is not None:
        # Real camera/NVR path.
        client = CameraClient(cam)
        _HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        start_fmt = start_dt.strftime("%Y-%m-%d %H:%M:%S")
        end_fmt = end_dt.strftime("%Y-%m-%d %H:%M:%S")
        try:
            from datetime import datetime
            for i, cap in enumerate(client.download_traffic_pics_by_time(
                    start_fmt, end_fmt, channel=cam.channel)):
                if i >= limit:
                    break
                if plate and plate.upper() not in cap.plate.upper():
                    continue
                fname = f"hist_{cam.host_only}_{cap.utc}_{cap.utcms:03d}.jpg"
                safe_name = fname.replace("/", "_").replace(":", "_")
                (_HISTORY_DIR / safe_name).write_bytes(cap.jpeg)
                ts = datetime.fromtimestamp(cap.utc)
                items.append(dict(
                    plate=cap.plate, speed=cap.speed,
                    event_ts=ts.isoformat(timespec="seconds"),
                    event_time=ts.strftime("%H:%M:%S"),
                    address=cap.address,
                    snapshot_url=f"/dashboard/snapshots/history/{safe_name}",
                    source="camera",
                    host=cam.host_only, channel=cam.channel,
                ))
            mode = "camera"
        except CameraError:
            # Hardware unreachable → silently fall back to simulate path.
            cam = None

    if cam is None:
        # Simulate fallback: synthesise from local events table.
        # event.event_ts is stored as "YYYY-MM-DD HH:MM:SS" (space separator) —
        # use the same format so SQLite BETWEEN works as expected.
        rows = db.vehicle_events_in_range(
            site_id, start_dt.strftime("%Y-%m-%d %H:%M:%S"),
            end_dt.strftime("%Y-%m-%d %H:%M:%S"),
            plate_like=plate, limit=limit)
        for r in rows:
            items.append(dict(
                plate=r["display_name"], speed=0,
                event_ts=r["event_ts"], event_time=r["event_time"],
                address=r["site_name"],
                snapshot_url=r.get("snapshot_url"),
                source="simulate", host=None, channel=None,
            ))

    return dict(
        site_id=site_id, start=start_dt.isoformat(timespec="seconds"),
        end=end_dt.isoformat(timespec="seconds"),
        total=len(items), mode=mode, items=items,
    )


@app.get("/dashboard/snapshots/history/{name}", tags=["board"])
def history_snapshot(name: str) -> FileResponse:
    """Serve a §4.10.19 historical snapshot."""
    safe = _HISTORY_DIR / name
    if ".." in name or "/" in name or not safe.is_file():
        raise HTTPException(status_code=404, detail="snapshot not found")
    return FileResponse(safe, media_type="image/jpeg")


@app.get("/dashboard/stream/events", tags=["realtime"])
async def stream_events() -> StreamingResponse:
    """SSE push channel (spec §11). Falls back to 60s polling if dropped."""
    queue = hub.subscribe()

    async def gen() -> AsyncIterator[bytes]:
        try:
            yield b": connected\n\n"
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=20.0)
                    yield f"event: site-event\ndata: {payload}\n\n".encode()
                except asyncio.TimeoutError:
                    yield b": keep-alive\n\n"
        finally:
            hub.unsubscribe(queue)

    return StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

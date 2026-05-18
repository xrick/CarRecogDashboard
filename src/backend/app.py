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
from .config import load_config
from .ingest import SNAPSHOT_DIR, Hub, IngestManager
from .mock_data import SITES
from .models import (
    Alert, CameraStream, CopilotSummary, Event, HourlyTrendResponse,
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

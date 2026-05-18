"""
FastAPI backend for the 工地看板 (Site Board) dashboard.

Implements every endpoint required by the spec §8.1, plus an SSE stream
(`/dashboard/stream/events`) so the board gets the spec's *push-preferred,
60s-poll-fallback* behaviour without adding a websocket dependency on the
PyQt client (plain ``requests`` can consume text/event-stream).

Run:  uvicorn src.backend.app:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import asyncio
import contextlib
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .mock_data import SITES, store
from .models import (
    Alert,
    CopilotSummary,
    Event,
    HourlyTrendResponse,
    SiteSummary,
    SitesSummaryResponse,
    SystemStatus,
)


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    task = asyncio.create_task(store.run_simulator(interval=6.0))
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="工地看板 Site Board API", version="1.0.0", lifespan=lifespan)

# the board may run on a different host than the API (50" kiosk scenario)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

_KNOWN = {s["id"] for s in SITES} | {"ALL"}


def _check_site(site_id: str) -> str:
    if site_id not in _KNOWN:
        raise HTTPException(status_code=404, detail=f"unknown site_id: {site_id}")
    return site_id


@app.get("/", tags=["meta"])
def root() -> dict:
    return {"service": "site-board-api", "version": "1.0.0", "docs": "/docs"}


@app.get("/dashboard/sites/summary", response_model=SitesSummaryResponse, tags=["board"])
def sites_summary() -> SitesSummaryResponse:
    """全部工地總覽數據 — spec §8.1."""
    return store.sites_summary()


@app.get("/dashboard/sites/{site_id}/summary", response_model=SiteSummary, tags=["board"])
def site_summary(site_id: str) -> SiteSummary:
    """單一工地即時統計 — spec §8.1."""
    _check_site(site_id)
    if site_id == "ALL":
        ov = store.overview()
        return SiteSummary(
            site_id="ALL", site_name="全部工地",
            people_in=ov.people_in, people_out=ov.people_out,
            people_inside=ov.people_inside, vehicle_in=ov.vehicle_in,
            vehicle_out=ov.vehicle_out, vehicle_inside=ov.vehicle_inside,
            alert_count=ov.alert_count,
            last_update_time=store.sites_summary().last_update_time,
        )
    return store.site_summary(site_id)


@app.get("/dashboard/sites/{site_id}/events/latest",
         response_model=list[Event], tags=["board"])
def latest_events(site_id: str, limit: int = Query(20, ge=1, le=60)) -> list[Event]:
    """最新進出事件 — spec §8.1."""
    _check_site(site_id)
    return store.latest_events(site_id, limit)


@app.get("/dashboard/sites/{site_id}/trends/hourly",
         response_model=HourlyTrendResponse, tags=["board"])
def hourly_trend(site_id: str) -> HourlyTrendResponse:
    """0-24H 每小時趨勢 + AI 預測 — spec §6 / §8.1."""
    _check_site(site_id)
    sid, name, cur, trend, forecast = store.hourly(site_id)
    return HourlyTrendResponse(site_id=sid, site_name=name, current_hour=cur,
                               trend=trend, forecast=forecast)


@app.get("/dashboard/system/status", response_model=SystemStatus, tags=["board"])
def system_status() -> SystemStatus:
    """資料源與看板程式狀態 — spec §8.1."""
    return store.system_status()


@app.get("/dashboard/sites/{site_id}/alerts",
         response_model=list[Alert], tags=["board"])
def site_alerts(site_id: str) -> list[Alert]:
    """異常事件牆資料 — spec §4.4 / 模板第 10 頁。"""
    _check_site(site_id)
    return store.alerts(site_id)


@app.get("/dashboard/sites/{site_id}/copilot",
         response_model=CopilotSummary, tags=["board"])
def copilot(site_id: str) -> CopilotSummary:
    """AI 副駕駛摘要 (Agentic supervisor)。"""
    _check_site(site_id)
    return store.copilot()


@app.get("/dashboard/stream/events", tags=["realtime"])
async def stream_events() -> StreamingResponse:
    """Server-Sent Events stream of new 進出事件 (spec §11 push channel).

    Falls back gracefully: if the client drops, the board keeps polling the
    REST endpoints every 60 s (spec §2 刷新模式)."""
    queue = store.subscribe()

    async def gen() -> AsyncIterator[bytes]:
        try:
            yield b": connected\n\n"
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=20.0)
                    yield f"event: site-event\ndata: {payload}\n\n".encode()
                except asyncio.TimeoutError:
                    yield b": keep-alive\n\n"  # keep proxies from closing idle conn
        finally:
            store.unsubscribe(queue)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

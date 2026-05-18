"""
Ingestion orchestration — the only place that decides *where* events come from.

* CAMERA mode (config has cameras): one daemon thread per camera holds the
  §4.4.3 attachFileProc multipart stream, parses TrafficJunction / FaceRecognition
  parts, normalises them, persists to SQLite and fans them out on SSE. JPEG
  parts are saved to data/snapshots and linked back onto the event.
  A periodic async task refreshes the allow/deny lists and §4.6.39 system
  status (and raises an api_delay alert when a camera goes quiet).
* SIMULATE mode (no cameras): the Simulator feeds the SAME db + SSE pipeline.

The SSE Hub bridges worker threads -> the asyncio event loop with
``loop.call_soon_threadsafe`` so subscriber queues stay loop-affine.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import db
from .camera_client import (
    CameraClient, CameraError, normalize_face, normalize_traffic,
)
from .config import AppConfig
from .mock_data import Simulator, seed_database

SNAPSHOT_DIR = Path(__file__).resolve().parents[2] / "data" / "snapshots"


class Hub:
    """SSE subscriber registry; thread-safe broadcast onto the asyncio loop."""

    def __init__(self) -> None:
        self._subs: list[asyncio.Queue] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=50)
        self._subs.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subs:
            self._subs.remove(q)

    def broadcast(self, payload: str) -> None:
        loop = self._loop
        if loop is None:
            return
        for q in list(self._subs):
            loop.call_soon_threadsafe(self._put, q, payload)

    @staticmethod
    def _put(q: asyncio.Queue, payload: str) -> None:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            pass


def _emit(hub: Hub, ev: dict) -> None:
    """Persist + broadcast one normalised event (and derive alerts)."""
    if not db.insert_event(ev):
        return  # duplicate event_id
    if ev.get("status_type") in ("blacklist", "alert"):
        kind = "blacklist" if ev["status_type"] == "blacklist" else "expired"
        db.insert_alert(dict(
            id=f"al_{ev['event_id']}", type=kind,
            target=ev["display_name"]
            + (f" / {ev['secondary_id']}" if ev.get("secondary_id") else ""),
            detail=ev.get("detail", ""), site=ev["site_id"],
            confidence=ev.get("confidence"), why=ev.get("why", ""),
            cost={"fp": "誤攔正常人車 · 中斷作業",
                  "fn": "違規進入 · 安全/法規風險"},
            suggestions=["通知警衛/工安督導確認", "保留現場影像", "回報管理平台"],
            occurrence="即時偵測", occurrence_count=1))
    hub.broadcast(json.dumps(ev, ensure_ascii=False))


class IngestManager:
    def __init__(self, cfg: AppConfig, hub: Hub) -> None:
        self.cfg = cfg
        self.hub = hub
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._lists: dict[str, tuple[set, set]] = {}  # host -> (red, black)
        self._last_seen: dict[str, float] = {}
        self._periodic: Optional[asyncio.Task] = None
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    # ---- lifecycle ------------------------------------------------------
    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self.hub.bind_loop(loop)
        seed_database()
        if self.cfg.simulate or not self.cfg.all_cameras:
            db.set_api_totals(1, 1)
            self._periodic = loop.create_task(self._simulate_loop())
            return
        cams = self.cfg.all_cameras
        db.set_api_totals(len(cams), len(cams))
        for site, cam in cams:
            t = threading.Thread(target=self._camera_loop, args=(site, cam),
                                 daemon=True, name=f"cam-{cam.host}")
            t.start()
            self._threads.append(t)
        self._periodic = loop.create_task(self._refresh_loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._periodic:
            self._periodic.cancel()
            try:
                await self._periodic
            except (asyncio.CancelledError, Exception):
                pass

    # ---- SIMULATE mode --------------------------------------------------
    async def _simulate_loop(self) -> None:
        sim = Simulator()
        while not self._stop.is_set():
            await asyncio.sleep(6.0)
            try:
                _emit(self.hub, sim.fabricate())
                self._refresh_copilot()
                db.record_status(dict(
                    plate_api_status="normal", face_api_status="normal",
                    last_success_time=datetime.now().strftime("%H:%M:%S"),
                    latency_seconds=0, api_online=1, api_total=1,
                    version="1.0.0"))
            except Exception:  # never let the loop die
                pass

    # ---- CAMERA mode (§4.9.17 eventManager.attach — verified on .10) ----
    def _camera_loop(self, site, cam) -> None:
        client = CameraClient(cam)
        backoff = 1.0
        dumped = False
        while not self._stop.is_set():
            try:
                client.get_system_info()  # auth + reachability (§4.6.39)
                self._refresh_lists(client, cam.host)
                backoff = 1.0
                for ev in client.stream_events():
                    if self._stop.is_set():
                        break
                    self._last_seen[cam.host] = time.time()
                    # one-time raw dump so a real event can calibrate the
                    # data={JSON} schema (only Heartbeat seen on .10 so far)
                    if not dumped:
                        dumped = True
                        try:
                            (SNAPSHOT_DIR.parent /
                             f"event_sample_{cam.host}.json").write_text(
                                json.dumps(ev, ensure_ascii=False, indent=2))
                        except Exception:
                            pass
                    self._handle_event(site, cam, ev, client)
            except CameraError:
                self._mark_offline(site, cam, "認證或設備不可達")
            except Exception:
                self._mark_offline(site, cam, "事件串流中斷")
            if not self._stop.is_set():
                time.sleep(min(backoff, 15.0))
                backoff = min(backoff * 2, 15.0)

    def _refresh_lists(self, client: CameraClient, host: str) -> None:
        try:
            red = client.find_plate_list("TrafficRedList")
            black = client.find_plate_list("TrafficBlackList")
            self._lists[host] = (red, black)
        except Exception:
            self._lists.setdefault(host, (set(), set()))

    def _handle_event(self, site, cam, ev: dict, client: CameraClient) -> None:
        code = ev.get("code", "")
        data = ev.get("data", {}) or {}
        # eventManager carries Code/action/index in the part header; the
        # normalisers expect them under EventBaseInfo (like attachFileProc).
        data.setdefault("EventBaseInfo",
                        {"Code": code, "Action": ev.get("action"),
                         "Index": ev.get("index")})
        red, black = self._lists.get(cam.host, (set(), set()))
        now = datetime.now()
        iso, hms = now.strftime("%Y-%m-%d %H:%M:%S"), now.strftime("%H:%M:%S")
        norm = None
        if code == "TrafficJunction":
            norm = normalize_traffic(
                data, site_id=site.site_id, site_name=site.site_name,
                role=cam.role, redlist=red, blacklist=black,
                now_iso=iso, now_hms=hms)
        elif code == "FaceRecognition":
            norm = normalize_face(
                data, site_id=site.site_id, site_name=site.site_name,
                role=cam.role, now_iso=iso, now_hms=hms)
        if not norm:
            return
        # eventManager.attach has no inline jpeg -> pull snapshot.cgi (§4.4.2)
        try:
            jpeg = client.snapshot(cam.channel)
            if jpeg:
                fname = f"{norm['event_id']}.jpg"
                (SNAPSHOT_DIR / fname).write_bytes(jpeg)
                url = f"/dashboard/snapshots/{fname}"
                norm["snapshot_url"] = url
                if norm["event_type"] == "vehicle":
                    norm["plate_snapshot_url"] = url
        except Exception:
            pass
        _emit(self.hub, norm)

    def _mark_offline(self, site, cam, reason: str) -> None:
        last = self._last_seen.get(cam.host)
        last_txt = (datetime.fromtimestamp(last).strftime("%H:%M:%S")
                    if last else "—")
        db.record_status(dict(
            plate_api_status="down", face_api_status="down",
            last_success_time=last_txt, latency_seconds=0,
            error_message=f"{cam.host} · {reason}",
            api_online=0, api_total=len(self.cfg.all_cameras),
            version="1.0.0"))
        db.insert_alert(dict(
            id=f"apidelay_{cam.host}", type="api_delay",
            target=f"{site.site_name} · {cam.host}",
            detail=f"{reason} · 最後事件 {last_txt}", site=site.site_id,
            confidence=None, why="心跳/連線中斷 (staleness 異常)",
            cost={"fp": "誤判導致工程師白跑一趟",
                  "fn": "系統真的離線 · 進出未被記錄"},
            suggestions=["檢查相機/網路連線", "確認帳密與 API 服務",
                         "通知 IT 排查"],
            occurrence="連線監測", occurrence_count=1))

    # ---- periodic (CAMERA mode) ----------------------------------------
    async def _refresh_loop(self) -> None:
        while not self._stop.is_set():
            await asyncio.sleep(self.cfg.poll_interval)
            online = 0
            for site, cam in self.cfg.all_cameras:
                try:
                    CameraClient(cam).get_system_info()
                    online += 1
                except Exception:
                    self._mark_offline(site, cam, "週期健康檢查失敗")
            total = max(len(self.cfg.all_cameras), 1)
            db.set_api_totals(online, total)
            db.record_status(dict(
                plate_api_status="normal" if online else "down",
                face_api_status="normal" if online else "down",
                last_success_time=datetime.now().strftime("%H:%M:%S"),
                latency_seconds=0, api_online=online, api_total=total,
                error_message=None if online else "所有相機離線",
                version="1.0.0"))
            self._refresh_copilot()

    def _refresh_copilot(self) -> None:
        try:
            ss = db.sites_summary()
            ov = ss["overview"]
            db.set_copilot(None, dict(
                headline="AI 副駕駛 · 即時摘要",
                body=(f"今日累計人員進場 {ov['people_in']}、車輛進場 "
                      f"{ov['vehicle_in']};目前異常事件 {ov['alert_count']} 件"
                      f"(黑名單 {ov['blacklist']} · 證照/告警 {ov['expired_cert']})。"
                      f"API 線上 {ov['api_online']}/{ov['api_total']}。"
                      "建議優先處理黑名單與證照過期事件,並確認離線相機。"),
                sources="今日所有進出事件 + 名單比對 + 相機健康檢查",
                model="規則引擎 + 統計摘要",
                generated_at=datetime.now().strftime("%H:%M")))
        except Exception:
            pass

"""
Networking layer for the board.

Two long-lived QThreads, both built on the repo's ``requests`` convention:

* :class:`ApiPoller`  — periodic REST pull (spec §2 備援每 60 秒輪詢). Wakes
  early on a manual refresh ('R') or a site switch.
* :class:`EventStream` — consumes the SSE push channel
  (`/dashboard/stream/events`) so new 進出事件 land within ~1 s
  (spec §10 驗收標準), with auto-reconnect.

On any failure the board keeps its last good data and flips an offline flag —
the screen is never blanked (spec §7 離線提示 / §10 斷線處理).
"""
from __future__ import annotations

import json
import os
import threading

import requests
from PyQt5.QtCore import QObject, QThread, pyqtSignal

API_BASE = os.environ.get("CARDASH_API", "http://127.0.0.1:8000").rstrip("/")


class ApiPoller(QThread):
    data_ready = pyqtSignal(dict)      # full snapshot for the current site
    online_changed = pyqtSignal(bool)

    def __init__(self, interval: int = 60, parent=None) -> None:
        super().__init__(parent)
        self.interval = interval
        self._site = "ALL"
        self._stop = False
        self._wake = threading.Event()
        self._online = None
        self._sess = requests.Session()
        self._sess.headers["Accept"] = "application/json"

    # called from the GUI thread ------------------------------------------
    def set_site(self, site_id: str) -> None:
        self._site = site_id
        self._wake.set()

    def request_refresh(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop = True
        self._wake.set()

    # worker --------------------------------------------------------------
    def _get(self, path: str):
        r = self._sess.get(f"{API_BASE}{path}", timeout=6)
        r.raise_for_status()
        return r.json()

    def _snapshot(self, site: str) -> dict:
        snap: dict = {"site_id": site}
        snap["sites_summary"] = self._get("/dashboard/sites/summary")
        snap["site_summary"] = self._get(f"/dashboard/sites/{site}/summary")
        snap["events"] = self._get(
            f"/dashboard/sites/{site}/events/latest?limit=30")
        snap["trend"] = self._get(f"/dashboard/sites/{site}/trends/hourly")
        snap["status"] = self._get("/dashboard/system/status")
        snap["alerts"] = self._get(f"/dashboard/sites/{site}/alerts")
        snap["copilot"] = self._get(f"/dashboard/sites/{site}/copilot")
        try:
            snap["cameras"] = self._get(f"/dashboard/sites/{site}/cameras")
        except Exception:
            snap["cameras"] = []
        return snap

    def run(self) -> None:
        while not self._stop:
            self._wake.clear()
            site = self._site
            try:
                snap = self._snapshot(site)
                if self._online is not True:
                    self._online = True
                    self.online_changed.emit(True)
                self.data_ready.emit(snap)
            except Exception:  # network down / API error -> keep last data
                if self._online is not False:
                    self._online = False
                    self.online_changed.emit(False)
            # sleep, but break out early on refresh / site switch / stop
            self._wake.wait(timeout=self.interval)


class EventStream(QThread):
    new_event = pyqtSignal(dict)
    stream_online = pyqtSignal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        backoff = 1.0
        while not self._stop:
            try:
                with requests.get(
                    f"{API_BASE}/dashboard/stream/events",
                    stream=True, timeout=(5, None),
                    headers={"Accept": "text/event-stream"},
                ) as resp:
                    resp.raise_for_status()
                    self.stream_online.emit(True)
                    backoff = 1.0
                    data_buf: list[str] = []
                    for raw in resp.iter_lines(decode_unicode=True):
                        if self._stop:
                            break
                        if raw is None:
                            continue
                        line = raw.strip()
                        if line == "":  # dispatch on blank line
                            if data_buf:
                                self._emit("".join(data_buf))
                                data_buf = []
                            continue
                        if line.startswith(":"):  # comment / keep-alive
                            continue
                        if line.startswith("data:"):
                            data_buf.append(line[5:].strip())
            except Exception:
                self.stream_online.emit(False)
            if not self._stop:
                # capped exponential backoff before reconnecting
                self.msleep(int(min(backoff, 15.0) * 1000))
                backoff = min(backoff * 2, 15.0)

    def _emit(self, payload: str) -> None:
        try:
            self.new_event.emit(json.loads(payload))
        except (ValueError, TypeError):
            pass


# --------------------------------------------------------------------------- #
# Human-in-the-loop: 人工拍板 (spec §5). The board's ONLY write call.
# --------------------------------------------------------------------------- #
class _ActionBus(QObject):
    """Signals a board-side action succeeded so the window can refetch
    (resolved alerts then drop out via the resolved=0 filter)."""
    changed = pyqtSignal()


ACTION_BUS = _ActionBus()


class _ResolveWorker(QThread):
    done = pyqtSignal(bool)  # ok?

    def __init__(self, site_id: str, alert_id: str, resolution: str,
                 note: str = "", parent=None) -> None:
        super().__init__(parent)
        self._args = (site_id, alert_id, resolution, note)

    def run(self) -> None:
        site_id, alert_id, resolution, note = self._args
        ok = False
        try:
            r = requests.post(
                f"{API_BASE}/dashboard/sites/{site_id}/alerts/{alert_id}"
                f"/resolve",
                json={"resolution": resolution, "actor": "operator",
                      "note": note},
                timeout=6)
            ok = r.status_code < 400
        except requests.RequestException:
            ok = False
        if ok:
            ACTION_BUS.changed.emit()
        self.done.emit(ok)


_workers: list[_ResolveWorker] = []  # keep refs so QThreads aren't GC'd


def resolve_alert_async(site_id: str, alert_id: str, resolution: str,
                        note: str = "", on_done=None) -> None:
    """Fire-and-forget POST on a QThread (repo convention: never block the
    GUI on requests). ``resolution`` = 'adopted' | 'false_positive'."""
    w = _ResolveWorker(site_id or "ALL", alert_id, resolution, note)

    def _finish(ok: bool) -> None:
        if on_done is not None:
            try:
                on_done(ok)
            except Exception:
                pass
        if w in _workers:
            _workers.remove(w)

    w.done.connect(_finish)
    _workers.append(w)
    w.start()

"""
SQLite persistence — implements the schema from claudedocs/tableInfo.sql
(subset actually used by the board).

Design:
* one connection, WAL, ``check_same_thread=False`` + a write lock — the kiosk
  load is light and this keeps the camera-ingest threads, the SSE loop and the
  request handlers consistent.
* KPI / hourly-trend / in-site counts are computed by SQL aggregation over the
  ``event`` log for *today* — i.e. the board derives 在場數 from 進出事件 itself
  (spec §11 option "由看板服務端依進出事件自行計算"), not hardcoded numbers.
* curated alerts / copilot / sites / seed events are inserted idempotently on
  init so a fresh DB still shows a populated board.
"""
from __future__ import annotations

import hashlib
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

_lock = threading.RLock()
_conn: Optional[sqlite3.Connection] = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS site (
    site_id    TEXT PRIMARY KEY,
    site_name  TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'normal',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS event (
    event_id           TEXT PRIMARY KEY,
    site_id            TEXT NOT NULL,
    site_name          TEXT NOT NULL,
    event_type         TEXT NOT NULL,           -- vehicle | personnel
    direction          TEXT NOT NULL,           -- IN | OUT
    event_ts           TEXT NOT NULL,           -- ISO datetime (local)
    event_time         TEXT NOT NULL,           -- HH:MM:SS (display)
    display_name       TEXT NOT NULL,
    secondary_id       TEXT,
    contractor         TEXT NOT NULL DEFAULT '',
    detail             TEXT NOT NULL DEFAULT '',
    status             TEXT NOT NULL,
    status_type        TEXT NOT NULL,           -- whitelist|pass|stranger|alert|blacklist
    snapshot_url       TEXT,
    plate_snapshot_url TEXT,
    access_result      TEXT NOT NULL DEFAULT '',
    confidence         REAL,
    why                TEXT,
    source             TEXT,
    ingested_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_event_site_ts ON event (site_id, event_ts DESC);
CREATE INDEX IF NOT EXISTS ix_event_ts      ON event (event_ts DESC);
CREATE INDEX IF NOT EXISTS ix_event_stype   ON event (status_type, event_ts DESC);

CREATE TABLE IF NOT EXISTS alert (
    alert_id         TEXT PRIMARY KEY,
    type             TEXT NOT NULL,             -- blacklist|expired|stranger|api_delay
    target           TEXT NOT NULL,
    detail           TEXT NOT NULL DEFAULT '',
    site_id          TEXT NOT NULL,
    confidence       REAL,
    why              TEXT NOT NULL DEFAULT '',
    cost_fp          TEXT NOT NULL DEFAULT '',
    cost_fn          TEXT NOT NULL DEFAULT '',
    occurrence       TEXT NOT NULL DEFAULT '',
    occurrence_count INTEGER NOT NULL DEFAULT 1,
    resolved         INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS alert_suggestion (
    alert_id TEXT NOT NULL,
    seq      INTEGER NOT NULL,
    text     TEXT NOT NULL,
    PRIMARY KEY (alert_id, seq)
);
CREATE TABLE IF NOT EXISTS copilot_summary (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id      TEXT,
    headline     TEXT NOT NULL,
    body         TEXT NOT NULL,
    sources      TEXT NOT NULL DEFAULT '',
    model        TEXT NOT NULL DEFAULT '',
    generated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS system_status (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at       TEXT NOT NULL DEFAULT (datetime('now')),
    plate_api_status  TEXT NOT NULL DEFAULT 'normal',
    face_api_status   TEXT NOT NULL DEFAULT 'normal',
    last_success_time TEXT NOT NULL,
    latency_seconds   INTEGER NOT NULL DEFAULT 0,
    error_message     TEXT,
    api_online        INTEGER NOT NULL DEFAULT 0,
    api_total         INTEGER NOT NULL DEFAULT 0,
    cached_events     INTEGER NOT NULL DEFAULT 0,
    version           TEXT NOT NULL DEFAULT '1.0.0'
);
CREATE TABLE IF NOT EXISTS plate_list (
    host       TEXT NOT NULL,
    list_type  TEXT NOT NULL CHECK (list_type IN ('red','black')),
    plate      TEXT NOT NULL,
    PRIMARY KEY (host, list_type, plate)
);
CREATE INDEX IF NOT EXISTS ix_plate_list_h ON plate_list(host, list_type);
CREATE TABLE IF NOT EXISTS plate_list_meta (
    host            TEXT NOT NULL,
    list_type       TEXT NOT NULL,
    snapshot_hash   TEXT,
    plate_count     INTEGER NOT NULL DEFAULT 0,
    last_success_ts TEXT,            -- last successful NON-EMPTY content sync
    last_change_ts  TEXT,            -- last time content actually changed
    last_attempt_ts TEXT,            -- last fetch attempt (any outcome)
    last_status     TEXT NOT NULL DEFAULT 'unsynced',
    PRIMARY KEY (host, list_type)
);
"""


def connect(db_path: str) -> None:
    global _conn
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(db_path, check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    with _lock:
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA synchronous=NORMAL")
        _conn.executescript(_SCHEMA)
        _conn.commit()


def close() -> None:
    global _conn
    if _conn is not None:
        with _lock:
            _conn.close()
        _conn = None


def _c() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError("db.connect() not called")
    return _conn


# --------------------------------------------------------------------------- #
# Writes
# --------------------------------------------------------------------------- #
def upsert_site(site_id: str, site_name: str, status: str = "normal") -> None:
    with _lock:
        _c().execute(
            "INSERT INTO site(site_id,site_name,status) VALUES(?,?,?) "
            "ON CONFLICT(site_id) DO UPDATE SET site_name=excluded.site_name, "
            "status=excluded.status",
            (site_id, site_name, status))
        _c().commit()


def insert_event(ev: dict) -> bool:
    """Idempotent on event_id. Returns True if a new row was inserted."""
    cols = ("event_id", "site_id", "site_name", "event_type", "direction",
            "event_ts", "event_time", "display_name", "secondary_id",
            "contractor", "detail", "status", "status_type", "snapshot_url",
            "plate_snapshot_url", "access_result", "confidence", "why", "source")
    with _lock:
        cur = _c().execute(
            f"INSERT OR IGNORE INTO event({','.join(cols)}) "
            f"VALUES({','.join('?' * len(cols))})",
            tuple(ev.get(k) for k in cols))
        _c().commit()
        return cur.rowcount > 0


def set_event_snapshot(event_id: str, url: str) -> None:
    with _lock:
        _c().execute(
            "UPDATE event SET snapshot_url=?, "
            "plate_snapshot_url=COALESCE(plate_snapshot_url,?) "
            "WHERE event_id=?", (url, url, event_id))
        _c().commit()


def insert_alert(a: dict) -> None:
    with _lock:
        _c().execute(
            "INSERT OR REPLACE INTO alert(alert_id,type,target,detail,site_id,"
            "confidence,why,cost_fp,cost_fn,occurrence,occurrence_count,resolved)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (a["id"], a["type"], a["target"], a.get("detail", ""), a["site"],
             a.get("confidence"), a.get("why", ""),
             a.get("cost", {}).get("fp", ""), a.get("cost", {}).get("fn", ""),
             a.get("occurrence", ""), a.get("occurrence_count", 1),
             1 if a.get("resolved") else 0))
        _c().execute("DELETE FROM alert_suggestion WHERE alert_id=?", (a["id"],))
        for i, s in enumerate(a.get("suggestions", []), 1):
            _c().execute(
                "INSERT INTO alert_suggestion(alert_id,seq,text) VALUES(?,?,?)",
                (a["id"], i, s))
        _c().commit()


def set_copilot(site_id: Optional[str], c: dict) -> None:
    with _lock:
        _c().execute(
            "INSERT INTO copilot_summary(site_id,headline,body,sources,model,"
            "generated_at) VALUES(?,?,?,?,?,?)",
            (site_id, c["headline"], c["body"], c.get("sources", ""),
             c.get("model", ""), c.get("generated_at", "")))
        _c().execute(
            "DELETE FROM copilot_summary WHERE id NOT IN "
            "(SELECT id FROM copilot_summary ORDER BY id DESC LIMIT 5)")
        _c().commit()


def record_status(s: dict) -> None:
    with _lock:
        _c().execute(
            "INSERT INTO system_status(plate_api_status,face_api_status,"
            "last_success_time,latency_seconds,error_message,api_online,"
            "api_total,cached_events,version) VALUES(?,?,?,?,?,?,?,?,?)",
            (s.get("plate_api_status", "normal"),
             s.get("face_api_status", "normal"),
             s.get("last_success_time", ""), s.get("latency_seconds", 0),
             s.get("error_message"), s.get("api_online", 0),
             s.get("api_total", 0), s.get("cached_events", 0),
             s.get("version", "1.0.0")))
        _c().execute(
            "DELETE FROM system_status WHERE id NOT IN "
            "(SELECT id FROM system_status ORDER BY id DESC LIMIT 50)")
        _c().commit()


# --------------------------------------------------------------------------- #
# Reads (return model-shaped dicts)
# --------------------------------------------------------------------------- #
_TODAY = "date(event_ts)=date('now','localtime')"


def _site_counts(site_id: str) -> dict:
    row = _c().execute(
        f"""SELECT
          SUM(event_type='personnel' AND direction='IN')  AS p_in,
          SUM(event_type='personnel' AND direction='OUT') AS p_out,
          SUM(event_type='vehicle'   AND direction='IN')  AS v_in,
          SUM(event_type='vehicle'   AND direction='OUT') AS v_out,
          SUM(status_type IN ('alert','blacklist'))        AS alerts
        FROM event WHERE site_id=? AND {_TODAY}""", (site_id,)).fetchone()
    pi, po = row["p_in"] or 0, row["p_out"] or 0
    vi, vo = row["v_in"] or 0, row["v_out"] or 0
    return dict(people_in=pi, people_out=po, people_inside=max(pi - po, 0),
                vehicle_in=vi, vehicle_out=vo, vehicle_inside=max(vi - vo, 0),
                alert_count=row["alerts"] or 0)


def _now_hms() -> str:
    return datetime.now().strftime("%H:%M:%S")


def site_summary(site_id: str) -> dict:
    with _lock:
        srow = _c().execute(
            "SELECT site_name,status FROM site WHERE site_id=?",
            (site_id,)).fetchone()
        name = srow["site_name"] if srow else site_id
        status = srow["status"] if srow else "normal"
        k = _site_counts(site_id)
    return dict(site_id=site_id, site_name=name,
                last_update_time=_now_hms(), status=status, **k)


def sites_summary() -> dict:
    with _lock:
        sites = _c().execute(
            "SELECT site_id,site_name,status FROM site ORDER BY site_id"
        ).fetchall()
        per = []
        agg = dict(people_in=0, people_out=0, people_inside=0, vehicle_in=0,
                   vehicle_out=0, vehicle_inside=0, alert_count=0)
        for s in sites:
            k = _site_counts(s["site_id"])
            per.append(dict(site_id=s["site_id"], site_name=s["site_name"],
                            status=s["status"], last_update_time=_now_hms(), **k))
            for key in agg:
                agg[key] += k[key]
        st = _c().execute(
            f"""SELECT
              SUM(status_type='blacklist') AS bl,
              SUM(status_type='alert')     AS al,
              SUM(status_type='stranger')  AS sg
            FROM event WHERE {_TODAY}""").fetchone()
    overview = dict(
        **agg,
        blacklist=st["bl"] or 0, expired_cert=st["al"] or 0,
        stranger_plate=st["sg"] or 0,
        api_online=_api_online(), api_total=max(_api_total(), 1))
    overview["alert_count"] = (st["bl"] or 0) + (st["al"] or 0)
    return dict(overview=overview, sites=per, last_update_time=_now_hms())


_API_TOTALS = {"online": 2, "total": 2}


def set_api_totals(online: int, total: int) -> None:
    _API_TOTALS["online"], _API_TOTALS["total"] = online, total


def _api_online() -> int:
    return _API_TOTALS["online"]


def _api_total() -> int:
    return _API_TOTALS["total"]


def latest_events(site_id: str, limit: int = 20) -> list[dict]:
    with _lock:
        if site_id == "ALL":
            rows = _c().execute(
                "SELECT * FROM event ORDER BY event_ts DESC LIMIT ?",
                (limit,)).fetchall()
        else:
            rows = _c().execute(
                "SELECT * FROM event WHERE site_id=? ORDER BY event_ts DESC "
                "LIMIT ?", (site_id, limit)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d.pop("event_ts", None)
        d.pop("ingested_at", None)
        out.append(d)
    return out


def hourly_trend(site_id: str) -> dict:
    with _lock:
        if site_id == "ALL":
            rows = _c().execute(
                f"""SELECT CAST(strftime('%H',event_ts) AS INT) h,
                  SUM(event_type='personnel' AND direction='IN')  pi,
                  SUM(event_type='personnel' AND direction='OUT') po,
                  SUM(event_type='vehicle'   AND direction='IN')  vi,
                  SUM(event_type='vehicle'   AND direction='OUT') vo
                FROM event WHERE {_TODAY} GROUP BY h""").fetchall()
            name = "全部工地"
        else:
            rows = _c().execute(
                f"""SELECT CAST(strftime('%H',event_ts) AS INT) h,
                  SUM(event_type='personnel' AND direction='IN')  pi,
                  SUM(event_type='personnel' AND direction='OUT') po,
                  SUM(event_type='vehicle'   AND direction='IN')  vi,
                  SUM(event_type='vehicle'   AND direction='OUT') vo
                FROM event WHERE site_id=? AND {_TODAY} GROUP BY h""",
                (site_id,)).fetchall()
            srow = _c().execute("SELECT site_name FROM site WHERE site_id=?",
                                (site_id,)).fetchone()
            name = srow["site_name"] if srow else site_id
    by_h = {r["h"]: r for r in rows}
    trend = []
    for h in range(24):
        r = by_h.get(h)
        trend.append(dict(
            hour=f"{h:02d}",
            people_in=(r["pi"] if r else 0) or 0,
            people_out=(r["po"] if r else 0) or 0,
            vehicle_in=(r["vi"] if r else 0) or 0,
            vehicle_out=(r["vo"] if r else 0) or 0))
    cur = datetime.now().hour
    # simple AI forecast: project current-hour people_in flat with ±30% cone
    base = trend[cur]["people_in"] if cur < 24 else 0
    forecast = []
    for off in range(1, 5):
        hh = cur + off
        if hh > 23:
            break
        val = max(int(base * (0.9 ** off)), 0)
        forecast.append(dict(hour=f"{hh:02d}",
                              people_in_forecast=val,
                              people_in_upper=int(val * 1.3) + 1,
                              people_in_lower=int(val * 0.7)))
    return dict(site_id=site_id, site_name=name, current_hour=cur,
                trend=trend, forecast=forecast)


def alerts(site_id: str) -> list[dict]:
    with _lock:
        if site_id == "ALL":
            rows = _c().execute(
                "SELECT * FROM alert WHERE resolved=0 ORDER BY created_at DESC"
            ).fetchall()
        else:
            rows = _c().execute(
                "SELECT * FROM alert WHERE resolved=0 AND site_id=? "
                "ORDER BY created_at DESC", (site_id,)).fetchall()
        out = []
        for r in rows:
            sug = _c().execute(
                "SELECT text FROM alert_suggestion WHERE alert_id=? ORDER BY seq",
                (r["alert_id"],)).fetchall()
            out.append(dict(
                id=r["alert_id"], type=r["type"], target=r["target"],
                detail=r["detail"], site=r["site_id"],
                confidence=r["confidence"], why=r["why"],
                cost={"fp": r["cost_fp"], "fn": r["cost_fn"]},
                suggestions=[s["text"] for s in sug],
                occurrence=r["occurrence"],
                occurrence_count=r["occurrence_count"]))
    return out


def copilot(site_id: Optional[str] = None) -> dict:
    with _lock:
        row = _c().execute(
            "SELECT headline,body,sources,model,generated_at "
            "FROM copilot_summary ORDER BY id DESC LIMIT 1").fetchone()
    if row:
        d = dict(row)
        d["generated_at"] = datetime.now().strftime("%H:%M")
        return d
    return dict(headline="AI 副駕駛", body="尚無摘要資料。", sources="",
                model="", generated_at=datetime.now().strftime("%H:%M"))


def system_status() -> dict:
    with _lock:
        row = _c().execute(
            "SELECT * FROM system_status ORDER BY id DESC LIMIT 1").fetchone()
        cached = _c().execute(
            f"SELECT COUNT(*) c FROM event WHERE {_TODAY}").fetchone()["c"]
    if row:
        d = dict(row)
        d.pop("id", None)
        d.pop("recorded_at", None)
        d["cached_events"] = cached
        return d
    return dict(plate_api_status="normal", face_api_status="normal",
                last_success_time=_now_hms(), latency_seconds=0,
                error_message=None, api_online=_api_online(),
                api_total=_api_total(), cached_events=cached, version="1.0.0")


def event_count() -> int:
    with _lock:
        return _c().execute("SELECT COUNT(*) c FROM event").fetchone()["c"]

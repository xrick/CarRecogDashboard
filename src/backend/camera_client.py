"""
中性/Dahua ANPR + face camera HTTP client (中性简体 HTTP API V3.87).

Endpoints used (only what the 工地看板 needs):
* §3.4   HTTP Digest auth (RFC 7616) — via requests HTTPDigestAuth
* §4.6.39 GET /cgi-bin/magicBox.cgi?action=getSystemInfo        (smoke test)
* §4.9.17 GET /cgi-bin/eventManager.cgi?action=attach&codes=[…] (live events,
          multipart/x-mixed-replace, parts `Code=…;action=…;index=…;data={JSON}`;
          codes TrafficJunction §10.1.1 / FaceRecognition §9.2.16). **PRIMARY** —
          verified on real XC-204BLPR @192.168.0.10 (HTTP 200 + Heartbeat).
* §4.4.3  GET /cgi-bin/snapManager.cgi?action=attachFileProc    (legacy, kept
          for models that support it; NOT implemented on XC-204BLPR — the
          connection hangs with no response, hence eventManager is primary)
* §4.4.2  GET /cgi-bin/snapshot.cgi                              (still image;
          eventManager.attach carries no inline jpeg, so snapshots are pulled
          here per event, best-effort)
* §10.3.4 GET /cgi-bin/recordFinder.cgi?action=find&name=TrafficRedList
          /TrafficBlackList  (allow/deny list; primary, verified 200 on .10)
* §10.7.8 POST /cgi-bin/api/VehicleRegisterDB/startFind|doFind|stopFind
          (fallback when recordFinder not implemented — XC-204BLPR returns 400,
          so this path is rarely usable on that model; primary works anyway)
* §4.10.19 GET /cgi-bin/loadfile.cgi?action=downPicByTime  (history search:
          bulk-download traffic snapshots by time range. Returns multipart with
          interleaved JSON metadata + JPEG parts; one HTTP request yields all
          captures in the window. Backs the "歷史車牌查詢" dashboard feature.)

Conventions match the repo (tests/demo2_writelist.py): Session + HTTPDigestAuth,
verify=False for self-signed HTTPS, key=value response parsing.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, Iterator, Optional

import requests
import urllib3
from requests.auth import HTTPDigestAuth

from .config import CameraConfig

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_KV_TOKEN = re.compile(r"([^.\[\]=]+)|\[(\d+)\]")


def parse_kv(text: str) -> dict[str, Any]:
    """Parse Dahua `key=value` text (incl. nested `records[0].PlateNumber=..`).
    Same algorithm as tests/demo2_writelist.py::_parse_kv."""
    root: dict[str, Any] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or "=" not in line or line.startswith(("#", "--")):
            continue
        key, _, val = line.partition("=")
        tokens: list[tuple[str, Any]] = []
        for m in _KV_TOKEN.finditer(key.strip()):
            name, idx = m.group(1), m.group(2)
            tokens.append(("k", name) if name is not None else ("i", int(idx)))
        if not tokens:
            continue
        cur: Any = root
        for i, (kind, t) in enumerate(tokens):
            is_last = i == len(tokens) - 1
            nxt = None if is_last else tokens[i + 1][0]
            if kind == "k":
                if is_last:
                    cur[t] = val.strip()
                else:
                    if t not in cur or not isinstance(cur[t], (list, dict)):
                        cur[t] = [] if nxt == "i" else {}
                    cur = cur[t]
            else:
                while len(cur) <= t:
                    cur.append({} if nxt == "k" else (None if is_last else []))
                if is_last:
                    cur[t] = val.strip()
                else:
                    if not isinstance(cur[t], (list, dict)):
                        cur[t] = {} if nxt == "k" else []
                    cur = cur[t]
    return root


_EM_HEAD = re.compile(
    r"Code=(?P<code>[^;]+);\s*[Aa]ction=(?P<action>[^;]+);"
    r"\s*[Ii]ndex=(?P<index>[^;]+)(?:;\s*data=(?P<data>.*))?",
    re.S)


def parse_eventmanager_event(text: str) -> Optional[dict]:
    """Parse one eventManager.attach part body (spec §4.9.17 / §10.2.1):

        Code=TrafficJunction;action=Start;index=0;data={ …JSON… }

    Returns {code, action, index, data(dict)} or None. ``data`` JSON may span
    multiple lines; if it is absent or not JSON it degrades to {} (with the
    raw text kept under ``_raw`` so a real event can calibrate the schema).
    """
    m = _EM_HEAD.search(text.strip())
    if not m:
        return None
    raw = (m.group("data") or "").strip()
    data: dict = {}
    if raw:
        try:
            parsed = json.loads(raw)
            data = parsed if isinstance(parsed, dict) else {"value": parsed}
        except (ValueError, TypeError):
            # some firmware use key=value instead of JSON in data=
            kv = parse_kv(raw)
            data = kv if kv else {"_raw": raw[:2000]}
    return {
        "code": m.group("code").strip(),
        "action": m.group("action").strip(),
        "index": m.group("index").strip(),
        "data": data,
    }


class CameraError(RuntimeError):
    pass


@dataclass
class _Part:
    content_type: str
    body: bytes


@dataclass
class HistoricalCapture:
    """One ANPR snapshot recovered from §4.10.19 downPicByTime.
    ``utc`` is epoch seconds; ``utcms`` is the millisecond offset
    (spec §4.10.19 keeps them separate). Combine via utc + utcms/1000."""
    plate: str
    speed: int                     # km/h
    utc: int                       # epoch seconds
    utcms: int                     # ms offset within the second (0-999)
    address: str
    jpeg: bytes


@dataclass
class PlateListResult:
    """Outcome of one allow/deny-list fetch. Lets the ingest layer apply the
    D4 decision matrix: ok+plates -> replace; ok+empty (found=0) -> keep;
    not ok -> keep (spec: DESIGN_plate_list_persistence.md §2)."""
    ok: bool                       # True only on HTTP 2xx + parsed (incl found=0)
    plates: set                    # plate strings (may be empty when ok)
    http_status: Optional[int] = None
    reason: str = ""               # failure detail (log / alert)


class CameraClient:
    def __init__(self, cfg: CameraConfig):
        self.cfg = cfg
        self.s = requests.Session()
        self.s.auth = HTTPDigestAuth(cfg.username, cfg.password)
        self.s.verify = False  # ANPR cams ship self-signed certs (CLAUDE.md)

    # ---- smoke test (§4.6.39) ------------------------------------------
    def get_system_info(self) -> dict[str, str]:
        r = self.s.get(f"{self.cfg.base_url}/cgi-bin/magicBox.cgi",
                        params={"action": "getSystemInfo"},
                        timeout=self.cfg.timeout)
        if r.status_code == 401:
            raise CameraError("認證失敗 (401)：帳號/密碼錯誤")
        r.raise_for_status()
        return parse_kv(r.text)

    # ---- allow / deny list (§10.3.4, fallback §10.7.8) -----------------
    def find_plate_list(self, name: str) -> PlateListResult:
        """name = 'TrafficRedList' (白) | 'TrafficBlackList' (黑).

        Returns a PlateListResult so the caller can tell apart
        success-with-plates / success-but-empty (found=0) / failure — the
        three branches of the D4 decision matrix. ``found=N`` with no
        ``records`` (verified real behaviour on XC-204BLPR @.10) is a
        legitimate ok+empty result, NOT a failure."""
        try:
            r = self.s.get(f"{self.cfg.base_url}/cgi-bin/recordFinder.cgi",
                            params={"action": "find", "name": name,
                                    "count": 1024},
                            timeout=self.cfg.timeout)
            if r.status_code < 400:
                data = parse_kv(r.text)
                recs = data.get("records", []) or []
                plates = {rec.get("PlateNumber", "").strip()
                          for rec in recs if rec.get("PlateNumber")}
                return PlateListResult(ok=True, plates=plates,
                                       http_status=r.status_code)
            # recordFinder unsupported on this model -> §10.7 fallback
            fb = self._vehicle_register_plates()
            if fb:
                return PlateListResult(ok=True, plates=fb,
                                       http_status=r.status_code,
                                       reason="VehicleRegisterDB fallback")
            return PlateListResult(ok=False, plates=set(),
                                   http_status=r.status_code,
                                   reason=f"recordFinder HTTP {r.status_code}")
        except requests.RequestException as e:
            return PlateListResult(ok=False, plates=set(), http_status=None,
                                   reason=f"{type(e).__name__}: {str(e)[:120]}")

    def _vehicle_register_plates(self) -> set[str]:
        """§10.7 VehicleRegisterDB fallback: findGroup -> startFind/doFind."""
        plates: set[str] = set()
        base = f"{self.cfg.base_url}/cgi-bin/api/VehicleRegisterDB"
        try:
            g = self.s.post(f"{base}/findGroup", json={"groupID": ""},
                            timeout=self.cfg.timeout)
            if g.status_code >= 400:
                return plates
            groups = (g.json() or {}).get("groups", []) or \
                (g.json() or {}).get("Groups", [])
            for grp in groups:
                gid = grp.get("groupID") or grp.get("GroupID")
                if not gid:
                    continue
                sf = self.s.post(f"{base}/startFind",
                                 json={"vehicle": {"GroupID": gid}},
                                 timeout=self.cfg.timeout)
                if sf.status_code >= 400:
                    continue
                token = (sf.json() or {}).get("token")
                total = (sf.json() or {}).get("totalCount", 0)
                got = 0
                while token is not None and got < total:
                    df = self.s.post(
                        f"{base}/doFind",
                        json={"condition": {"token": token,
                                            "beginNumber": got, "count": 50}},
                        timeout=self.cfg.timeout)
                    if df.status_code >= 400:
                        break
                    cands = ((df.json() or {}).get("results", {})
                             .get("candidates", []))
                    if not cands:
                        break
                    for c in cands:
                        pn = (c.get("Vehicle", {}) or {}).get("PlateNumber")
                        if pn:
                            plates.add(pn.strip())
                    got += len(cands)
                self.s.post(f"{base}/stopFind", json={"token": token},
                            timeout=self.cfg.timeout)
        except (requests.RequestException, ValueError):
            pass
        return plates

    # ---- shared multipart/x-mixed-replace reader -----------------------
    def _iter_parts(self, url: str) -> Iterator[_Part]:
        """Yield decoded multipart parts from a streaming endpoint.
        Reconnect/backoff is the caller's job (ingest layer)."""
        with self.s.get(url, stream=True, timeout=(self.cfg.timeout, None)) as r:
            r.raise_for_status()
            ctype = r.headers.get("Content-Type", "")
            m = re.search(r"boundary=([^;]+)", ctype)
            boundary = ("--" + m.group(1).strip()).encode() if m else b"--myboundary"
            buf = b""
            for chunk in r.iter_content(chunk_size=4096):
                if not chunk:
                    continue
                buf += chunk
                while True:
                    i = buf.find(boundary)
                    if i < 0:
                        break
                    seg, buf = buf[:i], buf[i + len(boundary):]
                    part = self._decode_part(seg)
                    if part is not None:
                        yield part

    # ---- PRIMARY live event stream (§4.9.17 eventManager.attach) --------
    def stream_events(self) -> Iterator[dict]:
        """Yield raw event dicts {code, action, index, data} from
        eventManager.cgi?action=attach. Heartbeats are swallowed here.

        Verified channel on XC-204BLPR @192.168.0.10 (attachFileProc hangs on
        that model). Part body format (spec §4.9.17 / §10.2.1):
            Code=TrafficJunction;action=Start;index=0;data={ …JSON… }
        """
        codes = ",".join(self.cfg.event_codes)
        url = (f"{self.cfg.base_url}/cgi-bin/eventManager.cgi"
               f"?action=attach&codes=[{codes}]&heartbeat=5")
        for part in self._iter_parts(url):
            body = part.body.strip()
            if not body or body == b"Heartbeat":
                continue
            ev = parse_eventmanager_event(body.decode("utf-8", "ignore"))
            if ev is not None:
                yield ev

    # ---- legacy event+snapshot stream (§4.4.3) -------------------------
    def stream_parts(self) -> Iterator[_Part]:
        """snapManager.attachFileProc — kept for models that implement it.
        NOT used by default: XC-204BLPR does not support it (connection
        hangs). ``stream_events`` (eventManager.attach) is primary."""
        codes = ",".join(self.cfg.event_codes)
        url = (f"{self.cfg.base_url}/cgi-bin/snapManager.cgi"
               f"?action=attachFileProc&channel={self.cfg.channel}"
               f"&heartbeat=5&Flags[0]=Event&Events=[{codes}]")
        yield from self._iter_parts(url)

    @staticmethod
    def _decode_part(seg: bytes) -> Optional[_Part]:
        seg = seg.strip(b"\r\n-")
        if not seg or seg == b"--":
            return None
        if b"\r\n\r\n" in seg:
            head, _, body = seg.partition(b"\r\n\r\n")
        elif b"\n\n" in seg:
            head, _, body = seg.partition(b"\n\n")
        else:
            head, body = b"", seg
        ct = "text/plain"
        for line in head.split(b"\n"):
            if line.lower().startswith(b"content-type:"):
                ct = line.split(b":", 1)[1].strip().decode("latin-1")
        return _Part(content_type=ct, body=body)

    # ---- history search (§4.10.19) -------------------------------------
    def download_traffic_pics_by_time(
        self, start: str, end: str, *,
        channel: Optional[int] = None, types: str = "jpg", flags: str = "*",
    ) -> Iterator["HistoricalCapture"]:
        """§4.10.19 按时间范围下载交通抓拍图片文件.

        One HTTP request fetches all ANPR snapshots in [start, end] from the
        camera/NVR (主場是 NVR — single IPC SD card 通常只有近期). Each
        capture is delivered as **a pair of multipart parts**: a JSON metadata
        part (plate / speed / UTC / address) followed by the JPEG binary.

        Time format: ``YYYY-MM-DD HH:MM:SS`` (local) — the spec also accepts
        ``startTimeRealUTC=YYYY-MM-DDTHH:MM:SSZ`` but we keep the simpler
        local-time form to match the rest of the codebase. ``channel`` default
        is the configured channel; pass ``-1`` for all channels (NVR).

        Yields ``HistoricalCapture(plate, speed, utc, utcms, address, jpeg)``
        — caller is responsible for persisting JPEGs and surfacing metadata.
        Network failures raise ``CameraError`` (callers should treat as
        empty-result, mirroring D4 list semantics)."""
        url = (f"{self.cfg.base_url}/cgi-bin/loadfile.cgi"
               f"?action=downPicByTime"
               f"&channel={channel if channel is not None else self.cfg.channel}"
               f"&startTime={start}&endTime={end}"
               f"&Types={types}&Flags={flags}")
        pending: Optional[dict] = None
        try:
            for part in self._iter_parts(url):
                ct = part.content_type.lower()
                body = part.body
                if "json" in ct:
                    try:
                        pending = json.loads(body)
                    except (ValueError, TypeError):
                        pending = None
                elif ("jpeg" in ct or "jpg" in ct) and pending is not None:
                    info = (pending.get("filedata") or {}).get("info") or {}
                    yield HistoricalCapture(
                        plate=str(info.get("plateNum", "")).strip(),
                        speed=int(info.get("Speed") or 0),
                        utc=int(info.get("UTC") or 0),
                        utcms=int(info.get("UTCMS") or 0),
                        address=str(info.get("address", "")).strip(),
                        jpeg=body,
                    )
                    pending = None
        except requests.RequestException as e:
            raise CameraError(f"§4.10.19 downPicByTime failed: "
                              f"{type(e).__name__}: {str(e)[:120]}")

    # ---- still image (§4.4.2) ------------------------------------------
    def snapshot(self, channel: Optional[int] = None) -> bytes:
        r = self.s.get(f"{self.cfg.base_url}/cgi-bin/snapshot.cgi",
                        params={"channel": channel or self.cfg.channel,
                                "type": 0},
                        timeout=self.cfg.timeout)
        r.raise_for_status()
        return r.content


# --------------------------------------------------------------------------- #
# Normalisers: raw camera event -> board Event dict (matches models.Event)
# --------------------------------------------------------------------------- #
def _direction(role: str) -> str:
    return "OUT" if role == "exit" else "IN"


def normalize_traffic(raw: dict, *, site_id: str, site_name: str,
                      role: str, redlist: set[str], blacklist: set[str],
                      now_iso: str, now_hms: str,
                      list_state: str = "fresh",
                      snapshot_url: Optional[str] = None) -> Optional[dict]:
    """TrafficJunction (§10.1.1) Events[i] -> board Event.

    ``list_state`` (fresh|stale|unsynced) drives the unmatched-plate label:
    when the host's lists were never synced (unsynced, e.g. fresh deploy /
    camera unreachable) an unknown plate is 'pending' 名單未同步（系統安裝中）,
    NOT 'stranger' (FR-10 / D5)."""
    tc = raw.get("TrafficCar", {}) or {}
    veh = raw.get("Vehicle", {}) or {}
    plate = (tc.get("PlateNumber") or "").strip()
    if not plate:
        return None
    if plate in blacklist:
        status, stype = "黑名單", "blacklist"
        access = "拒絕"
    elif plate in redlist:
        status, stype = "白名單", "whitelist"
        access = "閘門已開啟"
    elif list_state == "unsynced":
        status, stype = "名單未同步", "pending"
        access = "系統安裝中"
    else:
        status, stype = "陌生", "stranger"
        access = "人工確認"
    brand = " ".join(x for x in (veh.get("Text"), veh.get("SubText")) if x)
    detail = brand or tc.get("VehicleColor", "") or "車輛"
    direction = _direction(role)
    return dict(
        event_id=f"tj_{site_id}_{tc.get('RecNo') or uuid.uuid4().hex[:10]}",
        site_id=site_id, site_name=site_name, event_type="vehicle",
        direction=direction, event_ts=now_iso, event_time=now_hms,
        display_name=plate, secondary_id=None,
        contractor=tc.get("Owner", "") or "—", detail=detail,
        status=status, status_type=stype,
        snapshot_url=snapshot_url, plate_snapshot_url=snapshot_url,
        access_result=access, confidence=None,
        why=f"車牌辨識：{plate} · 比對名單",
        source="ALPR · 中性 HTTP API §10.1.1")


def normalize_face(raw: dict, *, site_id: str, site_name: str, role: str,
                   now_iso: str, now_hms: str,
                   snapshot_url: Optional[str] = None) -> Optional[dict]:
    """FaceRecognition (§9.2.16) Events[i] -> board Event."""
    cands = raw.get("Candidates", []) or []
    top = cands[0] if cands else {}
    person = (top.get("Person", {}) or {})
    name = person.get("Name") or ""
    sim = top.get("Similarity")
    try:
        conf = (float(sim) / 100.0) if sim not in (None, "") else None
    except (TypeError, ValueError):
        conf = None
    if name:
        status, stype, access = ("通行", "pass", "通行")
    else:
        name, status, stype, access = ("未知人員", "陌生", "stranger", "人工確認")
    direction = _direction(role)
    return dict(
        event_id=f"fr_{site_id}_{raw.get('UID') or uuid.uuid4().hex[:10]}",
        site_id=site_id, site_name=site_name, event_type="personnel",
        direction=direction, event_ts=now_iso, event_time=now_hms,
        display_name=name, secondary_id=person.get("ID") or None,
        contractor=person.get("GroupID", "") or "—",
        detail="人臉辨識" + (f" · 相似度 {sim}" if sim else ""),
        status=("離場" if direction == "OUT" and stype == "pass" else status),
        status_type=stype,
        snapshot_url=snapshot_url, plate_snapshot_url=None,
        access_result=access, confidence=conf,
        why=("人臉比對命中" if conf else "人臉未命中名單"),
        source="FaceID · 中性 HTTP API §9.2.16")

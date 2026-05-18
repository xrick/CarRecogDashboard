"""
In-memory mock data + a live event simulator.

The real deployment will replace :class:`DataStore` with calls to the 車牌管理
平台 / 人臉辨識平台. Until then this module fabricates a believable stream so
the board (and the auto-rotation / flash-card UX) can be exercised end-to-end.
"""
from __future__ import annotations

import asyncio
import random
from collections import deque
from datetime import datetime
from typing import Optional

from .models import (
    Alert,
    AlertCost,
    ApiState,
    CopilotSummary,
    Direction,
    Event,
    EventType,
    HourlyForecastPoint,
    HourlyTrendPoint,
    OverviewKPI,
    SiteStatus,
    SiteSummary,
    SitesSummaryResponse,
    StatusType,
    SystemStatus,
)

CURRENT_HOUR = 14  # the demo pins "now" at 14:00 for stable screenshots

SITES = [
    {"id": "A01", "name": "A01 北側基地",   "people": 84,  "vehicle": 14, "status": "normal"},
    {"id": "A02", "name": "A02 東門工區",   "people": 42,  "vehicle": 7,  "status": "normal"},
    {"id": "A03", "name": "A03 機電棟工區", "people": 108, "vehicle": 18, "status": "alert"},
    {"id": "A04", "name": "A04 地下層",     "people": 39,  "vehicle": 4,  "status": "normal"},
    {"id": "B01", "name": "B01 高塔區",     "people": 61,  "vehicle": 9,  "status": "normal"},
    {"id": "B02", "name": "B02 材料場",     "people": 25,  "vehicle": 5,  "status": "normal"},
    {"id": "B03", "name": "B03 臨時道路",   "people": 74,  "vehicle": 12, "status": "normal"},
    {"id": "B04", "name": "B04 西側門",     "people": 33,  "vehicle": 6,  "status": "delay"},
    {"id": "C01", "name": "C01 宿舍區",     "people": 92,  "vehicle": 16, "status": "normal"},
    {"id": "C02", "name": "C02 吊車區",     "people": 45,  "vehicle": 8,  "status": "normal"},
    {"id": "C03", "name": "C03 倉儲區",     "people": 67,  "vehicle": 11, "status": "normal"},
    {"id": "C04", "name": "C04 試運轉區",   "people": 57,  "vehicle": 10, "status": "normal"},
]
SITE_BY_ID = {s["id"]: s for s in SITES}

# spec §6 — 0..23h people/vehicle in/out. Hours after CURRENT_HOUR are 0.
_HOURLY_TREND = [
    (2, 1, 0, 0), (1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 0, 0),
    (0, 0, 1, 0), (3, 0, 2, 0), (18, 2, 5, 1), (42, 5, 9, 2),
    (28, 8, 7, 3), (19, 12, 5, 4), (14, 18, 4, 5), (11, 24, 3, 6),
    (8, 22, 2, 4), (22, 14, 6, 3), (18, 16, 5, 4), (0, 0, 0, 0),
    (0, 0, 0, 0), (0, 0, 0, 0), (0, 0, 0, 0), (0, 0, 0, 0),
    (0, 0, 0, 0), (0, 0, 0, 0), (0, 0, 0, 0), (0, 0, 0, 0),
]
_FORECAST = [  # spec ch.13 — dashed forecast + confidence cone
    ("15", 12, 18, 7), ("16", 8, 14, 3), ("17", 24, 34, 14), ("18", 6, 12, 1),
]

SITE_KPI = dict(people_in=186, people_out=142, people_inside=44,
                vehicle_in=51, vehicle_out=38, vehicle_inside=13,
                expired_cert=5, stranger_plate=4)

_SEED_EVENTS = [
    dict(event_type="vehicle", direction="IN", time="14:32:18", name="ABC-5288", sid=None,
         site="A03", contractor="大榮土木", detail="砂石車", status="白名單", st="whitelist",
         access="閘門已開啟", conf=0.98, why="車牌完整辨識 · 比對白名單命中", src="ALPR v2.3 · 白名單 #1284"),
    dict(event_type="personnel", direction="IN", time="14:31:42", name="王O明", sid="E-1029",
         site="B01", contractor="正興機電", detail="建築工 · 高空作業證有效", status="通行", st="pass",
         access="通行", conf=0.94, why="人臉與證件照相符 · 證照效期至 2026/08", src="FaceID v1.8 · 工安系統"),
    dict(event_type="vehicle", direction="OUT", time="14:30:55", name="KLM-0921", sid=None,
         site="C02", contractor="隆泰工程", detail="小貨車", status="白名單", st="whitelist",
         access="閘門已開啟", conf=0.96, why="車牌完整辨識 · 同車已於 09:14 進場", src="ALPR v2.3 · 進出事件配對"),
    dict(event_type="vehicle", direction="IN", time="14:29:11", name="UNKNOWN-018", sid=None,
         site="A02", contractor="陌生車牌", detail="待確認", status="陌生", st="stranger",
         access="人工確認", conf=0.71, why="車牌辨識成功但白名單無此車 · 第 18 次出現", src="ALPR v2.3 · 白名單未命中"),
    dict(event_type="personnel", direction="IN", time="14:28:47", name="李O華", sid="E-0981",
         site="A03", contractor="隆泰工程", detail="電焊工 · 證照過期", status="告警", st="alert",
         access="人工確認", conf=0.91, why="人臉相符 · 但電焊作業證 2026/03 已過期 71 天", src="FaceID v1.8 · 證照資料庫"),
    dict(event_type="personnel", direction="OUT", time="14:27:33", name="陳O德", sid="E-0442",
         site="A03", contractor="宏達水電", detail="一般工安證有效", status="離場", st="pass",
         access="通行", conf=0.93, why="人臉相符 · 同人 08:02 進場", src="FaceID v1.8"),
    dict(event_type="vehicle", direction="IN", time="14:26:08", name="XYZ-3344", sid=None,
         site="B03", contractor="建興營造", detail="吊卡", status="白名單", st="whitelist",
         access="閘門已開啟", conf=0.97, why="車牌完整辨識 · 比對白名單命中", src="ALPR v2.3 · 白名單 #0942"),
    dict(event_type="personnel", direction="IN", time="14:25:21", name="張O芬", sid="E-1138",
         site="C01", contractor="正興機電", detail="工安督導 · 證照有效", status="通行", st="pass",
         access="通行", conf=0.95, why="人臉相符 · 工安督導證效期至 2027/01", src="FaceID v1.8"),
]

_ALERTS = [
    Alert(id="a001", type="blacklist", target="ZZZ-7777", detail="不得進入 · 已通知警衛室",
          site="A03", confidence=0.99, why="車牌字元完全相符 · 列入黑名單 31 天 (歷史違規)",
          cost=AlertCost(fp="誤攔正常車輛 1 次 · 影響工程進度約 5 分鐘",
                         fn="違規車輛進入工地 · 安全風險高"),
          suggestions=["通知保全在閘門攔截", "通報工地主任", "保留進入時段影像"],
          occurrence="24H 內首次", occurrence_count=1),
    Alert(id="a002", type="expired", target="李O華 / E-0981", detail="電焊作業證過期 · 需人工確認",
          site="A03", confidence=0.91, why="人臉相符 · 電焊作業證 2026/03 已過期 71 天",
          cost=AlertCost(fp="誤攔合格工人 · 中斷作業約 10 分鐘",
                         fn="無證上崗 · 法規違規與安全風險"),
          suggestions=["請工人補件或暫停電焊作業", "通知工安督導", "聯繫承包商更新證照"],
          occurrence="7 日內第 3 次", occurrence_count=3),
    Alert(id="a003", type="stranger", target="UNKNOWN-019", detail="已自動建檔 · 待管理平台確認",
          site="A02", confidence=0.73, why="車牌完整辨識 · 白名單未命中 · 出現少於 5 次",
          cost=AlertCost(fp="誤判可能影響供應商 (例如同集團車隊)",
                         fn="陌生車輛長期未驗證"),
          suggestions=["請警衛詢問來訪事由", "若為合作廠商,加入白名單"],
          occurrence="24H 內第 1 次", occurrence_count=1),
    Alert(id="a004", type="api_delay", target="人臉 API", detail="最後事件時間 14:22:01 · 已超過 5 分鐘",
          site="B04", confidence=None, why="心跳訊號中斷 · 顯示為 staleness 異常 (非 AI 推論)",
          cost=AlertCost(fp="誤判導致工程師白跑一趟",
                         fn="系統真的離線 · 進出未被記錄"),
          suggestions=["檢查 API 服務狀態", "切換到備援辨識通道", "通知 IT 排查"],
          occurrence="7 日內第 2 次", occurrence_count=2),
]

_COPILOT = CopilotSummary(
    headline="AI 副駕駛 · 即時摘要",
    body=("過去 1 小時偵測 4 件異常,集中於 A03 機電棟工區(2 件)。"
          "關鍵風險:電焊工 李O華 證照已過期 71 天且 7 日內第 3 次嘗試進場;"
          "黑名單車牌 ZZZ-7777 首次出現。建議優先處理上述兩件,並排查 B04 工區人臉 API 延遲。"),
    sources="過去 60 分鐘所有事件 + 證照資料庫 + 黑名單",
    model="GPT-4 + 內部規則引擎",
    generated_at="",
)

# pools used by the live simulator to fabricate believable new events
_V_CONTRACTORS = ["大榮土木", "隆泰工程", "建興營造", "宏達水電", "正興機電"]
_V_TYPES = ["砂石車", "卡車", "大卡車", "吊卡", "小貨車", "轎車"]
_P_NAMES = ["王O明", "李O華", "陳O德", "張O芬", "林O傑", "黃O雅", "吳O峰"]
_P_ROLES = ["建築工 · 一般工安證有效", "電焊工 · 證照有效", "高空作業 · 證照有效",
            "工安督導 · 證照有效", "電焊工 · 證照過期"]


def _now_hms() -> str:
    return datetime.now().strftime("%H:%M:%S")


class DataStore:
    """Holds dashboard state and fans new events out to SSE subscribers."""

    def __init__(self) -> None:
        self.events: deque[Event] = deque(maxlen=60)
        for i, s in enumerate(_SEED_EVENTS):
            self.events.appendleft(self._mk_event(f"e{i:03d}", s))
        self._subscribers: list[asyncio.Queue] = []
        self._counter = len(_SEED_EVENTS)
        self._unknown_seq = 19
        self._sim_task: Optional[asyncio.Task] = None

    # ---- builders -------------------------------------------------------
    @staticmethod
    def _mk_event(eid: str, s: dict) -> Event:
        site = SITE_BY_ID.get(s["site"], {"name": s["site"]})
        return Event(
            event_id=eid, site_id=s["site"], site_name=site.get("name", s["site"]),
            event_type=EventType(s["event_type"]), direction=Direction(s["direction"]),
            event_time=s["time"], display_name=s["name"], secondary_id=s.get("sid"),
            contractor=s["contractor"], detail=s.get("detail", ""), status=s["status"],
            status_type=StatusType("pass" if s["st"] == "pass" else s["st"]),
            access_result=s.get("access", ""), confidence=s.get("conf"),
            why=s.get("why"), source=s.get("src"),
            snapshot_url=None, plate_snapshot_url=None,
        )

    def site_summary(self, site_id: str) -> SiteSummary:
        s = SITE_BY_ID[site_id]
        k = SITE_KPI
        alerts = sum(1 for e in self.events
                     if e.site_id == site_id and e.status_type in
                     (StatusType.alert, StatusType.blacklist))
        return SiteSummary(
            site_id=site_id, site_name=s["name"],
            people_in=k["people_in"], people_out=k["people_out"],
            people_inside=s["people"],
            vehicle_in=k["vehicle_in"], vehicle_out=k["vehicle_out"],
            vehicle_inside=s["vehicle"],
            alert_count=alerts, last_update_time=_now_hms(),
            status=SiteStatus(s["status"]),
        )

    def overview(self) -> OverviewKPI:
        return OverviewKPI(
            people_in=1286, people_out=1052,
            people_inside=sum(s["people"] for s in SITES),
            vehicle_in=342, vehicle_out=288,
            vehicle_inside=sum(s["vehicle"] for s in SITES),
            alert_count=7, blacklist=2, expired_cert=5, stranger_plate=4,
            api_online=11, api_total=12,
        )

    def sites_summary(self) -> SitesSummaryResponse:
        return SitesSummaryResponse(
            overview=self.overview(),
            sites=[self.site_summary(s["id"]) for s in SITES],
            last_update_time=_now_hms(),
        )

    def hourly(self, site_id: str):
        scale = 1.0
        if site_id != "ALL":
            base = SITE_BY_ID[site_id]["people"]
            scale = max(0.3, min(2.0, base / 70.0))
        trend = []
        for h, (pi, po, vi, vo) in enumerate(_HOURLY_TREND):
            trend.append(HourlyTrendPoint(
                hour=f"{h:02d}",
                people_in=int(pi * scale), people_out=int(po * scale),
                vehicle_in=vi, vehicle_out=vo))
        forecast = [HourlyForecastPoint(
            hour=hh, people_in_forecast=int(f * scale),
            people_in_upper=int(u * scale), people_in_lower=int(lo * scale))
            for hh, f, u, lo in _FORECAST]
        name = SITE_BY_ID[site_id]["name"] if site_id != "ALL" else "全部工地"
        return site_id, name, CURRENT_HOUR, trend, forecast

    def system_status(self) -> SystemStatus:
        return SystemStatus(
            plate_api_status=ApiState.normal, face_api_status=ApiState.normal,
            last_success_time=_now_hms(), latency_seconds=2, error_message=None,
            api_online=2, api_total=2, cached_events=0, version="1.0.0",
        )

    def alerts(self, site_id: str) -> list[Alert]:
        if site_id == "ALL":
            return list(_ALERTS)
        return [a for a in _ALERTS if a.site == site_id] or list(_ALERTS)

    def copilot(self) -> CopilotSummary:
        c = _COPILOT.model_copy()
        c.generated_at = datetime.now().strftime("%H:%M")
        return c

    def latest_events(self, site_id: str, limit: int = 20) -> list[Event]:
        items = list(self.events)
        if site_id != "ALL":
            items = [e for e in items if e.site_id == site_id]
        return items[:limit]

    # ---- live simulator -------------------------------------------------
    def _fabricate(self) -> Event:
        self._counter += 1
        eid = f"e{self._counter:03d}_{int(datetime.now().timestamp())}"
        site = random.choice(SITES)
        direction = random.choice(["IN", "OUT"])
        roll = random.random()
        if random.random() < 0.5:  # vehicle
            if roll < 0.12:
                self._unknown_seq += 1
                name, status, st = f"UNKNOWN-{self._unknown_seq:03d}", "陌生", "stranger"
                contractor, conf = "陌生車牌", round(random.uniform(0.62, 0.78), 2)
                why, access = "車牌辨識成功但白名單無此車", "人工確認"
            elif roll < 0.18:
                name = random.choice(["ZZZ-7777", "QQ-1111"])
                status, st, contractor = "黑名單", "blacklist", "黑名單車輛"
                conf, why, access = 0.99, "車牌字元完全相符 · 列入黑名單", "拒絕"
            else:
                name = f"{random.choice('ABCDEFGHJKLM')}{random.choice('NPQRSTUVWXYZ')}{random.choice('ABCDEFGH')}-{random.randint(1000,9999)}"
                status, st, contractor = "白名單", "whitelist", random.choice(_V_CONTRACTORS)
                conf, why, access = round(random.uniform(0.92, 0.99), 2), "車牌完整辨識 · 比對白名單命中", "閘門已開啟"
            s = dict(event_type="vehicle", direction=direction, time=_now_hms(),
                     name=name, sid=None, site=site["id"], contractor=contractor,
                     detail=random.choice(_V_TYPES), status=status, st=st,
                     access=access, conf=conf, why=why, src="ALPR v2.3")
        else:  # personnel
            role = random.choice(_P_ROLES)
            expired = "過期" in role
            s = dict(
                event_type="personnel", direction=direction, time=_now_hms(),
                name=random.choice(_P_NAMES), sid=f"E-{random.randint(1000,1999)}",
                site=site["id"], contractor=random.choice(_V_CONTRACTORS), detail=role,
                status="告警" if expired else ("離場" if direction == "OUT" else "通行"),
                st="alert" if expired else "pass",
                access="人工確認" if expired else "通行",
                conf=round(random.uniform(0.88, 0.97), 2),
                why="人臉相符 · 證照過期" if expired else "人臉與證件照相符",
                src="FaceID v1.8")
        return self._mk_event(eid, s)

    async def run_simulator(self, interval: float = 6.0) -> None:
        """Emit a new event every ``interval`` s (spec demo cadence)."""
        while True:
            await asyncio.sleep(interval)
            ev = self._fabricate()
            self.events.appendleft(ev)
            payload = ev.model_dump_json()
            for q in list(self._subscribers):
                try:
                    q.put_nowait(payload)
                except asyncio.QueueFull:
                    pass

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=20)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)


store = DataStore()

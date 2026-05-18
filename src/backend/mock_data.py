"""
Demo seed data + the live event SIMULATOR.

This is no longer the data store — persistence is src/backend/db.py and live
ingestion is src/backend/ingest.py. This module only:
  * seeds a fresh DB so the board is populated on first run, and
  * fabricates believable events when no real camera is configured
    (config.simulate) — driven through the SAME db + SSE pipeline as the
    camera path so behaviour is identical.
"""
from __future__ import annotations

import random
from datetime import date, datetime

from . import db

SITES = [
    {"id": "A01", "name": "A01 北側基地",   "status": "normal"},
    {"id": "A02", "name": "A02 東門工區",   "status": "normal"},
    {"id": "A03", "name": "A03 機電棟工區", "status": "alert"},
    {"id": "A04", "name": "A04 地下層",     "status": "normal"},
    {"id": "B01", "name": "B01 高塔區",     "status": "normal"},
    {"id": "B02", "name": "B02 材料場",     "status": "normal"},
    {"id": "B03", "name": "B03 臨時道路",   "status": "normal"},
    {"id": "B04", "name": "B04 西側門",     "status": "delay"},
    {"id": "C01", "name": "C01 宿舍區",     "status": "normal"},
    {"id": "C02", "name": "C02 吊車區",     "status": "normal"},
    {"id": "C03", "name": "C03 倉儲區",     "status": "normal"},
    {"id": "C04", "name": "C04 試運轉區",   "status": "normal"},
]
SITE_IDS = [s["id"] for s in SITES]
SITE_NAME = {s["id"]: s["name"] for s in SITES}

_SEED = [
    ("vehicle", "IN", "08:32:18", "ABC-5288", None, "A03", "大榮土木", "砂石車",
     "白名單", "whitelist", "閘門已開啟", 0.98, "車牌完整辨識 · 比對白名單命中",
     "ALPR v2.3 · 白名單 #1284"),
    ("personnel", "IN", "08:31:42", "王O明", "E-1029", "B01", "正興機電",
     "建築工 · 高空作業證有效", "通行", "pass", "通行", 0.94,
     "人臉與證件照相符 · 證照效期至 2026/08", "FaceID v1.8"),
    ("vehicle", "OUT", "09:30:55", "KLM-0921", None, "C02", "隆泰工程", "小貨車",
     "白名單", "whitelist", "閘門已開啟", 0.96, "車牌完整辨識 · 同車已於 09:14 進場",
     "ALPR v2.3"),
    ("vehicle", "IN", "10:29:11", "UNKNOWN-018", None, "A02", "陌生車牌", "待確認",
     "陌生", "stranger", "人工確認", 0.71, "車牌辨識成功但白名單無此車",
     "ALPR v2.3 · 白名單未命中"),
    ("personnel", "IN", "11:28:47", "李O華", "E-0981", "A03", "隆泰工程",
     "電焊工 · 證照過期", "告警", "alert", "人工確認", 0.91,
     "人臉相符 · 電焊作業證 2026/03 已過期 71 天", "FaceID v1.8 · 證照資料庫"),
    ("personnel", "OUT", "12:27:33", "陳O德", "E-0442", "A03", "宏達水電",
     "一般工安證有效", "離場", "pass", "通行", 0.93, "人臉相符 · 同人 08:02 進場",
     "FaceID v1.8"),
    ("vehicle", "IN", "13:26:08", "XYZ-3344", None, "B03", "建興營造", "吊卡",
     "白名單", "whitelist", "閘門已開啟", 0.97, "車牌完整辨識 · 比對白名單命中",
     "ALPR v2.3 · 白名單 #0942"),
    ("personnel", "IN", "13:25:21", "張O芬", "E-1138", "C01", "正興機電",
     "工安督導 · 證照有效", "通行", "pass", "通行", 0.95,
     "人臉相符 · 工安督導證效期至 2027/01", "FaceID v1.8"),
]

_ALERTS = [
    dict(id="a001", type="blacklist", target="ZZZ-7777", detail="不得進入 · 已通知警衛室",
         site="A03", confidence=0.99, why="車牌字元完全相符 · 列入黑名單 31 天 (歷史違規)",
         cost={"fp": "誤攔正常車輛 1 次 · 影響工程進度約 5 分鐘",
               "fn": "違規車輛進入工地 · 安全風險高"},
         suggestions=["通知保全在閘門攔截", "通報工地主任", "保留進入時段影像"],
         occurrence="24H 內首次", occurrence_count=1),
    dict(id="a002", type="expired", target="李O華 / E-0981", detail="電焊作業證過期 · 需人工確認",
         site="A03", confidence=0.91, why="人臉相符 · 電焊作業證 2026/03 已過期 71 天",
         cost={"fp": "誤攔合格工人 · 中斷作業約 10 分鐘",
               "fn": "無證上崗 · 法規違規與安全風險"},
         suggestions=["請工人補件或暫停電焊作業", "通知工安督導", "聯繫承包商更新證照"],
         occurrence="7 日內第 3 次", occurrence_count=3),
    dict(id="a003", type="stranger", target="UNKNOWN-019", detail="已自動建檔 · 待管理平台確認",
         site="A02", confidence=0.73, why="車牌完整辨識 · 白名單未命中 · 出現少於 5 次",
         cost={"fp": "誤判可能影響供應商 (例如同集團車隊)", "fn": "陌生車輛長期未驗證"},
         suggestions=["請警衛詢問來訪事由", "若為合作廠商,加入白名單"],
         occurrence="24H 內第 1 次", occurrence_count=1),
    dict(id="a004", type="api_delay", target="人臉 API", detail="最後事件時間 14:22:01 · 已超過 5 分鐘",
         site="B04", confidence=None, why="心跳訊號中斷 · 顯示為 staleness 異常 (非 AI 推論)",
         cost={"fp": "誤判導致工程師白跑一趟", "fn": "系統真的離線 · 進出未被記錄"},
         suggestions=["檢查 API 服務狀態", "切換到備援辨識通道", "通知 IT 排查"],
         occurrence="7 日內第 2 次", occurrence_count=2),
]

_V_CONTRACTORS = ["大榮土木", "隆泰工程", "建興營造", "宏達水電", "正興機電"]
_V_TYPES = ["砂石車", "卡車", "大卡車", "吊卡", "小貨車", "轎車"]
_P_NAMES = ["王O明", "李O華", "陳O德", "張O芬", "林O傑", "黃O雅", "吳O峰"]
_P_ROLES = ["建築工 · 一般工安證有效", "電焊工 · 證照有效", "高空作業 · 證照有效",
            "工安督導 · 證照有效", "電焊工 · 證照過期"]


def _today_iso(hms: str) -> str:
    return f"{date.today().isoformat()} {hms}"


def seed_database() -> None:
    """Idempotent: sites + curated alerts/copilot + today's seed events."""
    for s in SITES:
        db.upsert_site(s["id"], s["name"], s["status"])
    for i, e in enumerate(_SEED):
        (etype, dirn, hms, name, sid, site, contr, det, st, stype,
         acc, conf, why, src) = e
        db.insert_event(dict(
            event_id=f"seed{i:03d}", site_id=site, site_name=SITE_NAME[site],
            event_type=etype, direction=dirn, event_ts=_today_iso(hms),
            event_time=hms, display_name=name, secondary_id=sid,
            contractor=contr, detail=det, status=st, status_type=stype,
            snapshot_url=None, plate_snapshot_url=None, access_result=acc,
            confidence=conf, why=why, source=src))
    for a in _ALERTS:
        db.insert_alert(a)
    db.set_copilot(None, dict(
        headline="AI 副駕駛 · 即時摘要",
        body=("過去 1 小時偵測 4 件異常,集中於 A03 機電棟工區(2 件)。"
              "關鍵風險:電焊工 李O華 證照已過期 71 天且 7 日內第 3 次嘗試進場;"
              "黑名單車牌 ZZZ-7777 首次出現。建議優先處理上述兩件,並排查 B04 工區人臉 API 延遲。"),
        sources="過去 60 分鐘所有事件 + 證照資料庫 + 黑名單",
        model="GPT-4 + 內部規則引擎", generated_at=datetime.now().strftime("%H:%M")))


class Simulator:
    """Fabricates one believable event per tick (used when no camera)."""

    def __init__(self) -> None:
        self._n = 1000
        self._unknown = 19

    def fabricate(self) -> dict:
        self._n += 1
        site = random.choice(SITES)
        now = datetime.now()
        iso, hms = now.strftime("%Y-%m-%d %H:%M:%S"), now.strftime("%H:%M:%S")
        eid = f"sim{self._n}_{int(now.timestamp())}"
        if random.random() < 0.5:
            roll = random.random()
            if roll < 0.12:
                self._unknown += 1
                name, status, st = f"UNKNOWN-{self._unknown:03d}", "陌生", "stranger"
                contr, conf, why, acc = "陌生車牌", round(random.uniform(.62, .78), 2), \
                    "車牌辨識成功但白名單無此車", "人工確認"
            elif roll < 0.18:
                name = random.choice(["ZZZ-7777", "QQ-1111"])
                status, st, contr = "黑名單", "blacklist", "黑名單車輛"
                conf, why, acc = 0.99, "車牌字元完全相符 · 列入黑名單", "拒絕"
            else:
                name = (f"{random.choice('ABCDEFGHJKLM')}"
                        f"{random.choice('NPQRSTUVWXYZ')}"
                        f"{random.choice('ABCDEFGH')}-{random.randint(1000, 9999)}")
                status, st, contr = "白名單", "whitelist", random.choice(_V_CONTRACTORS)
                conf, why, acc = round(random.uniform(.92, .99), 2), \
                    "車牌完整辨識 · 比對白名單命中", "閘門已開啟"
            return dict(
                event_id=eid, site_id=site["id"], site_name=site["name"],
                event_type="vehicle", direction=random.choice(["IN", "OUT"]),
                event_ts=iso, event_time=hms, display_name=name,
                secondary_id=None, contractor=contr,
                detail=random.choice(_V_TYPES), status=status, status_type=st,
                snapshot_url=None, plate_snapshot_url=None, access_result=acc,
                confidence=conf, why=why, source="ALPR v2.3 (模擬)")
        role = random.choice(_P_ROLES)
        expired = "過期" in role
        dirn = random.choice(["IN", "OUT"])
        return dict(
            event_id=eid, site_id=site["id"], site_name=site["name"],
            event_type="personnel", direction=dirn, event_ts=iso,
            event_time=hms, display_name=random.choice(_P_NAMES),
            secondary_id=f"E-{random.randint(1000, 1999)}",
            contractor=random.choice(_V_CONTRACTORS), detail=role,
            status="告警" if expired else ("離場" if dirn == "OUT" else "通行"),
            status_type="alert" if expired else "pass",
            snapshot_url=None, plate_snapshot_url=None,
            access_result="人工確認" if expired else "通行",
            confidence=round(random.uniform(.88, .97), 2),
            why="人臉相符 · 證照過期" if expired else "人臉與證件照相符",
            source="FaceID v1.8 (模擬)")

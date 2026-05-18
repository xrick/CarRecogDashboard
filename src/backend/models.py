"""
Pydantic schemas for the Site Board Dashboard API.

Field names follow the spec 工地看板_UI功能設計補充規格書 §8.1 / §8.2
(snake_case, datetime precise to the second). The board is a *display only*
client, so every model here is read-only from the board's perspective.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class EventType(str, Enum):
    vehicle = "vehicle"
    personnel = "personnel"


class Direction(str, Enum):
    IN = "IN"
    OUT = "OUT"


class StatusType(str, Enum):
    """Drives the colour rule from spec §2 (顏色規則)."""
    whitelist = "whitelist"   # 白名單  -> green
    pass_ = "pass"            # 通行    -> green
    stranger = "stranger"     # 陌生    -> yellow
    alert = "alert"           # 告警/證照過期 -> red
    blacklist = "blacklist"   # 黑名單  -> red
    pending = "pending"       # 名單未同步(系統安裝中) -> grey (FR-10/D5)


class AccessResult(str, Enum):
    opened = "opened"
    denied = "denied"
    manual_check = "manual_check"
    api_no_response = "api_no_response"


class ApiState(str, Enum):
    normal = "normal"
    delay = "delay"
    down = "down"


class SiteStatus(str, Enum):
    normal = "normal"
    alert = "alert"
    delay = "delay"


class Event(BaseModel):
    """即時事件 — spec §8.2. ``confidence``/``why``/``source`` add the
    AI-explainability layer shown in the demo (信心度 / 判定依據 / 資料來源)."""
    event_id: str
    site_id: str
    site_name: str
    event_type: EventType
    direction: Direction
    event_time: str = Field(..., description="HH:MM:SS, precise to the second")
    display_name: str = Field(..., description="車牌號碼 或 人員姓名")
    secondary_id: Optional[str] = Field(None, description="工號 / UNKNOWN 流水號")
    contractor: str
    detail: str = ""
    status: str = Field(..., description="白名單/黑名單/陌生/通行/拒絕/證照有效/證照過期")
    status_type: StatusType
    snapshot_url: Optional[str] = None
    plate_snapshot_url: Optional[str] = None
    access_result: str = ""
    # AI explainability
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    why: Optional[str] = None
    source: Optional[str] = None


class SiteSummary(BaseModel):
    """單一工地即時統計 — spec §8.1."""
    site_id: str
    site_name: str
    people_in: int = 0
    people_out: int = 0
    people_inside: int = 0
    vehicle_in: int = 0
    vehicle_out: int = 0
    vehicle_inside: int = 0
    alert_count: int = 0
    last_update_time: str
    status: SiteStatus = SiteStatus.normal


class OverviewKPI(BaseModel):
    """跨工地匯總，全工地總覽上方 KPI。"""
    people_in: int = 0
    people_out: int = 0
    people_inside: int = 0
    vehicle_in: int = 0
    vehicle_out: int = 0
    vehicle_inside: int = 0
    alert_count: int = 0
    blacklist: int = 0
    expired_cert: int = 0
    stranger_plate: int = 0
    api_online: int = 0
    api_total: int = 0


class SitesSummaryResponse(BaseModel):
    overview: OverviewKPI
    sites: list[SiteSummary]
    last_update_time: str


class HourlyTrendPoint(BaseModel):
    hour: str  # "00".."23"
    people_in: int = 0
    people_out: int = 0
    vehicle_in: int = 0
    vehicle_out: int = 0


class HourlyForecastPoint(BaseModel):
    hour: str
    people_in_forecast: int
    people_in_upper: int
    people_in_lower: int


class HourlyTrendResponse(BaseModel):
    site_id: str
    site_name: str
    current_hour: int
    trend: list[HourlyTrendPoint]
    forecast: list[HourlyForecastPoint]


class SystemStatus(BaseModel):
    """資料源與看板程式狀態 — spec §8.1 GET /dashboard/system/status."""
    plate_api_status: ApiState = ApiState.normal
    face_api_status: ApiState = ApiState.normal
    last_success_time: str
    latency_seconds: int = 0
    error_message: Optional[str] = None
    api_online: int = 2
    api_total: int = 2
    cached_events: int = 0
    version: str = "1.0.0"


class AlertCost(BaseModel):
    fp: str = Field(..., description="誤判代價 (False Positive)")
    fn: str = Field(..., description="漏判代價 (False Negative)")


class Alert(BaseModel):
    """異常事件牆卡片 — 黑名單 / 證照過期 / 陌生車牌 / API 延遲。"""
    id: str
    type: str = Field(..., description="blacklist|expired|stranger|api_delay")
    target: str
    detail: str
    site: str
    confidence: Optional[float] = None
    why: str = ""
    cost: AlertCost
    suggestions: list[str] = []
    occurrence: str = ""
    occurrence_count: int = 1


class AlertResolution(str, Enum):
    adopted = "adopted"               # 採納並處理 / 確認告警
    false_positive = "false_positive"  # 標記為誤判


class AlertResolveRequest(BaseModel):
    """人工拍板 (spec §5 human-in-the-loop)。看板端唯一允許的『寫入』動作 —
    僅記錄處置決策，不回寫相機/名單 (規格 §10)。"""
    resolution: AlertResolution
    actor: str = Field("operator", max_length=64)
    note: str = Field("", max_length=500)


class AlertResolveResponse(BaseModel):
    alert_id: str
    resolved: bool
    resolution: str


class CameraStream(BaseModel):
    """RTSP stream descriptor for the 現場影像 panel (spec §4.1.1)."""
    site_id: str
    site_name: str
    host: str
    channel: int
    subtype: int
    role: str
    kind: str
    rtsp_url: str


class CopilotSummary(BaseModel):
    """AI 副駕駛摘要 (異常事件牆 / 總覽上方)。"""
    headline: str
    body: str
    sources: str
    model: str
    generated_at: str

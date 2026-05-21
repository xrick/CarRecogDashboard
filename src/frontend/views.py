"""
The six board screens (spec §3 畫面模式總覽):

  overview  全工地總覽 Dashboard
  site      單一工地看板 Site Board
  vehicle   車輛進出看板 Vehicle Board
  personnel 人員進出看板 Personnel Board
  trend     趨勢全螢幕 Trend View
  alert     異常事件牆 Alert View

Every view exposes ``update_state(state)`` and rebuilds its dynamic content
from the latest snapshot. Rebuilding (rather than diffing) keeps the kiosk
code simple; updates are wrapped in setUpdatesEnabled to avoid flicker.
"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

from .charts import HourlyChart
from .theme import COLORS, base_font
from .widgets import (
    AICopilotSummary, AlertCard, EventRow, KpiCard, Panel,
    PersonnelDetailRow, PlateSnapshot, SectionTitle, SiteCard,
    SiteHeaderBar, StatusBadge, VehicleDetailRow, VehicleSnapshot,
    FaceSnapshot, _lbl,
)

_H = COLORS


def _clear(layout):
    while layout.count():
        it = layout.takeAt(0)
        w = it.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()
        elif it.layout() is not None:
            _clear(it.layout())


def _scroll_list(rows):
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.NoFrame)
    sa.setStyleSheet(
        f"QScrollArea{{background:transparent;border:none;}}"
        f"QScrollBar:vertical{{background:transparent;width:8px;}}"
        f"QScrollBar::handle:vertical{{background:{_H['border']};"
        f"border-radius:4px;min-height:24px;}}")
    box = QWidget()
    box.setStyleSheet("background:transparent;")
    v = QVBoxLayout(box)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(0)
    for r in rows:
        v.addWidget(r)
    v.addStretch(1)
    sa.setWidget(box)
    return sa


class _BaseView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{_H['bg']};")
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(12)
        self.state: dict = {}

    def update_state(self, state: dict):
        self.state = state
        self.setUpdatesEnabled(False)
        try:
            _clear(self._root)
            self._build()
        finally:
            self.setUpdatesEnabled(True)

    def _build(self):  # pragma: no cover - overridden
        raise NotImplementedError


# --------------------------------------------------------------------------- #
class OverviewView(_BaseView):
    def _build(self):
        s = self.state
        ss = s.get("sites_summary", {})
        ov = ss.get("overview", {})
        sites = ss.get("sites", [])

        outer = QHBoxLayout()
        outer.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(12)
        if s.get("copilot"):
            left.addWidget(AICopilotSummary(s["copilot"]))

        kpi = QHBoxLayout()
        kpi.setSpacing(10)
        kpi.addWidget(KpiCard("今日人員進場", f"{ov.get('people_in', 0):,}",
                              f"出場 {ov.get('people_out', 0):,} · 在場 {ov.get('people_inside', 0)}",
                              "in", large=True))
        kpi.addWidget(KpiCard("今日車輛進場", ov.get("vehicle_in", 0),
                              f"出場 {ov.get('vehicle_out', 0)} · 在場 {ov.get('vehicle_inside', 0)}",
                              "vehicleIn", large=True))
        kpi.addWidget(KpiCard("異常事件", ov.get("alert_count", 0),
                              f"黑名單 {ov.get('blacklist', 0)} · 證照過期 {ov.get('expired_cert', 0)}",
                              "alert", large=True))
        kpi.addWidget(KpiCard("API 狀態",
                              f"{ov.get('api_online', 0)}/{ov.get('api_total', 0)}",
                              "1 個工地資料延遲", "stranger", large=True))
        left.addLayout(kpi)

        grid_panel = Panel()
        grid_panel.v.addWidget(SectionTitle("各工地現況", f"共 {len(sites)} 個工地"))
        grid = QGridLayout()
        grid.setSpacing(10)
        for i, st in enumerate(sites):
            seed = [int(8 + 6 * ((i + j) % 5) + (j * 1.7)) for j in range(12)]
            anom = 11 if st.get("status") in ("alert", "delay") else -1
            grid.addWidget(SiteCard(st, seed, anom), i // 4, i % 4)
        gw = QWidget()
        gw.setStyleSheet("background:transparent;")
        gw.setLayout(grid)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.NoFrame)
        sa.setStyleSheet("background:transparent;border:none;")
        sa.setWidget(gw)
        grid_panel.v.addWidget(sa, 1)
        left.addWidget(grid_panel, 1)
        outer.addLayout(left, 1)

        right = Panel()
        right.setFixedWidth(380)
        right.v.addWidget(SectionTitle("最新進出快訊", "即時推送"))
        rows = [EventRow(e) for e in s.get("events", [])[:20]]
        right.v.addWidget(_scroll_list(rows), 1)
        outer.addWidget(right)
        self._root.addLayout(outer)


# --------------------------------------------------------------------------- #
class SiteBoardView(_BaseView):
    """單一工地看板 — spec §3.2，模板 p.4「人員 + 車輛同屏」."""

    def _build(self):
        s = self.state
        k = s.get("site_summary", {})
        tr = s.get("trend", {})
        evs = s.get("events", [])

        # (1) Header bar：右上「工地：xxx」+「最後更新 HH:MM」綠徽章
        self._root.addWidget(SiteHeaderBar(
            site_name=k.get("site_name", ""),
            last_update=k.get("last_update_time", "—"),
        ))

        # (2) KPI 6 cards — 人員 3 + 車輛 3
        kpi = QHBoxLayout()
        kpi.setSpacing(10)
        for lab, key, ck, sub in (
            ("人員進場", "people_in",      "in",        "今日累計人次"),
            ("人員出場", "people_out",     "out",       "今日累計人次"),
            ("目前在場", "people_inside",  "pass",      "人員即時在場"),
            ("車輛進場", "vehicle_in",     "vehicleIn", "今日累計車次"),
            ("車輛出場", "vehicle_out",    "vehicleOut","今日累計車次"),
            ("車輛在場", "vehicle_inside", "stranger",  "車輛即時在場"),
        ):
            kpi.addWidget(KpiCard(lab, k.get(key, 0), sub, ck))
        self._root.addLayout(kpi)

        # (3) Mid row：趨勢圖 (左) + 最新快訊與截圖 (右)
        mid = QHBoxLayout()
        mid.setSpacing(12)

        chart_panel = Panel()
        chart_panel.v.addWidget(SectionTitle("今日 0-24 小時進出趨勢"))
        # 模板 p.4 只放 2 系列：人員進場 (bar) + 車輛進場 (line)，無 AI 預測
        ch = HourlyChart(
            bars=[("people_in", "in", "人員進場")],
            lines=[("vehicle_in", "vehicleIn", "車輛進場")],
            show_forecast=False, legend=True)
        ch.set_data(tr.get("trend", []), [], tr.get("current_hour", 14))
        chart_panel.v.addWidget(ch, 1)
        mid.addWidget(chart_panel, 16)

        ev_panel = Panel()
        ev_panel.v.addWidget(SectionTitle("最新快訊與截圖", "即時推送"))
        ev_panel.v.addWidget(_scroll_list([EventRow(e) for e in evs[:5]]), 1)
        mid.addWidget(ev_panel, 10)
        self._root.addLayout(mid, 1)

        # (4) 現場影像參考：固定 2 車 + 1 人 (模板 p.4)
        snap = Panel()
        snap.v.addWidget(SectionTitle("現場影像參考"))
        row = QHBoxLayout()
        row.setSpacing(14)
        vehicle_evs = [e for e in evs if e.get("event_type") == "vehicle"][:2]
        people_evs = [e for e in evs if e.get("event_type") == "personnel"][:1]
        if vehicle_evs:
            row.addWidget(VehicleSnapshot(
                vehicle_evs[0]["display_name"], 200, 130,
                alert=vehicle_evs[0].get("status_type") in ("alert", "blacklist")))
        if people_evs:
            row.addWidget(FaceSnapshot(
                people_evs[0]["display_name"], 120,
                alert=people_evs[0].get("status_type") == "alert"))
        if len(vehicle_evs) > 1:
            row.addWidget(VehicleSnapshot(
                vehicle_evs[1]["display_name"], 170, 110,
                alert=vehicle_evs[1].get("status_type") in ("alert", "blacklist")))
        note = _lbl(
            "快訊跳卡顯示 5–8 秒，可設定是否保留在右側最新清單。\n"
            "黑名單、證照過期、陌生車牌會優先顯示。",
            "textMuted", 12)
        note.setWordWrap(True)
        row.addWidget(note, 1)
        rw = QWidget()
        rw.setStyleSheet("background:transparent;")
        rw.setLayout(row)
        snap.v.addWidget(rw)
        self._root.addWidget(snap)


# --------------------------------------------------------------------------- #
class VehicleView(_BaseView):
    def _build(self):
        s = self.state
        k = s.get("site_summary", {})
        tr = s.get("trend", {})
        evs = [e for e in s.get("events", []) if e.get("event_type") == "vehicle"]

        kpi = QHBoxLayout()
        kpi.setSpacing(10)
        kpi.addWidget(KpiCard("進場車次", k.get("vehicle_in", 0),
                              "今日 00:00 至目前", "vehicleIn", large=True))
        kpi.addWidget(KpiCard("離場車次", k.get("vehicle_out", 0),
                              "今日 00:00 至目前", "vehicleOut", large=True))
        kpi.addWidget(KpiCard("目前在場", k.get("vehicle_inside", 0),
                              "依進出事件估算", "pass", large=True))
        strangers = sum(1 for e in evs if e.get("status_type") == "stranger")
        kpi.addWidget(KpiCard("陌生車牌", strangers or 4,
                              "自動建立 UNKNOWN", "stranger", large=True))
        self._root.addLayout(kpi)

        mid = QHBoxLayout()
        mid.setSpacing(12)
        leftcol = QVBoxLayout()
        leftcol.setSpacing(12)
        snap = Panel()
        latest = evs[0] if evs else {"display_name": "ABC-5288",
                                     "contractor": "大榮土木", "detail": "砂石車",
                                     "event_time": "14:32:18", "status_type": "whitelist",
                                     "status": "白名單", "access_result": "閘門已開啟"}
        snap.v.addWidget(SectionTitle("最新車輛截圖", latest.get("event_time", "")))
        srow = QHBoxLayout()
        srow.setSpacing(14)
        srow.addWidget(VehicleSnapshot(latest["display_name"], 240, 150,
                                       alert=latest.get("status_type") in
                                       ("alert", "blacklist"),
                                       time_text=latest.get("event_time", "")))
        info = QVBoxLayout()
        info.setSpacing(4)
        prow = QHBoxLayout()
        prow.setSpacing(8)
        prow.addWidget(PlateSnapshot(latest["display_name"], 110, 36))
        prow.addWidget(StatusBadge(latest.get("status_type"), latest.get("status", "")))
        prow.addStretch(1)
        info.addLayout(prow)
        info.addWidget(_lbl(latest.get("contractor", ""), "text", 14, bold=True))
        info.addWidget(_lbl(f"{latest.get('detail', '')} · {latest.get('event_time', '')}",
                            "textMuted", 12))
        info.addWidget(_lbl(f"✓ {latest.get('access_result', '')}", "pass", 12))
        info.addStretch(1)
        srow.addLayout(info, 1)
        sw = QWidget()
        sw.setStyleSheet("background:transparent;")
        sw.setLayout(srow)
        snap.v.addWidget(sw)
        leftcol.addWidget(snap)

        chart_panel = Panel()
        chart_panel.v.addWidget(SectionTitle("每小時車輛進出趨勢"))
        ch = HourlyChart(
            bars=[("vehicle_in", "vehicleIn", "進場車次"),
                  ("vehicle_out", "vehicleOut", "離場車次")],
            lines=[], legend=True)
        ch.set_data(tr.get("trend", []), [], tr.get("current_hour", 14))
        chart_panel.v.addWidget(ch, 1)
        leftcol.addWidget(chart_panel, 1)
        mid.addLayout(leftcol, 12)

        ev_panel = Panel()
        ev_panel.v.addWidget(SectionTitle("最新車輛事件", f"{len(evs)} 筆"))
        ev_panel.v.addWidget(_scroll_list([VehicleDetailRow(e) for e in evs[:15]]), 1)
        mid.addWidget(ev_panel, 10)
        self._root.addLayout(mid, 1)


# --------------------------------------------------------------------------- #
class PersonnelView(_BaseView):
    def _build(self):
        s = self.state
        k = s.get("site_summary", {})
        tr = s.get("trend", {})
        evs = [e for e in s.get("events", []) if e.get("event_type") == "personnel"]

        kpi = QHBoxLayout()
        kpi.setSpacing(10)
        kpi.addWidget(KpiCard("進場人次", k.get("people_in", 0),
                              "今日 00:00 至目前", "in", large=True))
        kpi.addWidget(KpiCard("離場人次", k.get("people_out", 0),
                              "今日 00:00 至目前", "out", large=True))
        kpi.addWidget(KpiCard("目前在場", k.get("people_inside", 0),
                              "去重後估算人數", "pass", large=True))
        bad = sum(1 for e in evs if e.get("status_type") == "alert")
        kpi.addWidget(KpiCard("證照異常", bad or 5,
                              "過期 3 · 缺漏 2", "alert", large=True))
        self._root.addLayout(kpi)

        mid = QHBoxLayout()
        mid.setSpacing(12)
        chart_panel = Panel()
        chart_panel.v.addWidget(SectionTitle("每小時人員進出趨勢"))
        ch = HourlyChart(
            bars=[("people_in", "in", "進場人次"),
                  ("people_out", "out", "離場人次")],
            lines=[], legend=True)
        ch.set_data(tr.get("trend", []), [], tr.get("current_hour", 14))
        chart_panel.v.addWidget(ch, 1)
        mid.addWidget(chart_panel, 12)

        ev_panel = Panel()
        ev_panel.v.addWidget(SectionTitle("最新人員辨識", f"{len(evs)} 筆"))
        ev_panel.v.addWidget(_scroll_list([PersonnelDetailRow(e) for e in evs[:15]]), 1)
        mid.addWidget(ev_panel, 10)
        self._root.addLayout(mid, 1)


# --------------------------------------------------------------------------- #
class TrendView(_BaseView):
    def _build(self):
        s = self.state
        tr = s.get("trend", {})
        panel = Panel()
        cur = tr.get("current_hour", 14)
        panel.v.addWidget(SectionTitle(
            f"{tr.get('site_name', '')} · 今日 0-24H 人車進出趨勢",
            f"目前 {cur} 時 · 每分鐘刷新"))
        ch = HourlyChart(
            bars=[("people_in", "in", "人員進場"), ("people_out", "out", "人員離場")],
            lines=[("vehicle_in", "vehicleIn", "車輛進場"),
                   ("vehicle_out", "vehicleOut", "車輛離場")],
            axis_font=13)
        ch.set_data(tr.get("trend", []), [], cur)
        panel.v.addWidget(ch, 1)
        panel.v.addWidget(_lbl(
            "設計備註:人員與車輛可分開顯示,也可同圖疊加。建議保留至少 2.6 吋高,"
            "避免數字與折線太小。", "textMuted", 12))
        self._root.addWidget(panel, 1)


# --------------------------------------------------------------------------- #
class AlertView(_BaseView):
    def _build(self):
        s = self.state
        alerts = s.get("alerts", [])
        delay = next((a for a in alerts if a.get("type") == "api_delay"), None)
        banner_txt = ("⚠ " + (f"{delay['site']} · {delay['detail']}"
                               if delay else "目前無 API 延遲")
                      + " · 請確認 API 服務或網路連線")
        banner = QLabel(banner_txt)
        banner.setFont(base_font(14, bold=True))
        banner.setStyleSheet(
            f"color:{_H['alert']};background:rgba(248,113,113,0.15);"
            f"border:1px solid {_H['alert']};border-radius:6px;padding:10px 16px;")
        self._root.addWidget(banner)

        if s.get("copilot"):
            self._root.addWidget(AICopilotSummary(s["copilot"]))

        panel = Panel()
        panel.v.addWidget(SectionTitle(
            "異常事件牆",
            "優先順序:黑名單/證照過期 > API 斷線 > 陌生車牌 > 資料延遲"))
        grid = QGridLayout()
        grid.setSpacing(14)
        grid.setAlignment(Qt.AlignTop)
        for i, a in enumerate(alerts):
            grid.addWidget(AlertCard(a), i // 4, i % 4)
        gw = QWidget()
        gw.setStyleSheet("background:transparent;")
        gw.setLayout(grid)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.NoFrame)
        sa.setStyleSheet("background:transparent;border:none;")
        sa.setWidget(gw)
        panel.v.addWidget(sa, 1)
        panel.v.addWidget(_lbl(
            "每張卡片均顯示 AI 信心度、判定依據、誤判/漏判代價(Value Matrix),"
            "以及建議下一步,最終由人類拍板。", "textMuted", 12))
        self._root.addWidget(panel, 1)


from .rtsp_panel import RtspView  # noqa: E402  (kept separate: lazy cv2)

VIEW_CLASSES = {
    "overview": OverviewView, "site": SiteBoardView, "vehicle": VehicleView,
    "personnel": PersonnelView, "trend": TrendView, "alert": AlertView,
    "cctv": RtspView,
}

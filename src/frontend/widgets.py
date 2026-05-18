"""
Reusable building blocks ported 1:1 from the React demo so the PyQt board
matches the approved look (tests/dashboard-standalone_demo2.html) and the
spec templates (模板第 3-10 頁).
"""
from __future__ import annotations

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from .theme import COLORS, base_font

_HEX = COLORS


def rgba(key: str, a: float) -> str:
    c = QColor(_HEX.get(key, key))
    return f"rgba({c.red()},{c.green()},{c.blue()},{a})"


def _lbl(text, color="text", size=13, bold=False, mono=False) -> QLabel:
    q = QLabel(str(text))
    q.setFont(base_font(size, bold, mono))
    q.setStyleSheet(f"color:{_HEX.get(color, color)};background:transparent;")
    return q


# --------------------------------------------------------------------------- #
class Panel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame{{background:{_HEX['bgCard']};"
            f"border:1px solid {_HEX['border']};border-radius:10px;}}")
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(16, 14, 16, 14)
        self.v.setSpacing(10)


class SectionTitle(QWidget):
    def __init__(self, text, right="", parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 8)
        left = _lbl(text, "text", 14, bold=True)
        h.addWidget(left)
        h.addStretch(1)
        if right:
            h.addWidget(_lbl(right, "textMuted", 12))
        self.setStyleSheet(f"border-bottom:1px solid {_HEX['border']};")


class KpiCard(QFrame):
    def __init__(self, label, value, sub="", accent="in", large=False, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame{{background:{_HEX['bgCard']};"
            f"border:1px solid {_HEX['border']};border-radius:8px;}}")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        strip = QFrame()
        strip.setFixedWidth(3)
        strip.setStyleSheet(f"background:{_HEX.get(accent, accent)};border:none;")
        row.addWidget(strip)
        body = QVBoxLayout()
        body.setContentsMargins(14, 10 if not large else 14, 14, 10 if not large else 14)
        body.setSpacing(4)
        body.addWidget(_lbl(label, "textDim", 13 if large else 12))
        val = _lbl(value, accent, 40 if large else 30, bold=True, mono=True)
        body.addWidget(val)
        if sub:
            body.addWidget(_lbl(sub, "textMuted", 11))
        row.addLayout(body)


class StatusBadge(QLabel):
    _MAP = {
        "whitelist": ("pass", 0.15), "pass": ("pass", 0.15),
        "stranger": ("stranger", 0.15), "alert": ("alert", 0.18),
        "blacklist": ("alert", 0.18),
        "pending": ("textMuted", 0.18),   # 名單未同步(系統安裝中) — neutral grey
    }

    def __init__(self, status_type, text, parent=None):
        super().__init__(str(text), parent)
        ck, a = self._MAP.get(status_type, ("pass", 0.15))
        self.setFont(base_font(11, bold=True))
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(
            f"color:{_HEX[ck]};background:{rgba(ck, a)};"
            f"padding:2px 8px;border-radius:4px;")


class DirectionPill(QLabel):
    def __init__(self, direction, parent=None):
        is_in = direction == "IN"
        super().__init__("進" if is_in else "出", parent)
        ck = "in" if is_in else "out"
        self.setFixedSize(24, 24)
        self.setAlignment(Qt.AlignCenter)
        self.setFont(base_font(12, bold=True))
        self.setStyleSheet(
            f"color:{_HEX[ck]};background:{rgba(ck, 0.18)};border-radius:4px;")


class ConfidenceChip(QLabel):
    def __init__(self, value, parent=None):
        if value is None:
            super().__init__("規則判定", parent)
            self.setStyleSheet(
                f"color:{_HEX['textMuted']};background:{rgba('textDim', 0.15)};"
                f"padding:1px 6px;border-radius:3px;")
        else:
            pct = round(value * 100)
            ck = "pass" if value >= 0.9 else "stranger" if value >= 0.75 else "alert"
            super().__init__(f"AI {pct}%", parent)
            self.setStyleSheet(
                f"color:{_HEX[ck]};background:{rgba('bgCard', 0.6)};"
                f"border:1px solid {_HEX[ck]};padding:1px 6px;border-radius:3px;")
        self.setFont(base_font(11, bold=True, mono=True))


# --------------------------------------------------------------------------- #
# Snapshots (placeholder renderings until real 截圖 URLs are wired up §11)
# --------------------------------------------------------------------------- #
class FaceSnapshot(QWidget):
    def __init__(self, name="?", size=64, alert=False, parent=None):
        super().__init__(parent)
        self._n = name or "?"
        self._alert = alert
        self.setFixedSize(size, size)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        s = self.width()
        g = QLinearGradient(0, 0, s, s)
        g.setColorAt(0, QColor("#1E3A6B"))
        g.setColorAt(1, QColor("#2A4F8E"))
        p.setBrush(g)
        p.setPen(QPen(QColor(_HEX["alert"] if self._alert else _HEX["borderLight"]), 2))
        p.drawEllipse(1, 1, s - 2, s - 2)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(143, 163, 199, 90))
        p.drawEllipse(int(s * 0.34), int(s * 0.22), int(s * 0.32), int(s * 0.32))
        path = QPainterPath()
        path.moveTo(s * 0.18, s * 0.92)
        path.quadTo(s * 0.5, s * 0.55, s * 0.82, s * 0.92)
        p.drawPath(path)
        bs = max(14, int(s * 0.26))
        p.setBrush(QColor(_HEX["alert"]) if self._alert else QColor(34, 211, 238, 220))
        p.drawRoundedRect(s - bs - 2, s - bs - 2, bs, bs, 3, 3)
        p.setPen(QColor("#000"))
        p.setFont(base_font(max(8, bs // 2), bold=True))
        p.drawText(s - bs - 2, s - bs - 2, bs, bs, Qt.AlignCenter, self._n[:1])
        p.end()


class VehicleSnapshot(QWidget):
    def __init__(self, plate="ABC-0000", w=200, h=130, alert=False,
                 time_text="14:32:18", parent=None):
        super().__init__(parent)
        self._plate, self._alert, self._t = plate, alert, time_text
        self.setFixedSize(w, h)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        W, H = self.width(), self.height()
        g = QLinearGradient(0, 0, 0, H)
        g.setColorAt(0, QColor("#1A2D52"))
        g.setColorAt(1, QColor("#0F1B33"))
        p.setBrush(g)
        p.setPen(QPen(QColor(_HEX["alert"] if self._alert else _HEX["border"]), 1))
        p.drawRoundedRect(0, 0, W - 1, H - 1, 6, 6)
        sx, sy = W / 200.0, H / 130.0
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(143, 163, 199, 80))
        p.drawRoundedRect(int(40 * sx), int(55 * sy), int(120 * sx), int(40 * sy), 4, 4)
        p.drawRoundedRect(int(55 * sx), int(40 * sy), int(80 * sx), int(22 * sy), 3, 3)
        p.setBrush(QColor(10, 20, 40))
        p.setPen(QPen(QColor(143, 163, 199, 130), 1))
        r = int(10 * sx)
        p.drawEllipse(int(60 * sx) - r, int(100 * sy) - r, 2 * r, 2 * r)
        p.drawEllipse(int(140 * sx) - r, int(100 * sy) - r, 2 * r, 2 * r)
        # plate chip
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 190))
        pw = min(W - 12, 9 * len(self._plate) + 16)
        p.drawRoundedRect(6, H - 24, int(pw), 18, 3, 3)
        p.setPen(QColor(_HEX["alert"] if self._alert else "#FFE066"))
        p.setFont(base_font(11, bold=True, mono=True))
        p.drawText(10, H - 24, int(pw), 18, Qt.AlignVCenter, self._plate)
        if W > 110:
            p.setPen(QColor(_HEX["textDim"]))
            p.setFont(base_font(9, mono=True))
            p.drawText(W - 64, 6, 58, 14, Qt.AlignRight, self._t)
        p.end()


class PlateSnapshot(QLabel):
    def __init__(self, plate="ABC-0000", w=100, h=36, parent=None):
        super().__init__(str(plate), parent)
        self.setFixedSize(w, h)
        self.setAlignment(Qt.AlignCenter)
        fs = 18
        if w < 110:
            fs = 11 if len(plate) > 8 else 14
        elif w < 140:
            fs = 12 if len(plate) > 8 else 16
        f = base_font(fs, bold=True, mono=True)
        self.setFont(f)
        self.setStyleSheet(
            "color:#000;background:#FFE066;border:2px solid #1A1A1A;"
            "border-radius:3px;")


# --------------------------------------------------------------------------- #
# Event rows
# --------------------------------------------------------------------------- #
class EventRow(QFrame):
    def __init__(self, ev: dict, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"border-bottom:1px solid {_HEX['border']};")
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 9, 12, 9)
        h.setSpacing(10)
        h.addWidget(DirectionPill(ev.get("direction")))
        h.addWidget(_lbl(ev.get("event_time", "")[:5], "textDim", 12, mono=True))
        mid = QVBoxLayout()
        mid.setSpacing(2)
        name = ev.get("display_name", "")
        if ev.get("secondary_id"):
            name += f"  / {ev['secondary_id']}"
        mid.addWidget(_lbl(name, "text", 13, bold=True,
                           mono=(ev.get("event_type") == "vehicle")))
        meta = f"{ev.get('site_id', '')} · {ev.get('contractor', '')} · {ev.get('detail', '')}"
        mid.addWidget(_lbl(meta, "textMuted", 11))
        h.addLayout(mid, 1)
        right = QVBoxLayout()
        right.setSpacing(3)
        right.setAlignment(Qt.AlignRight)
        right.addWidget(StatusBadge(ev.get("status_type"), ev.get("status", "")),
                        0, Qt.AlignRight)
        if ev.get("confidence") is not None:
            right.addWidget(ConfidenceChip(ev["confidence"]), 0, Qt.AlignRight)
        h.addLayout(right)


class VehicleDetailRow(QFrame):
    def __init__(self, ev: dict, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"border-bottom:1px solid {_HEX['border']};")
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 12, 14, 12)
        h.setSpacing(12)
        h.addWidget(DirectionPill(ev.get("direction")))
        h.addWidget(_lbl(ev.get("event_time", ""), "textDim", 12, mono=True))
        h.addWidget(PlateSnapshot(ev.get("display_name", ""), 130, 30))
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(_lbl(ev.get("contractor", ""), "text", 13))
        col.addWidget(_lbl(f"{ev.get('detail', '')} · {ev.get('access_result', '')}",
                           "textMuted", 11))
        h.addLayout(col, 1)
        h.addWidget(StatusBadge(ev.get("status_type"), ev.get("status", "")))


class PersonnelDetailRow(QFrame):
    def __init__(self, ev: dict, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"border-bottom:1px solid {_HEX['border']};")
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 12, 14, 12)
        h.setSpacing(12)
        h.addWidget(DirectionPill(ev.get("direction")))
        h.addWidget(_lbl(ev.get("event_time", ""), "textDim", 12, mono=True))
        h.addWidget(FaceSnapshot(ev.get("display_name", "?"), 42,
                                 ev.get("status_type") == "alert"))
        col = QVBoxLayout()
        col.setSpacing(2)
        nm = ev.get("display_name", "")
        if ev.get("secondary_id"):
            nm += f"  / {ev['secondary_id']}"
        col.addWidget(_lbl(nm, "text", 13, bold=True))
        col.addWidget(_lbl(f"{ev.get('contractor', '')} · {ev.get('detail', '')}",
                           "textMuted", 11))
        h.addLayout(col, 1)
        h.addWidget(StatusBadge(ev.get("status_type"), ev.get("status", "")))


# --------------------------------------------------------------------------- #
class AICopilotSummary(QFrame):
    def __init__(self, copilot: dict, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame{{background:{rgba('in', 0.06)};"
            f"border:1px solid {_HEX['in']};border-radius:8px;}}")
        h = QHBoxLayout(self)
        h.setContentsMargins(16, 12, 16, 12)
        h.setSpacing(14)
        badge = _lbl("AI", "in", 16, bold=True)
        badge.setFixedSize(32, 32)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(
            f"color:{_HEX['in']};background:{rgba('in', 0.2)};"
            f"border:1px solid {_HEX['in']};border-radius:16px;")
        h.addWidget(badge, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(4)
        head = copilot.get("headline", "AI 副駕駛")
        when = copilot.get("generated_at", "")
        col.addWidget(_lbl(f"{head} · {when} 摘要", "in", 12, bold=True))
        body = _lbl(copilot.get("body", ""), "text", 13)
        body.setWordWrap(True)
        col.addWidget(body)
        src = f"資料來源:{copilot.get('sources', '')}   ·   模型:{copilot.get('model', '')}"
        col.addWidget(_lbl(src, "textMuted", 11))
        h.addLayout(col, 1)


class AlertCard(QFrame):
    _META = {
        "blacklist": ("alert", "黑名單車牌"), "expired": ("alert", "證照過期"),
        "stranger": ("stranger", "陌生車牌"), "api_delay": ("stranger", "資料延遲"),
        "list_stale": ("stranger", "名單過期/未同步"),
    }
    _ICON = {"api_delay": "API", "list_stale": "名單"}

    def __init__(self, a: dict, parent=None):
        super().__init__(parent)
        self._aid = a.get("id", "")
        self._site = a.get("site", "ALL")
        ck, label = self._META.get(a.get("type"), ("alert", "異常"))
        self.setStyleSheet(
            f"QFrame#card{{background:{rgba(ck, 0.08)};"
            f"border:1px solid {_HEX[ck]};border-radius:8px;}}")
        self.setObjectName("card")
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(10)
        top = QHBoxLayout()
        top.addWidget(_lbl(f"● {label}", ck, 12, bold=True))
        top.addStretch(1)
        top.addWidget(ConfidenceChip(a.get("confidence")))
        v.addLayout(top)

        is_vehicle = a.get("type") in ("blacklist", "stranger")
        if is_vehicle:
            v.addWidget(VehicleSnapshot(a.get("target", ""), 240, 90, alert=True),
                        0, Qt.AlignHCenter)
        elif a.get("type") == "expired":
            v.addWidget(FaceSnapshot(a.get("target", "?")[:1], 70, alert=True),
                        0, Qt.AlignHCenter)
        else:
            api = _lbl(self._ICON.get(a.get("type"), "⚠"), ck, 24, bold=True)
            api.setAlignment(Qt.AlignCenter)
            api.setFixedHeight(80)
            api.setStyleSheet(
                f"color:{_HEX[ck]};background:{rgba('bg', 0.4)};border-radius:4px;")
            v.addWidget(api)

        v.addWidget(_lbl(a.get("target", ""), "text", 16, bold=True,
                         mono=is_vehicle))
        d = _lbl(a.get("detail", ""), "textMuted", 11)
        d.setWordWrap(True)
        v.addWidget(d)
        tags = QHBoxLayout()
        tags.setSpacing(6)
        site_tag = _lbl(a.get("site", ""), "textDim", 10)
        site_tag.setStyleSheet(
            f"color:{_HEX['textDim']};background:{rgba('bgCard', 0.6)};"
            f"padding:1px 5px;border-radius:3px;")
        occ_tag = _lbl(a.get("occurrence", ""), "stranger", 10)
        occ_tag.setStyleSheet(
            f"color:{_HEX['stranger']};background:{rgba('stranger', 0.1)};"
            f"padding:1px 5px;border-radius:3px;")
        tags.addWidget(site_tag)
        tags.addWidget(occ_tag)
        tags.addStretch(1)
        v.addLayout(tags)

        why = _lbl(f"● 判定  {a.get('why', '')}", "textDim", 10)
        why.setWordWrap(True)
        why.setStyleSheet(
            f"color:{_HEX['textDim']};background:{rgba('bgCard', 0.5)};"
            f"border:1px dashed {_HEX['borderLight']};"
            f"border-radius:4px;padding:6px 8px;")
        v.addWidget(why)

        cost = a.get("cost", {})
        crow = QHBoxLayout()
        crow.setSpacing(6)
        for title, txt, cc in (("誤判代價 (FP)", cost.get("fp", ""), "pass"),
                               ("漏判代價 (FN)", cost.get("fn", ""), "alert")):
            box = QFrame()
            box.setStyleSheet(
                f"background:{rgba(cc, 0.06)};"
                f"border:1px solid {rgba(cc, 0.25)};border-radius:4px;")
            bv = QVBoxLayout(box)
            bv.setContentsMargins(7, 5, 7, 5)
            bv.setSpacing(2)
            bv.addWidget(_lbl(title, cc, 10, bold=True))
            tl = _lbl(txt, "textMuted", 10)
            tl.setWordWrap(True)
            bv.addWidget(tl)
            crow.addWidget(box, 1)
        v.addLayout(crow)

        v.addWidget(_lbl("◆ AI 建議下一步", "in", 11, bold=True))
        for i, s in enumerate(a.get("suggestions", []), 1):
            sug = _lbl(f"{i}.  {s}", "text", 11)
            sug.setStyleSheet(
                f"color:{_HEX['text']};background:{rgba('in', 0.06)};"
                f"border-left:2px solid {_HEX['in']};"
                f"border-radius:3px;padding:4px 6px;")
            v.addWidget(sug)

        btns = QHBoxLayout()
        btns.setSpacing(6)
        adopt = QPushButton("採納並處理")
        adopt.setCursor(Qt.PointingHandCursor)
        adopt.setStyleSheet(
            f"QPushButton{{background:{_HEX[ck]};color:{_HEX['bg']};border:none;"
            f"padding:6px 0;border-radius:4px;font-weight:700;}}")
        fp = QPushButton("誤判")
        fp.setCursor(Qt.PointingHandCursor)
        fp.setStyleSheet(
            f"QPushButton{{background:transparent;color:{_HEX['textDim']};"
            f"border:1px solid {_HEX['borderLight']};padding:6px 0;"
            f"border-radius:4px;}}")
        adopt.clicked.connect(lambda: self._resolve("adopted", adopt, fp))
        fp.clicked.connect(lambda: self._resolve("false_positive", adopt, fp))
        btns.addWidget(adopt, 2)
        btns.addWidget(fp, 1)
        v.addLayout(btns)
        v.addStretch(1)

    def _resolve(self, resolution: str, adopt, fp) -> None:
        """人工拍板 (spec §5): POST resolve on a QThread, then disable the
        buttons. ACTION_BUS triggers a board refresh so the card drops out
        (db.alerts filters resolved=0)."""
        from .api_client import resolve_alert_async
        for b in (adopt, fp):
            b.setEnabled(False)
        adopt.setText("已採納處理" if resolution == "adopted" else "已採納")
        fp.setText("已標記誤判" if resolution == "false_positive" else "誤判")
        resolve_alert_async(self._site, self._aid, resolution)


class SiteCard(QFrame):
    def __init__(self, s: dict, trend_vals=None, anomaly_at=-1, parent=None):
        super().__init__(parent)
        st = s.get("status", "normal")
        bc = "alert" if st == "alert" else "stranger" if st == "delay" else "border"
        self.setStyleSheet(
            f"QFrame#sc{{background:{_HEX['bgCard']};"
            f"border:1px solid {_HEX[bc]};border-radius:8px;}}")
        self.setObjectName("sc")
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(8)
        head = QHBoxLayout()
        head.addWidget(_lbl(s.get("site_name", ""), "text", 13, bold=True))
        head.addStretch(1)
        if st in ("alert", "delay"):
            tag = _lbl("異常" if st == "alert" else "延遲",
                       "alert" if st == "alert" else "stranger", 10, bold=True)
            head.addWidget(tag)
        v.addLayout(head)
        nums = QHBoxLayout()
        for lab, val, ck in (("人員在場", s.get("people_inside", 0), "in"),
                             ("車輛在場", s.get("vehicle_inside", 0), "vehicleIn")):
            col = QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(_lbl(lab, "textMuted", 10))
            col.addWidget(_lbl(val, ck, 24, bold=True, mono=True))
            nums.addLayout(col, 1)
        v.addLayout(nums)
        from .charts import MiniBarChart
        mini = MiniBarChart("in", anomaly_at)
        mini.set_values(trend_vals or [], anomaly_at)
        v.addWidget(mini)


# --------------------------------------------------------------------------- #
class FlashCard(QFrame):
    """即時快訊跳卡 — spec §5. 5 s normal / 8 s 告警, then auto-dismiss."""
    closed = pyqtSignal(str)

    def __init__(self, ev: dict, parent=None):
        super().__init__(parent)
        self._id = ev.get("event_id", "")
        # alert row derived from this event in ingest._emit is "al_<event_id>"
        self._aid = f"al_{ev.get('event_id', '')}"
        self._site = ev.get("site_id", "ALL")
        is_v = ev.get("event_type") == "vehicle"
        is_alert = ev.get("status_type") in ("alert", "blacklist")
        accent = "alert" if is_alert else ("vehicleIn" if is_v else "in")
        self.setFixedWidth(360)
        self.setStyleSheet(
            f"QFrame#flash{{background:{'#1F0A12' if is_alert else _HEX['bgCard']};"
            f"border:2px solid {_HEX['alert'] if is_alert else _HEX['in']};"
            f"border-radius:10px;}}")
        self.setObjectName("flash")
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(10)

        top = QHBoxLayout()
        kind = ("車輛" if is_v else "人員") + ("告警" if is_alert else "進場")
        top.addWidget(_lbl(f"● {kind}", accent, 13, bold=True))
        top.addStretch(1)
        top.addWidget(_lbl(ev.get("event_time", ""), "textMuted", 11, mono=True))
        v.addLayout(top)
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background:{_HEX['border']};")
        v.addWidget(line)

        body = QHBoxLayout()
        body.setSpacing(12)
        if is_v:
            body.addWidget(VehicleSnapshot(ev.get("display_name", ""), 130, 84,
                                           alert=is_alert,
                                           time_text=ev.get("event_time", "")))
        else:
            body.addWidget(FaceSnapshot(ev.get("display_name", "?"), 84,
                                        alert=is_alert))
        info = QVBoxLayout()
        info.setSpacing(2)
        info.addWidget(_lbl(ev.get("display_name", ""), "text", 20, bold=True,
                            mono=is_v))
        if ev.get("secondary_id"):
            info.addWidget(_lbl(f"/ {ev['secondary_id']}", "textMuted", 12))
        info.addWidget(_lbl(ev.get("contractor", ""), "textDim", 12))
        info.addWidget(_lbl(ev.get("detail", ""), "textMuted", 11))
        info.addStretch(1)
        body.addLayout(info, 1)
        v.addLayout(body)

        foot = QHBoxLayout()
        foot.setSpacing(6)
        foot.addWidget(StatusBadge(ev.get("status_type"), ev.get("status", "")))
        if ev.get("confidence") is not None:
            foot.addWidget(ConfidenceChip(ev["confidence"]))
        foot.addStretch(1)
        foot.addWidget(_lbl(ev.get("access_result", ""),
                            "alert" if is_alert else "pass", 12, bold=True))
        v.addLayout(foot)

        if is_alert and ev.get("why"):
            ex = _lbl(f"● 判定依據  {ev.get('why', '')}\n資料來源  {ev.get('source', '')}",
                      "textDim", 11)
            ex.setWordWrap(True)
            ex.setStyleSheet(
                f"color:{_HEX['textDim']};background:{rgba('bgCard', 0.5)};"
                f"border:1px dashed {_HEX['borderLight']};"
                f"border-radius:6px;padding:8px 10px;")
            v.addWidget(ex)
            ack = QHBoxLayout()
            ack.setSpacing(8)
            b1 = QPushButton("確認告警")
            b1.setStyleSheet(
                f"QPushButton{{background:{rgba('alert', 0.15)};"
                f"color:{_HEX['alert']};border:1px solid {_HEX['alert']};"
                f"padding:6px 0;border-radius:4px;font-weight:600;}}")
            b2 = QPushButton("標記為誤判")
            b2.setStyleSheet(
                f"QPushButton{{background:transparent;color:{_HEX['textDim']};"
                f"border:1px solid {_HEX['borderLight']};padding:6px 0;"
                f"border-radius:4px;}}")
            b1.clicked.connect(lambda: self._ack("adopted", b1, b2))
            b2.clicked.connect(lambda: self._ack("false_positive", b1, b2))
            ack.addWidget(b1, 1)
            ack.addWidget(b2, 1)
            v.addLayout(ack)

        QTimer.singleShot(8000 if is_alert else 5000,
                          lambda: self.closed.emit(self._id))

    def _ack(self, resolution: str, b1, b2) -> None:
        """人工拍板 from the flash card (spec §5): resolve the derived
        alert, then dismiss the card."""
        from .api_client import resolve_alert_async
        for b in (b1, b2):
            b.setEnabled(False)
        resolve_alert_async(self._site, self._aid, resolution)
        self.closed.emit(self._id)

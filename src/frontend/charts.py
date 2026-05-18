"""
Dependency-free charts drawn with QPainter.

Re-creates the Recharts visuals from the demo without pulling in a charting
library: grouped hourly bars + overlaid line series, a red "目前 N 時"
reference line (spec §6), and the AI forecast — dashed line inside a shaded
confidence cone (demo ch.13).
"""
from __future__ import annotations

import math

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF
from PyQt5.QtWidgets import QWidget

from .theme import COLORS, base_font, qc


def _nice_max(v: float) -> int:
    if v <= 5:
        return 5
    step = 10 ** int(math.log10(v))
    for m in (1, 2, 2.5, 5, 10):
        if step * m >= v:
            return int(step * m)
    return int(step * 10)


class HourlyChart(QWidget):
    """0-24h grouped bar + line chart with optional forecast."""

    def __init__(self, bars, lines, *, show_forecast=False,
                 axis_font=11, legend=True, parent=None):
        super().__init__(parent)
        self._bars = bars            # [(key, color_key, label)]
        self._lines = lines          # [(key, color_key, label)]
        self._show_forecast = show_forecast
        self._axis_font = axis_font
        self._legend = legend
        self._trend: list[dict] = []
        self._forecast: list[dict] = []
        self._cur = 14
        self.setMinimumHeight(160)
        self.setAttribute(Qt.WA_StyledBackground, False)

    def set_data(self, trend, forecast, current_hour):
        self._trend = trend or []
        self._forecast = forecast or []
        self._cur = int(current_hour)
        self.update()

    # ------------------------------------------------------------------ #
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        W, H = self.width(), self.height()
        if not self._trend:
            p.setPen(qc("textMuted"))
            p.setFont(base_font(12))
            p.drawText(self.rect(), Qt.AlignCenter, "等待資料…")
            return

        legend_h = 26 if self._legend else 6
        ml, mr, mt, mb = 46, 16, 32, 22 + legend_h
        plot = QRectF(ml, mt, max(1, W - ml - mr), max(1, H - mt - mb))

        by_hour = {int(d["hour"]): d for d in self._trend}
        fc_by = {int(d["hour"]): d for d in self._forecast}

        vals = []
        for d in self._trend:
            for k, _c, _l in self._bars + self._lines:
                v = d.get(k)
                if v is not None:
                    vals.append(v)
        if self._show_forecast:
            for d in self._forecast:
                vals.append(d.get("people_in_upper", 0))
        ymax = _nice_max(max(vals) if vals else 1)

        def yof(v):
            return plot.bottom() - (v / ymax) * plot.height()

        def xof(hour):  # center of an hour slot
            return plot.left() + (hour + 0.5) * plot.width() / 24.0

        # grid + y ticks
        p.setFont(base_font(self._axis_font - 1))
        for i in range(5):
            v = ymax * i / 4
            y = yof(v)
            pen = QPen(qc("border"), 1, Qt.DashLine)
            p.setPen(pen)
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(qc("textMuted"))
            p.drawText(QRectF(0, y - 9, ml - 6, 18),
                       Qt.AlignRight | Qt.AlignVCenter, str(int(round(v))))

        # x labels every 3h (matches the pptx template)
        p.setPen(qc("textMuted"))
        for h in range(0, 24, 3):
            p.drawText(QRectF(xof(h) - 14, plot.bottom() + 3, 28, 16),
                       Qt.AlignHCenter | Qt.AlignTop, f"{h:02d}")

        # confidence cone + forecast dashed line ---------------------------
        if self._show_forecast and self._forecast:
            cur_d = by_hour.get(self._cur, {})
            start_v = cur_d.get(self._bars[0][0]) if self._bars else None
            ups = []
            los = []
            if start_v is not None:
                ups.append(QPointF(xof(self._cur), yof(start_v)))
                los.append(QPointF(xof(self._cur), yof(start_v)))
            for fh in sorted(fc_by):
                d = fc_by[fh]
                ups.append(QPointF(xof(fh), yof(d["people_in_upper"])))
                los.append(QPointF(xof(fh), yof(d["people_in_lower"])))
            if len(ups) > 1:
                poly = QPolygonF(ups + los[::-1])
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(qc("in", 0.18)))
                p.drawPolygon(poly)
                fc_line = [QPointF(xof(self._cur), yof(start_v))] if start_v is not None else []
                fc_line += [QPointF(xof(fh), yof(fc_by[fh]["people_in_forecast"]))
                            for fh in sorted(fc_by)]
                pen = QPen(qc("in"), 2, Qt.DashLine)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawPolyline(QPolygonF(fc_line))
                for pt in fc_line[1:]:
                    p.setBrush(qc("in"))
                    p.drawEllipse(pt, 3, 3)

        # grouped bars -----------------------------------------------------
        nb = max(1, len(self._bars))
        group_w = plot.width() / 24.0 * 0.62
        bw = group_w / nb
        for bi, (key, ckey, _lbl) in enumerate(self._bars):
            p.setPen(Qt.NoPen)
            p.setBrush(qc(ckey))
            for h in range(24):
                v = by_hour.get(h, {}).get(key)
                if not v:
                    continue
                x = xof(h) - group_w / 2 + bi * bw
                top = yof(v)
                p.drawRoundedRect(QRectF(x, top, bw - 1.5,
                                         plot.bottom() - top), 2, 2)

        # line series ------------------------------------------------------
        for key, ckey, _lbl in self._lines:
            pts = [QPointF(xof(h), yof(by_hour[h][key]))
                   for h in range(24)
                   if h in by_hour and by_hour[h].get(key) is not None]
            if len(pts) < 2:
                continue
            p.setPen(QPen(qc(ckey), 2))
            p.setBrush(Qt.NoBrush)
            p.drawPolyline(QPolygonF(pts))

        # "目前 N 時" reference line --------------------------------------
        rx = xof(self._cur)
        p.setPen(QPen(qc("alert"), 2))
        p.drawLine(QPointF(rx, plot.top()), QPointF(rx, plot.bottom()))
        p.setFont(base_font(self._axis_font - 1, bold=True))
        p.setPen(qc("alert"))
        p.drawText(QRectF(rx - 40, plot.top() - 22, 80, 18),
                   Qt.AlignHCenter | Qt.AlignVCenter, f"目前 {self._cur} 時")

        # legend -----------------------------------------------------------
        if self._legend:
            p.setFont(base_font(self._axis_font - 1))
            items = [(c, l) for _k, c, l in self._bars + self._lines]
            if self._show_forecast:
                items.append(("in", "AI 預測"))
            x = plot.left()
            y = H - legend_h + 6
            for ckey, label in items:
                p.setPen(Qt.NoPen)
                p.setBrush(qc(ckey))
                p.drawRect(QRectF(x, y + 2, 12, 12))
                p.setPen(qc("textDim"))
                tw = p.fontMetrics().horizontalAdvance(label)
                p.drawText(QRectF(x + 16, y, tw + 6, 16),
                           Qt.AlignLeft | Qt.AlignVCenter, label)
                x += 16 + tw + 22
        p.end()


class MiniBarChart(QWidget):
    """Tiny sparkline for the 工地卡片 (spec §4.1 迷你趨勢圖)."""

    def __init__(self, color_key="in", anomaly_at=-1, parent=None):
        super().__init__(parent)
        self._vals: list[float] = []
        self._color = color_key
        self._anom = anomaly_at
        self.setFixedHeight(30)

    def set_values(self, vals, anomaly_at=-1):
        self._vals = list(vals or [])
        self._anom = anomaly_at
        self.update()

    def paintEvent(self, _ev):
        if not self._vals:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        W, H = self.width(), self.height()
        n = len(self._vals)
        mx = max(self._vals) or 1
        bw = W / n
        for i, v in enumerate(self._vals):
            h = (v / mx) * (H - 2)
            is_anom = i == self._anom
            col = qc("alert") if is_anom else qc(self._color, 0.6)
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawRect(QRectF(i * bw + 1, H - h, bw - 2, h))
        p.end()

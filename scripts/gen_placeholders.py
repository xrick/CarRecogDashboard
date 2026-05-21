"""Generate car.png and person.png placeholder thumbnails for EventRow.

Produces deep-blue silhouette PNGs that match the dashboard's dark theme
(bgCard #0F1B33 + borderLight #2A4373 outline). Re-run when palette changes.

    source run_env.sh && python scripts/gen_placeholders.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import QApplication

OUT_DIR = Path(__file__).resolve().parents[1] / "assets" / "placeholders"


def _bg_gradient(w: int, h: int) -> QLinearGradient:
    g = QLinearGradient(0, 0, 0, h)
    g.setColorAt(0, QColor("#1A2D52"))
    g.setColorAt(1, QColor("#0F1B33"))
    return g


def make_car(path: Path, w: int = 256, h: int = 176) -> None:
    pm = QPixmap(w, h)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)

    p.setBrush(_bg_gradient(w, h))
    p.setPen(QPen(QColor("#2A4373"), 2))
    p.drawRoundedRect(1, 1, w - 2, h - 2, 12, 12)

    sx, sy = w / 256.0, h / 176.0
    silhouette = QColor(143, 163, 199, 220)
    p.setPen(Qt.NoPen)
    p.setBrush(silhouette)

    body = QPainterPath()
    body.moveTo(36 * sx, 116 * sy)
    body.lineTo(52 * sx, 78 * sy)
    body.quadTo(60 * sx, 60 * sy, 84 * sx, 56 * sy)
    body.lineTo(168 * sx, 56 * sy)
    body.quadTo(190 * sx, 60 * sy, 208 * sx, 80 * sy)
    body.lineTo(224 * sx, 116 * sy)
    body.lineTo(224 * sx, 136 * sy)
    body.quadTo(224 * sx, 144 * sy, 216 * sx, 144 * sy)
    body.lineTo(40 * sx, 144 * sy)
    body.quadTo(32 * sx, 144 * sy, 32 * sx, 136 * sy)
    body.closeSubpath()
    p.drawPath(body)

    p.setBrush(QColor(20, 36, 66, 230))
    win = QPainterPath()
    win.moveTo(70 * sx, 88 * sy)
    win.quadTo(82 * sx, 70 * sy, 100 * sx, 70 * sy)
    win.lineTo(156 * sx, 70 * sy)
    win.quadTo(176 * sx, 70 * sy, 188 * sx, 88 * sy)
    win.lineTo(188 * sx, 108 * sy)
    win.lineTo(70 * sx, 108 * sy)
    win.closeSubpath()
    p.drawPath(win)
    p.setPen(QPen(QColor(60, 90, 140, 160), 1))
    p.drawLine(int(128 * sx), int(72 * sy), int(128 * sx), int(108 * sy))

    p.setPen(Qt.NoPen)
    p.setBrush(QColor(8, 14, 28))
    wheel_r = 16 * min(sx, sy)
    for cx in (74, 182):
        p.drawEllipse(QPointF(cx * sx, 144 * sy), wheel_r, wheel_r)
    p.setBrush(QColor(143, 163, 199, 180))
    for cx in (74, 182):
        p.drawEllipse(QPointF(cx * sx, 144 * sy), wheel_r * 0.45, wheel_r * 0.45)

    p.setBrush(QColor(255, 224, 102, 230))
    p.drawRoundedRect(QRectF(34 * sx, 104 * sy, 10 * sx, 8 * sy), 1.5, 1.5)
    p.setBrush(QColor(248, 113, 113, 230))
    p.drawRoundedRect(QRectF(212 * sx, 104 * sy, 10 * sx, 8 * sy), 1.5, 1.5)

    p.end()
    pm.save(str(path), "PNG")
    print(f"  wrote {path.relative_to(OUT_DIR.parent.parent)} ({w}x{h})")


def make_person(path: Path, w: int = 256, h: int = 256) -> None:
    pm = QPixmap(w, h)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)

    p.setBrush(_bg_gradient(w, h))
    p.setPen(QPen(QColor("#2A4373"), 2))
    p.drawEllipse(1, 1, w - 2, h - 2)

    s = min(w, h)
    silhouette = QColor(143, 163, 199, 220)
    p.setPen(Qt.NoPen)
    p.setBrush(silhouette)

    head_r = s * 0.18
    head_cx, head_cy = w / 2, h * 0.36
    p.drawEllipse(QPointF(head_cx, head_cy), head_r, head_r)

    helmet = QPainterPath()
    helmet.moveTo(head_cx - head_r * 1.25, head_cy - head_r * 0.05)
    helmet.quadTo(head_cx, head_cy - head_r * 1.85,
                  head_cx + head_r * 1.25, head_cy - head_r * 0.05)
    helmet.lineTo(head_cx + head_r * 1.25, head_cy + head_r * 0.05)
    helmet.lineTo(head_cx - head_r * 1.25, head_cy + head_r * 0.05)
    helmet.closeSubpath()
    p.setBrush(QColor(245, 158, 11, 230))
    p.drawPath(helmet)
    p.setPen(QPen(QColor(0, 0, 0, 90), 1))
    p.drawLine(QPointF(head_cx - head_r * 1.25, head_cy + head_r * 0.04),
               QPointF(head_cx + head_r * 1.25, head_cy + head_r * 0.04))

    p.setPen(Qt.NoPen)
    p.setBrush(silhouette)
    shoulder = QPainterPath()
    shoulder.moveTo(w * 0.18, h)
    shoulder.quadTo(w * 0.20, h * 0.66, w * 0.36, h * 0.62)
    shoulder.quadTo(w * 0.5, h * 0.56, w * 0.64, h * 0.62)
    shoulder.quadTo(w * 0.80, h * 0.66, w * 0.82, h)
    shoulder.closeSubpath()
    p.drawPath(shoulder)

    p.setBrush(QColor(34, 211, 238, 200))
    badge_w, badge_h = s * 0.22, s * 0.07
    badge_x = w / 2 - badge_w / 2
    badge_y = h * 0.78
    p.drawRoundedRect(QRectF(badge_x, badge_y, badge_w, badge_h), 4, 4)

    p.end()
    pm.save(str(path), "PNG")
    print(f"  wrote {path.relative_to(OUT_DIR.parent.parent)} ({w}x{h})")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    print(f"Generating placeholders into {OUT_DIR}")
    make_car(OUT_DIR / "car.png")
    make_person(OUT_DIR / "person.png")
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

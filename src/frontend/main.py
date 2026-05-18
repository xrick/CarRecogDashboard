"""
Standalone 工地看板 — PyQt5 entry point.

Implements the spec §7 操作設計: 工地切換 / 畫面切換 / 自動輪播 / 手動刷新 /
全螢幕 / 控制列收合 / 離線提示, plus the §5 即時快訊跳卡 overlay driven by
the backend SSE push channel.

Keyboard (spec §9):
  1-6   切換看板模式      ← →  切換工地
  R     立即刷新          F11  全螢幕
  Esc   顯示/隱藏控制列    Q    結束

Run:  python -m src.frontend.main
Env:  CARDASH_API  (default http://127.0.0.1:8000)
"""
from __future__ import annotations

import sys
from collections import OrderedDict

from PyQt5.QtCore import QEvent, Qt, QTimer
from PyQt5.QtWidgets import (
    QApplication, QComboBox, QHBoxLayout, QLabel, QPushButton, QStackedWidget,
    QVBoxLayout, QWidget,
)

from .api_client import ApiPoller, EventStream
from .theme import COLORS, base_font, init_fonts
from .views import VIEW_CLASSES
from .widgets import FlashCard, _lbl

_H = COLORS

MAIN_TABS = [("dashboard", "工地看板", False), ("reserved1", "人員管理", True),
             ("reserved2", "車輛管理", True), ("reserved3", "系統設定", True)]
SUB_TABS = [("overview", "全工地總覽", "1"), ("site", "單一工地", "2"),
            ("vehicle", "車輛看板", "3"), ("personnel", "人員看板", "4"),
            ("trend", "趨勢全螢幕", "5"), ("alert", "異常事件牆", "6")]
ROTATION = {"overview": 30, "site": 30, "vehicle": 20, "personnel": 20,
            "trend": 30, "alert": 20}
ROTATION_ORDER = ["overview", "site", "vehicle", "personnel"]


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("中華航空AI智慧工安辨識事件管理系統 · 工地看板")
        self.resize(1920, 1080)
        self.setStyleSheet(f"background:{_H['bg']};color:{_H['text']};")

        self._sub = "overview"
        self._site = "ALL"
        self._auto = False
        self._countdown = 60
        self._online = True
        self._snapshot: dict = {}
        self._extra_events: "OrderedDict[str, dict]" = OrderedDict()
        self._flash: list[FlashCard] = []

        self._build_ui()
        self._wire_workers()
        self._wire_timers()
        QApplication.instance().installEventFilter(self)

    # ---- UI -------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # offline banner (spec §7 離線提示) — hidden while online
        self.offline = QLabel()
        self.offline.setFont(base_font(13, bold=True))
        self.offline.setAlignment(Qt.AlignCenter)
        self.offline.setStyleSheet(
            f"color:{_H['alert']};background:rgba(248,113,113,0.16);"
            f"border-bottom:1px solid {_H['alert']};padding:6px;")
        self.offline.hide()
        root.addWidget(self.offline)

        # main tab bar
        top = QWidget()
        top.setFixedHeight(44)
        top.setStyleSheet(f"background:{_H['bgTopbar']};"
                          f"border-bottom:1px solid {_H['borderLight']};")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(20, 0, 20, 0)
        tl.setSpacing(4)
        brand = _lbl("◆ SITE BOARD", "in", 13, bold=True)
        tl.addWidget(brand)
        tl.addSpacing(20)
        for tid, name, disabled in MAIN_TABS:
            b = QPushButton(name)
            b.setEnabled(not disabled)
            active = tid == "dashboard"
            b.setStyleSheet(
                f"QPushButton{{background:{'transparent'};border:none;"
                f"border-bottom:2px solid {_H['in'] if active else 'transparent'};"
                f"color:{_H['in'] if active else _H['textDim']};"
                f"padding:12px 18px;font-weight:600;}}"
                f"QPushButton:disabled{{color:{_H['textMuted']};}}")
            tl.addWidget(b)
        tl.addStretch(1)
        self.clock = _lbl("", "textDim", 12, mono=True)
        tl.addWidget(self.clock)
        tl.addSpacing(16)
        self.api_ind = _lbl("● API --", "pass", 12)
        tl.addWidget(self.api_ind)
        root.addWidget(top)

        # sub-tab + control bar
        self.ctrl = QWidget()
        self.ctrl.setFixedHeight(52)
        self.ctrl.setStyleSheet(f"background:{_H['bg']};"
                                f"border-bottom:1px solid {_H['border']};")
        cl = QHBoxLayout(self.ctrl)
        cl.setContentsMargins(20, 0, 20, 0)
        cl.setSpacing(14)
        self.site_box = QComboBox()
        self.site_box.setStyleSheet(
            f"QComboBox{{background:{_H['bgCard']};color:{_H['text']};"
            f"border:1px solid {_H['borderLight']};border-radius:6px;"
            f"padding:6px 12px;min-width:160px;}}"
            f"QComboBox QAbstractItemView{{background:{_H['bgCard']};"
            f"color:{_H['text']};selection-background-color:{_H['bgCardHover']};}}")
        self.site_box.addItem("全部工地", "ALL")
        self.site_box.currentIndexChanged.connect(self._on_site_changed)
        cl.addWidget(self.site_box)
        sep = QWidget()
        sep.setFixedSize(1, 24)
        sep.setStyleSheet(f"background:{_H['border']};")
        cl.addWidget(sep)

        self._tab_btns = {}
        for sid, name, sc in SUB_TABS:
            b = QPushButton(f"{name}  {sc}")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, s=sid: self.set_sub(s))
            self._tab_btns[sid] = b
            cl.addWidget(b)
        cl.addStretch(1)

        self.auto_btn = QPushButton("○ 自動輪播")
        self.auto_btn.setCursor(Qt.PointingHandCursor)
        self.auto_btn.clicked.connect(self._toggle_auto)
        cl.addWidget(self.auto_btn)
        self.cd_lbl = _lbl("刷新倒數 01:00", "textDim", 12, mono=True)
        self.cd_lbl.setStyleSheet(
            f"color:{_H['textDim']};background:{_H['bgCard']};"
            f"border:1px solid {_H['border']};border-radius:6px;padding:6px 10px;")
        cl.addWidget(self.cd_lbl)
        root.addWidget(self.ctrl)

        # content stack
        self.stack = QStackedWidget()
        self.stack.setStyleSheet(f"background:{_H['bg']};")
        wrap = QWidget()
        wrap.setStyleSheet(f"background:{_H['bg']};")
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(16, 16, 16, 16)
        wl.addWidget(self.stack)
        root.addWidget(wrap, 1)

        self._views = {}
        for sid, _n, _s in SUB_TABS:
            v = VIEW_CLASSES[sid]()
            self._views[sid] = v
            self.stack.addWidget(v)

        # flash-card overlay (spec §5) — floats bottom-right
        self.overlay = QWidget(self)
        self.overlay.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.overlay.setStyleSheet("background:transparent;")
        self.ov_layout = QVBoxLayout(self.overlay)
        self.ov_layout.setContentsMargins(0, 0, 0, 0)
        self.ov_layout.setSpacing(12)
        self.ov_layout.addStretch(1)
        self.overlay.hide()

        self._refresh_tab_styles()
        self.set_sub("overview")

    def _refresh_tab_styles(self):
        for sid, btn in self._tab_btns.items():
            on = sid == self._sub
            btn.setStyleSheet(
                f"QPushButton{{background:{_H['bgCardHover'] if on else 'transparent'};"
                f"border:1px solid {_H['in'] if on else 'transparent'};"
                f"color:{_H['in'] if on else _H['textDim']};"
                f"padding:7px 14px;border-radius:6px;"
                f"font-weight:{'600' if on else '500'};}}")
        on = self._auto
        self.auto_btn.setText("◉ 自動輪播中" if on else "○ 自動輪播")
        self.auto_btn.setStyleSheet(
            f"QPushButton{{background:{'rgba(34,211,238,0.15)' if on else 'transparent'};"
            f"border:1px solid {_H['in'] if on else _H['border']};"
            f"color:{_H['in'] if on else _H['textDim']};"
            f"padding:6px 12px;border-radius:6px;font-weight:600;}}")

    # ---- workers --------------------------------------------------------
    def _wire_workers(self):
        self.poller = ApiPoller(interval=60)
        self.poller.data_ready.connect(self._on_data)
        self.poller.online_changed.connect(self._on_online)
        self.poller.start()
        self.stream = EventStream()
        self.stream.new_event.connect(self._on_event)
        self.stream.start()

    def _wire_timers(self):
        self._tick = QTimer(self)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start(1000)
        self._rot = QTimer(self)
        self._rot.setSingleShot(True)
        self._rot.timeout.connect(self._rotate)
        self._hide_ctrl = QTimer(self)
        self._hide_ctrl.setSingleShot(True)
        self._hide_ctrl.timeout.connect(lambda: self.ctrl.setVisible(False))
        self._hide_ctrl.start(5000)

    # ---- data flow ------------------------------------------------------
    def _compose(self) -> dict:
        s = dict(self._snapshot)
        poll_events = s.get("events", [])
        seen = set()
        merged = []
        for e in list(self._extra_events.values())[::-1] + poll_events:
            eid = e.get("event_id")
            if eid in seen:
                continue
            seen.add(eid)
            merged.append(e)
        s["events"] = merged[:30]
        s["site_id"] = self._site
        return s

    def _on_data(self, snap: dict):
        self._snapshot = snap
        self._countdown = 60
        self._views[self._sub].update_state(self._compose())

    def _on_online(self, ok: bool):
        self._online = ok
        if ok:
            self.offline.hide()
            self.api_ind.setText("● API 正常")
            self.api_ind.setStyleSheet(
                f"color:{_H['pass']};background:transparent;")
        else:
            last = self._snapshot.get("status", {}).get("last_success_time", "--")
            self.offline.setText(
                f"⚠ API 連線中斷 · 已保留最後成功資料(最後更新 {last})· 重試中…")
            self.offline.show()
            self.api_ind.setText("● API 斷線")
            self.api_ind.setStyleSheet(
                f"color:{_H['alert']};background:transparent;")

    def _on_event(self, ev: dict):
        eid = ev.get("event_id", "")
        self._extra_events[eid] = ev
        while len(self._extra_events) > 30:
            self._extra_events.popitem(last=False)
        # populate site dropdown lazily from incoming data
        if self.site_box.count() == 1:
            self._populate_sites()
        self._push_flash(ev)
        self._views[self._sub].update_state(self._compose())
        # severe alert interrupts auto-rotation (spec §5 / §9)
        if self._auto and ev.get("status_type") in ("alert", "blacklist"):
            self.set_sub("alert")

    # ---- flash cards ----------------------------------------------------
    def _push_flash(self, ev: dict):
        card = FlashCard(ev)
        card.closed.connect(self._dismiss_flash)
        self._flash.append(card)
        self.ov_layout.addWidget(card)
        while len(self._flash) > 3:
            old = self._flash.pop(0)
            self.ov_layout.removeWidget(old)
            old.deleteLater()
        self.overlay.show()
        self._place_overlay()

    def _dismiss_flash(self, fid: str):
        for c in list(self._flash):
            if c._id == fid:
                self._flash.remove(c)
                self.ov_layout.removeWidget(c)
                c.deleteLater()
        if not self._flash:
            self.overlay.hide()
        self._place_overlay()

    def _place_overlay(self):
        self.overlay.adjustSize()
        w = 384
        h = self.overlay.sizeHint().height()
        self.overlay.setGeometry(self.width() - w - 24,
                                 self.height() - h - 24, w, h)
        self.overlay.raise_()

    # ---- timers ---------------------------------------------------------
    def _on_tick(self):
        from datetime import datetime
        now = datetime.now()
        self.clock.setText(now.strftime("%Y/%m/%d  %H:%M:%S"))
        self._countdown -= 1
        if self._countdown <= 0:
            self._countdown = 60
            self.poller.request_refresh()
        m, sec = divmod(max(self._countdown, 0), 60)
        self.cd_lbl.setText(f"刷新倒數 {m:02d}:{sec:02d}")

    def _rotate(self):
        if not self._auto:
            return
        if self._sub in ROTATION_ORDER:
            i = ROTATION_ORDER.index(self._sub)
            self.set_sub(ROTATION_ORDER[(i + 1) % len(ROTATION_ORDER)])
        else:
            self.set_sub("overview")

    def _toggle_auto(self):
        self._auto = not self._auto
        self._refresh_tab_styles()
        if self._auto:
            self._rot.start(ROTATION[self._sub] * 1000)
        else:
            self._rot.stop()

    # ---- navigation -----------------------------------------------------
    def set_sub(self, sid: str):
        self._sub = sid
        self.stack.setCurrentWidget(self._views[sid])
        self._views[sid].update_state(self._compose())
        self._refresh_tab_styles()
        if self._auto:
            self._rot.start(ROTATION[sid] * 1000)
        self._place_overlay()

    def _populate_sites(self):
        sites = self._snapshot.get("sites_summary", {}).get("sites", [])
        if not sites or self.site_box.count() > 1:
            return
        self.site_box.blockSignals(True)
        for s in sites:
            self.site_box.addItem(s["site_name"], s["site_id"])
        self.site_box.blockSignals(False)

    def _on_site_changed(self, _idx):
        self._site = self.site_box.currentData() or "ALL"
        self._extra_events.clear()
        self.poller.set_site(self._site)
        self.poller.request_refresh()

    # ---- kiosk: keyboard / control bar / fullscreen ---------------------
    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.MouseMove:
            if not self.ctrl.isVisible():
                self.ctrl.setVisible(True)
            self._hide_ctrl.start(5000)
        elif ev.type() == QEvent.KeyPress:
            self._handle_key(ev)
        return super().eventFilter(obj, ev)

    def _handle_key(self, ev):
        k = ev.key()
        txt = ev.text().lower()
        for sid, _n, sc in SUB_TABS:
            if txt == sc:
                self.set_sub(sid)
                return
        if txt == "r":
            self._countdown = 60
            self.poller.request_refresh()
        elif k == Qt.Key_F11:
            self.showNormal() if self.isFullScreen() else self.showFullScreen()
        elif k == Qt.Key_Escape:
            self.ctrl.setVisible(not self.ctrl.isVisible())
            if self.ctrl.isVisible():
                self._hide_ctrl.start(5000)
        elif k in (Qt.Key_Left, Qt.Key_Right):
            n = self.site_box.count()
            if n:
                step = -1 if k == Qt.Key_Left else 1
                self.site_box.setCurrentIndex(
                    (self.site_box.currentIndex() + step) % n)
        elif txt == "q":
            self.close()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._place_overlay()

    def closeEvent(self, ev):
        self.poller.stop()
        self.stream.stop()
        self.poller.wait(1500)
        self.stream.wait(1500)
        super().closeEvent(ev)


def main():
    app = QApplication(sys.argv)
    init_fonts(app)
    w = MainWindow()
    if "--fullscreen" in sys.argv:
        w.showFullScreen()
    else:
        w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

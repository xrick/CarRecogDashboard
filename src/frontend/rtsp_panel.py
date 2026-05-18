"""
RTSP 現場影像面板 (spec §4.1.1).

Reuses the proven rtsp_viewer pattern (claudedocs/rtsp_viewer_說明文件.md):
QThread pulls frames with cv2.VideoCapture (forced RTSP-over-TCP), the GUI
thread only paints — they talk via Qt signals.

OpenCV/PyQt5 plugin conflict (CLAUDE.md): the cv2 wheel ships its own Qt
platform plugin. We import cv2 lazily *after* QApplication exists and never
touch cv2 highgui (only VideoCapture), popping the OpenCV plugin env first and
restoring PyQt5's plugin path after — the documented safe incantation.
"""
from __future__ import annotations

import os

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget

from .theme import COLORS, base_font

_H = COLORS
_cv2 = None
_cv2_tried = False


def _import_cv2():
    """Lazy, conflict-safe cv2 import (CLAUDE.md). Returns module or None."""
    global _cv2, _cv2_tried
    if _cv2_tried:
        return _cv2
    _cv2_tried = True
    saved = (os.environ.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None),
             os.environ.pop("QT_PLUGIN_PATH", None))
    try:
        import cv2  # noqa: E402
        _cv2 = cv2
    except Exception:
        _cv2 = None
    finally:
        try:
            from PyQt5.QtCore import QLibraryInfo
            os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = \
                QLibraryInfo.location(QLibraryInfo.PluginsPath)
        except Exception:
            if saved[0] is not None:
                os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = saved[0]
    return _cv2


class RtspWorker(QThread):
    frame_ready = pyqtSignal(QImage)
    status = pyqtSignal(str)

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self._url = url
        self._running = True

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        cv2 = _import_cv2()
        if cv2 is None:
            self.status.emit("OpenCV 不可用")
            return
        # RTSP over TCP is far more stable than UDP (no torn frames).
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
        while self._running:
            cap = cv2.VideoCapture(self._url, cv2.CAP_FFMPEG)
            if not cap.isOpened():
                self.status.emit("連線中…")
                cap.release()
                if not self._running:
                    break
                self.msleep(2000)
                continue
            self.status.emit("● 連線中")
            fail = 0
            while self._running:
                ok, frame = cap.read()
                if not ok or frame is None:
                    fail += 1
                    if fail > 30:
                        break
                    self.msleep(30)
                    continue
                fail = 0
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, _ = rgb.shape
                img = QImage(rgb.data, w, h, 3 * w,
                             QImage.Format_RGB888).copy()
                self.frame_ready.emit(img)
                self.msleep(25)  # ~40fps cap; sub-stream is usually <=15fps
            cap.release()
            if self._running:
                self.status.emit("斷線重連…")
                self.msleep(1500)


class RtspPanel(QWidget):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"background:{_H['bgCard']};border:1px solid {_H['border']};"
            f"border-radius:8px;")
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 6, 8, 8)
        v.setSpacing(6)
        self._title = QLabel(title)
        self._title.setFont(base_font(12, bold=True))
        self._title.setStyleSheet(f"color:{_H['textDim']};background:transparent;")
        v.addWidget(self._title)
        self._video = QLabel("● 連線中…")
        self._video.setAlignment(Qt.AlignCenter)
        self._video.setMinimumSize(320, 180)
        self._video.setStyleSheet(
            f"color:{_H['textMuted']};background:#050B1A;"
            f"border:1px solid {_H['border']};border-radius:4px;")
        v.addWidget(self._video, 1)
        self._worker: RtspWorker | None = None

    def start(self, url: str) -> None:
        self.stop()
        self._worker = RtspWorker(url)
        self._worker.frame_ready.connect(self._on_frame)
        self._worker.status.connect(
            lambda s: self._title.setText(f"{self._title.text().split('  ')[0]}  {s}"))
        self._worker.start()

    def stop(self) -> None:
        if self._worker is not None:
            self._worker.stop()
            self._worker.wait(2000)
            self._worker = None

    def _on_frame(self, img: QImage) -> None:
        pm = QPixmap.fromImage(img).scaled(
            self._video.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._video.setPixmap(pm)


class RtspView(QWidget):
    """現場影像 grid. Unlike the other views this does NOT clear-and-rebuild on
    every poll — it diffs the camera list and only restarts workers when the
    stream set actually changes (continuous video must not reconnect each tick).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{_H['bg']};")
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._grid_host = QWidget()
        self._grid_host.setStyleSheet("background:transparent;")
        self._grid = QGridLayout(self._grid_host)
        self._grid.setSpacing(12)
        self._root.addWidget(self._grid_host)
        self._placeholder = QLabel(
            "未設定相機（simulate 模式）— 於 config/cameras.json 設定後此處顯示 RTSP 即時影像")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setWordWrap(True)
        self._placeholder.setFont(base_font(15))
        self._placeholder.setStyleSheet(
            f"color:{_H['textMuted']};background:transparent;")
        self._root.addWidget(self._placeholder)
        self._panels: list[RtspPanel] = []
        self._urls: list[str] = []
        self._visible = False

    # called by MainWindow like every other view
    def update_state(self, state: dict) -> None:
        cams = state.get("cameras", []) or []
        urls = [c.get("rtsp_url", "") for c in cams if c.get("rtsp_url")]
        if urls == self._urls:
            return  # unchanged -> keep workers running, do nothing
        self._urls = urls
        self._rebuild(cams)

    def _rebuild(self, cams: list[dict]) -> None:
        for p in self._panels:
            p.stop()
            p.setParent(None)
            p.deleteLater()
        self._panels = []
        while self._grid.count():
            self._grid.takeAt(0)
        if not cams:
            self._placeholder.show()
            self._grid_host.hide()
            return
        self._placeholder.hide()
        self._grid_host.show()
        cols = 1 if len(cams) == 1 else 2
        for i, c in enumerate(cams):
            title = (f"{c.get('site_id', '')} · {c.get('host', '')} "
                     f"CH{c.get('channel', 1)} "
                     f"({'進' if c.get('role') == 'entry' else '出'})")
            p = RtspPanel(title)
            self._panels.append(p)
            self._grid.addWidget(p, i // cols, i % cols)
        if self._visible:
            self._start_all()

    def _start_all(self) -> None:
        for p, url in zip(self._panels, self._urls):
            p.start(url)

    def _stop_all(self) -> None:
        for p in self._panels:
            p.stop()

    def showEvent(self, e):
        super().showEvent(e)
        self._visible = True
        self._start_all()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._visible = False
        self._stop_all()

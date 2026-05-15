"""
RTSP 壓力測試程式：8 個獨立視窗同時連同一台相機
目的：測試
  1. 網路頻寬上限（8 路 1080p H.264 同時拉）
  2. CPU 解碼能力
  3. 相機端的並發 RTSP session 上限（許多廠商有限制，例如 4 或 10）
  4. Qt + OpenCV 多視窗渲染穩定性

依賴：PyQt5, opencv-python（或 opencv-python-headless）

URL 格式（PDF 規範 4.1.1）：
    rtsp://<user>:<pwd>@<server>:<port>/cam/realmonitor?channel=N&subtype=M
"""

import sys
import os

# 必須在 import cv2 之前：移除 OpenCV 自帶的 Qt plugin，避免與 PyQt5 衝突
os.environ.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)
os.environ.pop("QT_PLUGIN_PATH", None)

import cv2
import time
import psutil
from datetime import datetime
from collections import deque

from PyQt5.QtCore import QLibraryInfo
os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = QLibraryInfo.location(
    QLibraryInfo.PluginsPath
)

from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton,
    QLineEdit, QVBoxLayout, QHBoxLayout, QGridLayout, QSpinBox,
    QComboBox, QGroupBox, QMessageBox
)


# ===== 預設參數 =====
DEFAULT_HOST = "192.168.0.51"
DEFAULT_PORT = 554
DEFAULT_USER = "admin"
DEFAULT_PWD = "ai123456"
NUM_WINDOWS = 8


def build_rtsp_url(host, port, user, pwd, channel, subtype):
    return (
        f"rtsp://{user}:{pwd}@{host}:{port}"
        f"/cam/realmonitor?channel={channel}&subtype={subtype}"
    )


# ============================================================
# Worker：每個視窗一條，獨立拉 RTSP，並回報詳細統計
# ============================================================
class RtspWorker(QThread):
    frame_ready = pyqtSignal(int, object)
    stats_update = pyqtSignal(int, dict)   # 詳細統計
    error = pyqtSignal(int, str)
    finished_signal = pyqtSignal(int)

    def __init__(self, worker_id, rtsp_url, parent=None):
        super().__init__(parent)
        self.worker_id = worker_id
        self.rtsp_url = rtsp_url
        self._running = False

    def run(self):
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
            "rtsp_transport;tcp|stimeout;5000000"
        )

        t_connect_start = time.time()
        cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

        if not cap.isOpened():
            self.error.emit(self.worker_id, "連線失敗")
            self.finished_signal.emit(self.worker_id)
            return

        connect_time = time.time() - t_connect_start
        src_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

        self.stats_update.emit(self.worker_id, {
            "event": "connected",
            "connect_ms": connect_time * 1000,
            "src_fps": src_fps,
            "resolution": f"{width}x{height}",
        })

        self._running = True
        frame_count = 0
        total_frames = 0
        dropped = 0
        bytes_total = 0
        last_log = time.time()
        last_frame_time = time.time()
        frame_intervals = deque(maxlen=60)

        while self._running:
            t0 = time.time()
            ok, frame = cap.read()
            t1 = time.time()
            read_latency_ms = (t1 - t0) * 1000

            if not ok or frame is None:
                dropped += 1
                # 不重連，壓力測試直接記錄掉幀
                if dropped > 30:
                    self.error.emit(self.worker_id, "連續讀取失敗")
                    break
                continue

            # 統計
            now = time.time()
            frame_intervals.append(now - last_frame_time)
            last_frame_time = now

            frame_count += 1
            total_frames += 1
            # 估算位元組（每張畫面 raw size）
            bytes_total += frame.nbytes

            self.frame_ready.emit(self.worker_id, frame)

            # 每秒回報一次
            if now - last_log >= 1.0:
                actual_fps = frame_count / (now - last_log)
                # 抖動：frame interval 標準差
                if len(frame_intervals) > 5:
                    mean_iv = sum(frame_intervals) / len(frame_intervals)
                    var = sum((x - mean_iv) ** 2 for x in frame_intervals) / len(frame_intervals)
                    jitter_ms = (var ** 0.5) * 1000
                else:
                    jitter_ms = 0

                self.stats_update.emit(self.worker_id, {
                    "event": "tick",
                    "fps": actual_fps,
                    "total_frames": total_frames,
                    "dropped": dropped,
                    "jitter_ms": jitter_ms,
                    "read_latency_ms": read_latency_ms,
                    "mbps": (bytes_total * 8 / 1_000_000) / (now - last_log),
                })
                last_log = now
                frame_count = 0
                bytes_total = 0

        cap.release()
        self.stats_update.emit(self.worker_id, {
            "event": "stopped",
            "total_frames": total_frames,
            "dropped": dropped,
        })
        self.finished_signal.emit(self.worker_id)

    def stop(self):
        self._running = False


# ============================================================
# StreamWindow：每路串流自己一個獨立視窗
# ============================================================
class StreamWindow(QMainWindow):
    closed = pyqtSignal(int)

    def __init__(self, worker_id, parent=None):
        super().__init__(parent)
        self.worker_id = worker_id
        self.setWindowTitle(f"Stress Test - Window #{worker_id + 1}")
        self.resize(480, 380)

        central = QWidget()
        self.setCentralWidget(central)

        # 影像顯示
        self.video_label = QLabel("等待連線…")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setStyleSheet("background:#111; color:#666;")
        self.video_label.setMinimumSize(320, 200)

        # 統計面板（多行）
        self.stats_label = QLabel("—")
        self.stats_label.setStyleSheet(
            "background:#1e1e1e; color:#0f0; font-family:monospace; "
            "padding:4px; font-size:11px;"
        )
        self.stats_label.setMinimumHeight(90)
        self.stats_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        layout.addWidget(self.video_label, 1)
        layout.addWidget(self.stats_label)

        # 累計資訊
        self.connect_ms = 0
        self.resolution = "?"
        self.src_fps = 0

    def update_frame(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        img = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
        pix = QPixmap.fromImage(img).scaled(
            self.video_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.video_label.setPixmap(pix)

    def update_stats(self, stats):
        ev = stats.get("event")
        if ev == "connected":
            self.connect_ms = stats["connect_ms"]
            self.resolution = stats["resolution"]
            self.src_fps = stats["src_fps"]
            self.stats_label.setText(
                f"[連線成功] {self.resolution} @ {self.src_fps:.0f}fps\n"
                f"連線耗時: {self.connect_ms:.0f} ms\n"
                f"等待第一張畫面…"
            )
        elif ev == "tick":
            self.stats_label.setText(
                f"連線: {self.connect_ms:.0f}ms  解析度: {self.resolution} (源 {self.src_fps:.0f}fps)\n"
                f"實際 FPS: {stats['fps']:>5.1f}    累計幀數: {stats['total_frames']}\n"
                f"位元率: {stats['mbps']:>6.2f} Mbps  掉幀: {stats['dropped']}\n"
                f"抖動 σ: {stats['jitter_ms']:>5.1f}ms  讀取延遲: {stats['read_latency_ms']:>5.1f}ms"
            )
        elif ev == "stopped":
            self.stats_label.setText(
                self.stats_label.text() +
                f"\n[已停止] 總幀數: {stats['total_frames']} 掉幀: {stats['dropped']}"
            )

    def set_error(self, msg):
        self.stats_label.setStyleSheet(
            "background:#3a1010; color:#f66; font-family:monospace; padding:4px;"
        )
        self.stats_label.setText(f"⚠ 錯誤：{msg}")

    def closeEvent(self, event):
        self.closed.emit(self.worker_id)
        event.accept()


# ============================================================
# ControlPanel：總控視窗，啟動 / 停止 / 顯示總體統計
# ============================================================
class ControlPanel(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RTSP 8 路壓力測試 - 總控")
        self.resize(560, 360)

        self.workers = {}
        self.windows = {}
        self.start_time = None
        self.stats_cache = {}  # worker_id -> 最新 stats

        central = QWidget()
        self.setCentralWidget(central)

        # 參數
        self.host_edit = QLineEdit(DEFAULT_HOST)
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(DEFAULT_PORT)
        self.user_edit = QLineEdit(DEFAULT_USER)
        self.pwd_edit = QLineEdit(DEFAULT_PWD)
        self.pwd_edit.setEchoMode(QLineEdit.Password)

        self.subtype_combo = QComboBox()
        self.subtype_combo.addItem("主碼流 (subtype=0) - 1080p 高負載", 0)
        self.subtype_combo.addItem("辅码流 1 (subtype=1) - 低負載", 1)
        self.subtype_combo.addItem("辅码流 2 (subtype=2)", 2)
        self.subtype_combo.setCurrentIndex(0)  # 壓力測試預設主碼流

        self.num_spin = QSpinBox()
        self.num_spin.setRange(1, 16)
        self.num_spin.setValue(NUM_WINDOWS)

        self.btn_start = QPushButton("開始壓力測試")
        self.btn_stop = QPushButton("全部停止")
        self.btn_stop.setEnabled(False)

        param_group = QGroupBox("目標參數（所有視窗連同一台）")
        pl = QGridLayout()
        pl.addWidget(QLabel("Host:"), 0, 0)
        pl.addWidget(self.host_edit, 0, 1, 1, 3)
        pl.addWidget(QLabel("Port:"), 1, 0)
        pl.addWidget(self.port_spin, 1, 1)
        pl.addWidget(QLabel("User:"), 1, 2)
        pl.addWidget(self.user_edit, 1, 3)
        pl.addWidget(QLabel("Pwd:"), 2, 0)
        pl.addWidget(self.pwd_edit, 2, 1)
        pl.addWidget(QLabel("碼流:"), 2, 2)
        pl.addWidget(self.subtype_combo, 2, 3)
        pl.addWidget(QLabel("視窗數:"), 3, 0)
        pl.addWidget(self.num_spin, 3, 1)
        param_group.setLayout(pl)

        action_bar = QHBoxLayout()
        action_bar.addWidget(self.btn_start)
        action_bar.addWidget(self.btn_stop)
        action_bar.addStretch(1)

        # 總體統計面板
        self.summary_label = QLabel("尚未啟動")
        self.summary_label.setStyleSheet(
            "background:#1e1e1e; color:#0ff; font-family:monospace; "
            "padding:8px; font-size:12px;"
        )
        self.summary_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.summary_label.setMinimumHeight(160)

        layout = QVBoxLayout(central)
        layout.addWidget(param_group)
        layout.addLayout(action_bar)
        layout.addWidget(QLabel("總體統計（每秒更新）："))
        layout.addWidget(self.summary_label, 1)

        # signals
        self.btn_start.clicked.connect(self.on_start)
        self.btn_stop.clicked.connect(self.on_stop)

        # 系統資源監測 Timer
        self.summary_timer = QTimer(self)
        self.summary_timer.timeout.connect(self.update_summary)
        self.summary_timer.setInterval(1000)

        # CPU 取樣需先 call 一次
        psutil.cpu_percent(interval=None)
        self.proc = psutil.Process(os.getpid())
        self.proc.cpu_percent(interval=None)

    def on_start(self):
        host = self.host_edit.text().strip()
        port = self.port_spin.value()
        user = self.user_edit.text().strip()
        pwd = self.pwd_edit.text()
        subtype = self.subtype_combo.currentData()
        num = self.num_spin.value()

        if not host or not user:
            QMessageBox.warning(self, "提示", "請填入 Host 與 User")
            return

        # 所有視窗連同一台相機，channel=1
        url = build_rtsp_url(host, port, user, pwd, 1, subtype)

        self.start_time = time.time()
        self.stats_cache = {}

        for i in range(num):
            win = StreamWindow(i)
            win.closed.connect(self.on_window_closed)
            # 視窗錯開排列
            row, col = divmod(i, 4)
            win.move(50 + col * 490, 50 + row * 400)
            win.show()
            self.windows[i] = win

            worker = RtspWorker(i, url)
            worker.frame_ready.connect(self.on_frame)
            worker.stats_update.connect(self.on_stats)
            worker.error.connect(self.on_error)
            worker.finished_signal.connect(self.on_worker_finished)
            self.workers[i] = worker
            worker.start()

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.summary_timer.start()

    def on_stop(self):
        for worker in list(self.workers.values()):
            worker.stop()
        # 不直接關視窗，等 worker finished 信號

    def on_frame(self, worker_id, frame):
        win = self.windows.get(worker_id)
        if win:
            win.update_frame(frame)

    def on_stats(self, worker_id, stats):
        self.stats_cache[worker_id] = stats
        win = self.windows.get(worker_id)
        if win:
            win.update_stats(stats)

    def on_error(self, worker_id, msg):
        win = self.windows.get(worker_id)
        if win:
            win.set_error(msg)

    def on_worker_finished(self, worker_id):
        worker = self.workers.pop(worker_id, None)
        if worker is not None:
            worker.wait(2000)
            worker.deleteLater()

        if not self.workers:
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self.summary_timer.stop()
            self.update_summary()  # 最後一次更新

    def on_window_closed(self, worker_id):
        # 使用者手動關閉某個視窗 → 停掉對應 worker
        worker = self.workers.get(worker_id)
        if worker:
            worker.stop()
        self.windows.pop(worker_id, None)

    def update_summary(self):
        if self.start_time is None:
            return
        elapsed = time.time() - self.start_time

        total_fps = 0.0
        total_mbps = 0.0
        total_dropped = 0
        total_frames = 0
        active = 0
        for s in self.stats_cache.values():
            if s.get("event") == "tick":
                total_fps += s.get("fps", 0)
                total_mbps += s.get("mbps", 0)
                active += 1
            total_dropped += s.get("dropped", 0)
            total_frames += s.get("total_frames", 0)

        cpu = psutil.cpu_percent(interval=None)
        proc_cpu = self.proc.cpu_percent(interval=None)
        mem_mb = self.proc.memory_info().rss / 1024 / 1024

        self.summary_label.setText(
            f"執行時間:        {elapsed:>8.1f} 秒\n"
            f"運作中視窗:      {active} / {len(self.windows)}\n"
            f"\n"
            f"總 FPS:          {total_fps:>8.1f}  (所有視窗加總)\n"
            f"總頻寬:          {total_mbps:>8.2f} Mbps  (解碼後 raw)\n"
            f"累計幀數:        {total_frames:>8}\n"
            f"累計掉幀:        {total_dropped:>8}\n"
            f"\n"
            f"系統 CPU:        {cpu:>8.1f} %\n"
            f"本程式 CPU:      {proc_cpu:>8.1f} %\n"
            f"本程式記憶體:    {mem_mb:>8.1f} MB"
        )

    def closeEvent(self, event):
        for worker in list(self.workers.values()):
            worker.stop()
        for worker in list(self.workers.values()):
            worker.wait(2000)
        for win in list(self.windows.values()):
            win.close()
        event.accept()


def main():
    app = QApplication(sys.argv)
    panel = ControlPanel()
    panel.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

"""
RTSP 八路串流並行檢視程式（基於 PDF API 規範 V3）
依賴：PyQt5, opencv-python（或 opencv-python-headless）
安裝：pip install PyQt5 opencv-python-headless

URL 格式（取自規範 4.1.1）：
    rtsp://<user>:<pwd>@<server>:<port>/cam/realmonitor?channel=N&subtype=M
    - channel: 通道號，從 1 開始
    - subtype: 0=主碼流, 1=辅码流1, 2=辅码流2

預設使用 subtype=1（辅码流）以降低 8 路同時顯示的網路與解碼負擔。
"""

import sys
import os

# 必須在 import cv2 之前：移除 OpenCV 自帶的 Qt plugin，避免與 PyQt5 衝突
os.environ.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)
os.environ.pop("QT_PLUGIN_PATH", None)

import cv2
import time
from datetime import datetime

from PyQt5.QtCore import QLibraryInfo
os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = QLibraryInfo.location(
    QLibraryInfo.PluginsPath
)

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton,
    QLineEdit, QVBoxLayout, QHBoxLayout, QGridLayout, QFileDialog,
    QMessageBox, QStatusBar, QSpinBox, QComboBox, QGroupBox
)


# ===== 預設連線參數（依據 PDF 規範 4.1.1）=====
# 路線 B：8 台獨立相機，每台都用 channel=1
DEFAULT_HOSTS = [
    "192.168.0.51",
    "192.168.0.52",
    "192.168.0.53",
    "192.168.0.54",
    "192.168.0.55",
    "192.168.0.56",
    "192.168.0.57",
    "192.168.0.58",
]
DEFAULT_PORT = 554
DEFAULT_USER = "admin"
DEFAULT_PWD = "ai123456"
NUM_STREAMS = 4


def build_rtsp_url(host, port, user, pwd, channel, subtype):
    """依據 PDF 規範 4.1.1 組出 RTSP URL。"""
    return (
        f"rtsp://{user}:{pwd}@{host}:{port}"
        f"/cam/realmonitor?channel={channel}&subtype={subtype}"
    )


class RtspWorker(QThread):
    """單一串流的背景執行緒：讀取 RTSP，可選擇錄影。"""

    frame_ready = pyqtSignal(int, object)   # (worker_id, BGR frame)
    status = pyqtSignal(int, str)           # (worker_id, msg)
    error = pyqtSignal(int, str)
    finished_signal = pyqtSignal(int)

    def __init__(self, worker_id, rtsp_url, parent=None):
        super().__init__(parent)
        self.worker_id = worker_id
        self.rtsp_url = rtsp_url
        self._running = False
        self._recording = False
        self._writer = None
        self._record_path = None
        self._fps_estimate = 25.0

    def run(self):
        # FFmpeg backend + TCP 傳輸（多路並行時 UDP 容易丟包）
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
            "rtsp_transport;tcp|stimeout;5000000"
        )

        self.status.emit(self.worker_id, "連線中…")
        cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
        # 降低內部緩衝，減少延遲（部分 FFmpeg 版本支援）
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

        if not cap.isOpened():
            self.error.emit(self.worker_id, "無法開啟串流")
            self.finished_signal.emit(self.worker_id)
            return

        src_fps = cap.get(cv2.CAP_PROP_FPS)
        if src_fps and 1 < src_fps < 120:
            self._fps_estimate = src_fps

        self.status.emit(self.worker_id, f"已連線 FPS≈{self._fps_estimate:.0f}")

        self._running = True
        last_log = time.time()
        frame_count = 0
        retry_count = 0

        while self._running:
            ok, frame = cap.read()
            if not ok or frame is None:
                retry_count += 1
                self.status.emit(self.worker_id, f"讀取失敗，重連 #{retry_count}")
                cap.release()
                time.sleep(1.0)
                if not self._running:
                    break
                cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
                if not cap.isOpened():
                    if retry_count >= 5:
                        self.error.emit(self.worker_id, "重連多次失敗")
                        break
                    continue
                continue

            retry_count = 0
            frame_count += 1
            self.frame_ready.emit(self.worker_id, frame)

            if self._recording and self._writer is not None:
                try:
                    self._writer.write(frame)
                except Exception as e:
                    self.error.emit(self.worker_id, f"寫入錯誤：{e}")

            now = time.time()
            if now - last_log >= 3.0:
                actual_fps = frame_count / (now - last_log)
                tag = " [REC]" if self._recording else ""
                self.status.emit(
                    self.worker_id,
                    f"{frame.shape[1]}x{frame.shape[0]} {actual_fps:.0f}fps{tag}"
                )
                last_log = now
                frame_count = 0

        cap.release()
        self._close_writer()
        self.status.emit(self.worker_id, "已停止")
        self.finished_signal.emit(self.worker_id)

    def stop(self):
        self._running = False

    def start_recording(self, output_path):
        if self._recording:
            return
        self._record_path = output_path
        self._writer = None
        self._recording = True
        self.frame_ready.connect(self._maybe_init_writer)

    def _maybe_init_writer(self, worker_id, frame):
        if worker_id != self.worker_id:
            return
        if self._recording and self._writer is None and self._record_path:
            h, w = frame.shape[:2]
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            self._writer = cv2.VideoWriter(
                self._record_path, fourcc, self._fps_estimate, (w, h)
            )
            if not self._writer.isOpened():
                self.error.emit(self.worker_id, "VideoWriter 開啟失敗")
                self._writer = None
                self._recording = False

    def stop_recording(self):
        if not self._recording:
            return None
        self._recording = False
        path = self._record_path
        self._close_writer()
        try:
            self.frame_ready.disconnect(self._maybe_init_writer)
        except TypeError:
            pass
        return path

    def _close_writer(self):
        if self._writer is not None:
            try:
                self._writer.release()
            except Exception:
                pass
            self._writer = None


class StreamTile(QWidget):
    """單一串流的顯示格：影像 + 標題 + 狀態列。"""

    def __init__(self, worker_id, parent=None):
        super().__init__(parent)
        self.worker_id = worker_id
        self._last_frame = None

        self.title_label = QLabel(f"CH {worker_id + 1}")
        self.title_label.setStyleSheet(
            "color:#fff; background:#2b2b2b; padding:2px 6px; font-weight:bold;"
        )

        self.video_label = QLabel("尚未連線")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setStyleSheet("background:#111; color:#666;")
        self.video_label.setMinimumSize(320, 180)

        self.status_label = QLabel("—")
        self.status_label.setStyleSheet(
            "color:#bbb; background:#222; padding:1px 6px; font-size:10px;"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.title_label)
        layout.addWidget(self.video_label, 1)
        layout.addWidget(self.status_label)

    def update_frame(self, frame):
        self._last_frame = frame
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        img = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
        pix = QPixmap.fromImage(img).scaled(
            self.video_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.video_label.setPixmap(pix)

    def set_status(self, text):
        self.status_label.setText(text)

    def set_title(self, text):
        self.title_label.setText(text)

    def clear(self):
        self.video_label.setText("已中斷")
        self.video_label.setPixmap(QPixmap())
        self._last_frame = None


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"RTSP {NUM_STREAMS} 路並行檢視")
        self.resize(1280, 800)

        self.workers = {}    # worker_id -> RtspWorker
        self.tiles = {}      # worker_id -> StreamTile

        central = QWidget()
        self.setCentralWidget(central)

        # ===== 上方控制列 =====
        self.host_edits = []
        for ip in DEFAULT_HOSTS:
            edit = QLineEdit(ip)
            edit.setMaximumWidth(140)
            self.host_edits.append(edit)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(DEFAULT_PORT)
        self.user_edit = QLineEdit(DEFAULT_USER)
        self.pwd_edit = QLineEdit(DEFAULT_PWD)
        self.pwd_edit.setEchoMode(QLineEdit.Password)

        self.subtype_combo = QComboBox()
        self.subtype_combo.addItem("主碼流 (subtype=0)", 0)
        self.subtype_combo.addItem("辅码流 1 (subtype=1)", 1)
        self.subtype_combo.addItem("辅码流 2 (subtype=2)", 2)
        self.subtype_combo.setCurrentIndex(1)  # 預設辅码流以減輕負擔

        self.num_spin = QSpinBox()
        self.num_spin.setRange(1, NUM_STREAMS)
        self.num_spin.setValue(NUM_STREAMS)

        self.btn_connect_all = QPushButton("全部連線")
        self.btn_disconnect_all = QPushButton("全部中斷")
        self.btn_record_all = QPushButton("全部錄影")
        self.btn_disconnect_all.setEnabled(False)
        self.btn_record_all.setEnabled(False)
        self._recording_all = False

        conn_group = QGroupBox("連線參數（路線 B：8 台相機，依 PDF 規範 4.1.1，每台 channel=1）")
        conn_layout = QVBoxLayout()

        # 共用參數列
        common_row = QHBoxLayout()
        common_row.addWidget(QLabel("Port:"))
        common_row.addWidget(self.port_spin)
        common_row.addWidget(QLabel("User:"))
        common_row.addWidget(self.user_edit, 1)
        common_row.addWidget(QLabel("Pwd:"))
        common_row.addWidget(self.pwd_edit, 1)
        common_row.addWidget(QLabel("碼流:"))
        common_row.addWidget(self.subtype_combo)
        common_row.addWidget(QLabel("路數:"))
        common_row.addWidget(self.num_spin)
        common_row.addStretch(1)
        conn_layout.addLayout(common_row)

        # IP 清單（2 行 x 4 列，對應下方 4x2 影像格）
        ip_grid = QGridLayout()
        for i, edit in enumerate(self.host_edits):
            row, col = divmod(i, 4)
            cell = QHBoxLayout()
            cell.addWidget(QLabel(f"CH{i + 1}:"))
            cell.addWidget(edit)
            wrap = QWidget()
            wrap.setLayout(cell)
            ip_grid.addWidget(wrap, row, col)
        conn_layout.addLayout(ip_grid)

        conn_group.setLayout(conn_layout)

        action_bar = QHBoxLayout()
        action_bar.addWidget(self.btn_connect_all)
        action_bar.addWidget(self.btn_disconnect_all)
        action_bar.addWidget(self.btn_record_all)
        action_bar.addStretch(1)

        # ===== 中央 4x2 影像格 =====
        grid = QGridLayout()
        grid.setSpacing(2)
        for i in range(NUM_STREAMS):
            tile = StreamTile(i)
            self.tiles[i] = tile
            row, col = divmod(i, 4)  # 2 行 x 4 列
            grid.addWidget(tile, row, col)

        # 主 layout
        layout = QVBoxLayout(central)
        layout.addWidget(conn_group)
        layout.addLayout(action_bar)
        layout.addLayout(grid, 1)

        self.setStatusBar(QStatusBar())

        # signals
        self.btn_connect_all.clicked.connect(self.on_connect_all)
        self.btn_disconnect_all.clicked.connect(self.on_disconnect_all)
        self.btn_record_all.clicked.connect(self.on_toggle_record_all)

    # ---- 連線/中斷 ----
    def on_connect_all(self):
        port = self.port_spin.value()
        user = self.user_edit.text().strip()
        pwd = self.pwd_edit.text()
        subtype = self.subtype_combo.currentData()
        num = self.num_spin.value()

        if not user:
            QMessageBox.warning(self, "提示", "請填入 User")
            return

        # 隱藏未使用的格子
        for i in range(NUM_STREAMS):
            self.tiles[i].setVisible(i < num)

        for i in range(num):
            host = self.host_edits[i].text().strip()
            if not host:
                self.tiles[i].set_status("⚠ IP 未填")
                continue

            # 路線 B：每台相機只有 channel=1
            channel = 1
            url = build_rtsp_url(host, port, user, pwd, channel, subtype)

            tile = self.tiles[i]
            tile.set_title(f"CH {i + 1}  {host}  (sub={subtype})")
            tile.set_status("啟動中…")

            worker = RtspWorker(i, url)
            worker.frame_ready.connect(self.on_frame)
            worker.status.connect(self.on_worker_status)
            worker.error.connect(self.on_worker_error)
            worker.finished_signal.connect(self.on_worker_finished)
            self.workers[i] = worker
            worker.start()

        self.btn_connect_all.setEnabled(False)
        self.btn_disconnect_all.setEnabled(True)
        self.btn_record_all.setEnabled(True)
        self.statusBar().showMessage(f"已啟動 {len(self.workers)} 路串流")

    def on_disconnect_all(self):
        if self._recording_all:
            self._stop_record_all()
            self.btn_record_all.setText("全部錄影")
            self._recording_all = False

        for worker in list(self.workers.values()):
            worker.stop()
        for worker in list(self.workers.values()):
            worker.wait(3000)

    def on_worker_finished(self, worker_id):
        self.tiles[worker_id].clear()
        self.tiles[worker_id].set_status("已中斷")

        worker = self.workers.pop(worker_id, None)
        if worker is not None:
            # 關鍵：等執行緒實際結束再讓物件被回收，避免
            # "QThread: Destroyed while thread is still running" 崩潰
            worker.wait(2000)
            # 用 deleteLater 讓 Qt 在事件迴圈中安全銷毀
            worker.deleteLater()

        # 全部都收工後恢復按鈕
        if not self.workers:
            self.btn_connect_all.setEnabled(True)
            self.btn_disconnect_all.setEnabled(False)
            self.btn_record_all.setEnabled(False)
            self.statusBar().showMessage("全部中斷")

    # ---- 錄影 ----
    def on_toggle_record_all(self):
        if not self._recording_all:
            folder = QFileDialog.getExistingDirectory(self, "選擇錄影儲存資料夾")
            if not folder:
                return
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            for wid, worker in self.workers.items():
                # 用 IP 後三碼當識別，避免不同相機檔名混淆
                host = self.host_edits[wid].text().strip().replace(".", "_")
                path = os.path.join(folder, f"ch{wid + 1:02d}_{host}_{ts}.mp4")
                worker.start_recording(path)
            self._recording_all = True
            self.btn_record_all.setText("停止錄影")
            self.statusBar().showMessage(f"全部開始錄影：{folder}")
        else:
            saved = self._stop_record_all()
            self._recording_all = False
            self.btn_record_all.setText("全部錄影")
            QMessageBox.information(
                self, "錄影完成", f"已儲存 {len(saved)} 路錄影檔。"
            )

    def _stop_record_all(self):
        saved = []
        for worker in self.workers.values():
            path = worker.stop_recording()
            if path:
                saved.append(path)
        return saved

    # ---- Signal slots ----
    def on_frame(self, worker_id, frame):
        tile = self.tiles.get(worker_id)
        if tile:
            tile.update_frame(frame)

    def on_worker_status(self, worker_id, msg):
        tile = self.tiles.get(worker_id)
        if tile:
            tile.set_status(msg)

    def on_worker_error(self, worker_id, msg):
        tile = self.tiles.get(worker_id)
        if tile:
            tile.set_status(f"⚠ {msg}")

    def closeEvent(self, event):
        self.on_disconnect_all()
        event.accept()


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

"""
RTSP 串流檢視與錄影測試程式
依賴：PyQt5, opencv-python
安裝：pip install PyQt5 opencv-python
"""

import sys
import os

# 必須在 import cv2 之前執行：移除 OpenCV 自帶的 Qt plugin 路徑，
# 避免與 PyQt5 的 Qt 版本衝突（典型錯誤：xcb plugin 無法載入）
os.environ.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)
os.environ.pop("QT_PLUGIN_PATH", None)

import cv2
import time
from datetime import datetime

# 把 PyQt5 的 plugin 路徑指回來（保險作法）
from PyQt5.QtCore import QLibraryInfo
os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = QLibraryInfo.location(
    QLibraryInfo.PluginsPath
)

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton,
    QLineEdit, QVBoxLayout, QHBoxLayout, QFileDialog, QMessageBox, QStatusBar
)


# 預設 RTSP URL（注意：原 URL 缺少 '/'，已修正為 /stream1）
DEFAULT_RTSP_URL = "rtsp://admin:ai123456@192.168.0.10:554/cam/realmonitor?channel=1&subtype=0"
# DEFAULT_RTSP_URL = "rtsp://admin:ai123456@192.168.0.51:554/cam/realmonitor?channel=1&subtype=0"
# "rtsp://admin:ai123456@192.168.0.51:554/realmonitor?channel=1&subtype=0"


class RtspWorker(QThread):
    """背景執行緒：讀取 RTSP 串流，必要時寫入影片檔。"""

    frame_ready = pyqtSignal(object)        # 傳出原始 BGR frame
    status = pyqtSignal(str)                # 狀態訊息
    error = pyqtSignal(str)                 # 錯誤訊息
    finished_signal = pyqtSignal()

    def __init__(self, rtsp_url, parent=None):
        super().__init__(parent)
        self.rtsp_url = rtsp_url
        self._running = False
        self._recording = False
        self._writer = None
        self._record_path = None
        self._fps_estimate = 25.0

    def run(self):
        # 使用 FFMPEG backend，較穩定支援 RTSP
        # 透過環境變數設定使用 TCP 傳輸，可減少丟包
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

        self.status.emit(f"連線中：{self.rtsp_url}")
        cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)

        if not cap.isOpened():
            self.error.emit("無法開啟 RTSP 串流，請檢查 IP/帳密/網路。")
            self.finished_signal.emit()
            return

        # 取得來源 FPS（部分相機回傳 0 或不正確值，需給預設值）
        src_fps = cap.get(cv2.CAP_PROP_FPS)
        if src_fps and src_fps > 1 and src_fps < 120:
            self._fps_estimate = src_fps
        self.status.emit(f"已連線，來源 FPS≈{self._fps_estimate:.1f}")

        self._running = True
        last_log = time.time()
        frame_count = 0

        while self._running:
            ok, frame = cap.read()
            if not ok or frame is None:
                self.status.emit("讀取失敗，重試中…")
                # 簡單重連
                cap.release()
                time.sleep(1.0)
                cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
                if not cap.isOpened():
                    self.error.emit("重連失敗。")
                    break
                continue

            frame_count += 1
            self.frame_ready.emit(frame)

            # 錄影中則寫入檔案
            if self._recording and self._writer is not None:
                try:
                    self._writer.write(frame)
                except Exception as e:
                    self.error.emit(f"寫入錯誤：{e}")

            # 每秒約略回報一次實際讀到的 FPS
            now = time.time()
            if now - last_log >= 2.0:
                actual_fps = frame_count / (now - last_log)
                self.status.emit(
                    f"串流中 解析度 {frame.shape[1]}x{frame.shape[0]} "
                    f"實際FPS≈{actual_fps:.1f} "
                    f"{'[錄影中]' if self._recording else ''}"
                )
                last_log = now
                frame_count = 0

        cap.release()
        self._close_writer()
        self.status.emit("已停止串流。")
        self.finished_signal.emit()

    def stop(self):
        self._running = False

    def start_recording(self, output_path):
        """開始錄影，輸出 MP4（H.264 不一定可用，這裡用 mp4v 確保跨平台可寫入）。"""
        if self._recording:
            return
        self._record_path = output_path
        # writer 在收到第一張 frame 後才知道尺寸，這裡延後建立
        self._writer = None
        self._recording = True
        self.status.emit(f"準備錄影：{output_path}")

        # 用一個小 hook：覆寫 frame_ready 行為不可行，這裡採用旗標，在 run() 內初始化 writer
        # 改在 run() 中於收到第一張 frame 時建立 writer
        self._init_writer_pending = True
        # 用閉包補強：把 frame_ready 接到本地以建立 writer
        self.frame_ready.connect(self._maybe_init_writer)

    def _maybe_init_writer(self, frame):
        if self._recording and self._writer is None and self._record_path:
            h, w = frame.shape[:2]
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            self._writer = cv2.VideoWriter(
                self._record_path, fourcc, self._fps_estimate, (w, h)
            )
            if not self._writer.isOpened():
                self.error.emit("VideoWriter 開啟失敗，請改用 .avi 或檢查 codec。")
                self._writer = None
                self._recording = False
            else:
                self.status.emit(f"開始錄影：{self._record_path}")

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
        self.status.emit(f"錄影結束：{path}")
        return path

    def _close_writer(self):
        if self._writer is not None:
            try:
                self._writer.release()
            except Exception:
                pass
            self._writer = None


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RTSP 串流測試與錄影")
        self.resize(960, 640)

        self.worker = None
        self.current_record_path = None

        # === UI ===
        central = QWidget()
        self.setCentralWidget(central)

        self.url_edit = QLineEdit(DEFAULT_RTSP_URL)
        self.btn_connect = QPushButton("連線")
        self.btn_disconnect = QPushButton("中斷")
        self.btn_record = QPushButton("開始錄影")
        self.btn_snapshot = QPushButton("截圖")
        self.btn_disconnect.setEnabled(False)
        self.btn_record.setEnabled(False)
        self.btn_snapshot.setEnabled(False)

        top_bar = QHBoxLayout()
        top_bar.addWidget(QLabel("RTSP URL："))
        top_bar.addWidget(self.url_edit, 1)
        top_bar.addWidget(self.btn_connect)
        top_bar.addWidget(self.btn_disconnect)

        action_bar = QHBoxLayout()
        action_bar.addWidget(self.btn_record)
        action_bar.addWidget(self.btn_snapshot)
        action_bar.addStretch(1)

        self.video_label = QLabel("尚未連線")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setStyleSheet("background:#111; color:#aaa;")
        self.video_label.setMinimumSize(640, 480)

        layout = QVBoxLayout(central)
        layout.addLayout(top_bar)
        layout.addLayout(action_bar)
        layout.addWidget(self.video_label, 1)

        self.setStatusBar(QStatusBar())

        # === Signals ===
        self.btn_connect.clicked.connect(self.on_connect)
        self.btn_disconnect.clicked.connect(self.on_disconnect)
        self.btn_record.clicked.connect(self.on_toggle_record)
        self.btn_snapshot.clicked.connect(self.on_snapshot)

        self._last_frame = None

    # ---- 按鈕事件 ----
    def on_connect(self):
        url = self.url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, "提示", "請輸入 RTSP URL")
            return

        self.worker = RtspWorker(url)
        self.worker.frame_ready.connect(self.on_frame)
        self.worker.status.connect(self.statusBar().showMessage)
        self.worker.error.connect(self.on_error)
        self.worker.finished_signal.connect(self.on_worker_finished)
        self.worker.start()

        self.btn_connect.setEnabled(False)
        self.btn_disconnect.setEnabled(True)
        self.btn_record.setEnabled(True)
        self.btn_snapshot.setEnabled(True)

    def on_disconnect(self):
        if self.worker:
            if self.worker._recording:
                self.worker.stop_recording()
                self.btn_record.setText("開始錄影")
            self.worker.stop()
            self.worker.wait(3000)

    def on_worker_finished(self):
        self.btn_connect.setEnabled(True)
        self.btn_disconnect.setEnabled(False)
        self.btn_record.setEnabled(False)
        self.btn_snapshot.setEnabled(False)
        self.btn_record.setText("開始錄影")
        self.video_label.setText("已中斷")
        self.video_label.setPixmap(QPixmap())

    def on_toggle_record(self):
        if not self.worker:
            return
        if not self.worker._recording:
            default_name = datetime.now().strftime("rtsp_%Y%m%d_%H%M%S.mp4")
            path, _ = QFileDialog.getSaveFileName(
                self, "儲存錄影檔", default_name, "MP4 影片 (*.mp4);;AVI 影片 (*.avi)"
            )
            if not path:
                return
            self.current_record_path = path
            self.worker.start_recording(path)
            self.btn_record.setText("停止錄影")
        else:
            saved = self.worker.stop_recording()
            self.btn_record.setText("開始錄影")
            if saved:
                QMessageBox.information(self, "錄影完成", f"已儲存：\n{saved}")

    def on_snapshot(self):
        if self._last_frame is None:
            return
        default_name = datetime.now().strftime("snapshot_%Y%m%d_%H%M%S.png")
        path, _ = QFileDialog.getSaveFileName(
            self, "儲存截圖", default_name, "PNG 圖片 (*.png);;JPEG 圖片 (*.jpg)"
        )
        if path:
            cv2.imwrite(path, self._last_frame)
            self.statusBar().showMessage(f"截圖已儲存：{path}")

    # ---- 影像顯示 ----
    def on_frame(self, frame):
        self._last_frame = frame
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        img = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
        pix = QPixmap.fromImage(img).scaled(
            self.video_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.video_label.setPixmap(pix)

    def on_error(self, msg):
        self.statusBar().showMessage(msg)

    def closeEvent(self, event):
        self.on_disconnect()
        event.accept()


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

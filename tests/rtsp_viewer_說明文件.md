# rtsp_viewer.py 程式說明文件

> 用比喻一句話講完整支程式：
> **這支程式就像「一台監視器電視牆」**——前台有個服務員（GUI 主執行緒）負責接待你、按按鈕、把畫面貼到牆上；後台有個技師（背景執行緒）戴著耳機坐在機房，從遠端攝影機拉影像、必要時錄成錄影帶；兩人之間用對講機（Qt Signal/Slot）通訊，誰都不會把對方卡住。

---

## 一、為什麼要這樣設計？三個關鍵問題

在看程式碼之前，先想三個「為什麼」，理解了這三件事，整支程式的結構就會非常自然。

### Q1：為什麼要「兩條執行緒」？不能寫成一個迴圈嗎？

**比喻**：你一個人同時要在櫃台接待客人、又要去後場煮咖啡，結果就是——客人按鈴你聽不到，因為你正在磨豆子。

PyQt 的 GUI 主執行緒，職責是「**畫畫面 + 接收使用者輸入**」。它有一個「事件迴圈」（event loop），每秒要跑很多次去重繪視窗、檢查滑鼠鍵盤。

而 `cap.read()` 從 RTSP 拉一張影像，是一個**會「卡住」的動作**（blocking I/O）——網路慢的時候可能要等好幾百毫秒。如果讓主執行緒去做這件事：

- 視窗會「整個結凍」，按鈕按不動，連標題列拖曳都動不了
- Windows 還會跳出「程式沒有回應」

**解法**：開一條 `QThread`（背景技師），讓他專心去網路上拉影像；主執行緒（前台服務員）保持輕快，只負責把拉回來的畫面貼出來。

---

### Q2：兩條執行緒之間怎麼安全溝通？

**比喻**：櫃台服務員不能直接衝進後場拿咖啡——會打翻。後場煮好了，要用「**送餐鈴**」叫號，服務員聽到鈴聲再去取。

直接從背景執行緒呼叫 GUI 函式是 Qt 的大忌（會 crash 或畫面錯亂）。

**解法**：用 **Signal / Slot**（Qt 的對講機機制）。
- 背景執行緒 `emit` 一個訊號（按鈴）
- Qt 會把這個訊號**自動排程**到主執行緒去執行對應的 slot（領餐）
- 整個過程是 thread-safe 的

程式中有四支對講機頻道：

| Signal | 內容 | 誰來接 |
|---|---|---|
| `frame_ready` | 一張剛拉到的影像 | 主執行緒貼到視窗 |
| `status` | 文字狀態（已連線、FPS…） | 主執行緒貼到狀態列 |
| `error` | 錯誤訊息 | 主執行緒貼到狀態列 |
| `finished_signal` | 「我收工了」 | 主執行緒把按鈕恢復成「未連線」狀態 |

---

### Q3：為什麼錄影的 `VideoWriter` 要等第一張影像來才建立？

**比喻**：你要訂做一個剛剛好的相框，但你還不知道照片是 4×6 還是 8×10——只能等照片洗出來才能量尺寸。

`cv2.VideoWriter` 在建立時就必須**指定影像寬高**，而且之後寫入的每張畫面尺寸必須完全一樣，否則寫不進去。

問題是，使用者按「開始錄影」的瞬間，我們還不確定相機回傳的解析度（可能是 1920×1080、也可能是 640×480）。如果在按下按鈕當下就建立 writer，等於在不知道照片尺寸的情況下訂相框。

**解法**：按下「開始錄影」時，只**舉旗子**說「我要錄了」，真正的 writer 留到背景執行緒**收到第一張影像**、量好尺寸後才打造（`_maybe_init_writer`）。

---

## 二、程式的「角色」：兩個類別

```
┌──────────────────────────────────────────────────┐
│  MainWindow (前台服務員 / GUI 主執行緒)             │
│  ─ 視窗、按鈕、輸入框、狀態列                       │
│  ─ 接收使用者點擊，建立/控制 Worker                 │
│  ─ 收到影像就貼到 QLabel                          │
└─────────────────┬────────────────────────────────┘
                  │ Signal / Slot（對講機）
┌─────────────────▼────────────────────────────────┐
│  RtspWorker (後場技師 / 背景執行緒 QThread)        │
│  ─ 連線 RTSP                                    │
│  ─ 不停讀取影像                                  │
│  ─ 必要時寫入 VideoWriter                        │
│  ─ 回報狀態、錯誤                                │
└──────────────────────────────────────────────────┘
```

---

## 三、執行順序：從點開程式到關閉視窗

下面把整個生命週期拆成 **6 個階段**，每個階段都對應到程式中的具體函式。

### 階段 1：程式啟動（佈置櫃台）

**對應**：`main()` → `MainWindow.__init__()`

```
python rtsp_viewer.py
        ↓
   main() 建立 QApplication（啟動 Qt 事件迴圈引擎）
        ↓
   MainWindow.__init__() 把所有元件擺好：
     - URL 輸入框、四顆按鈕
     - 影像顯示用的 QLabel（黑底）
     - 狀態列
        ↓
   把按鈕的 clicked 訊號接到對應的 on_xxx 函式
        ↓
   win.show()  → 視窗出現
        ↓
   app.exec_() → 進入事件迴圈，等使用者操作
```

> **比喻**：這個階段就是開店前的工作——擺椅子、開燈、把對講機分配給員工。`app.exec_()` 之後，店就正式開門營業，前台服務員開始待命。

**為什麼順序是這樣？**
- `QApplication` 一定要**最早**建立，因為所有 Qt 物件都依賴它
- 元件要先建立、才能設定 layout
- Signal/Slot 連接要在 `show()` 之前完成，才能保證一顯示就能反應使用者操作

---

### 階段 2：使用者按下「連線」（開啟後場機台）

**對應**：`on_connect()`

```
使用者點「連線」
   ↓
on_connect() 讀取 URL 輸入框
   ↓
建立 RtspWorker(url)     ← 此時技師還沒上工，只是被聘僱
   ↓
把 worker 的四個 signal 接到主視窗對應的 slot
   ↓
worker.start()           ← 這一行才真正開新執行緒，技師進入機房
   ↓
按鈕狀態切換：連線變灰、其他按鈕亮起
```

> **比喻**：點「連線」就像是按下後場的對講機並說：「技師，上工，開始拉線。」`worker.start()` 是真正的「上工指令」，Qt 會幫你開一條 OS 執行緒並在裡面執行 `run()`。

**為什麼順序是這樣？**
- **先連 signal，再 `start()`**：如果先 start 後連 signal，技師可能還沒等你接好對講機就已經 emit 出第一個訊號，那個訊號會「掉地上」沒人收到
- 按鈕狀態切換放在最後，是為了避免使用者在連線途中重複按

---

### 階段 3：背景執行緒的影像拉取迴圈（後場的工作）

**對應**：`RtspWorker.run()`

這是整支程式最核心的迴圈，**獨立在另一條執行緒**裡跑。

```
run() 開始
   ↓
設定環境變數 OPENCV_FFMPEG_CAPTURE_OPTIONS=rtsp_transport;tcp
   │  ← 強制用 TCP 傳輸，比 UDP 穩定（不會丟包）
   ↓
cv2.VideoCapture(url, CAP_FFMPEG)     ← 建立與相機的連線
   ↓
isOpened() 失敗？→ emit error，結束
   ↓
讀取相機回報的 FPS（可能不準，所以做 1~120 的合理性檢查）
   ↓
┌─────────── 進入主迴圈 while self._running ──────────┐
│                                                    │
│  cap.read() 拉一張影像                              │
│     │                                              │
│     ├─ 失敗 → release、sleep 1 秒、重連            │
│     │                                              │
│     └─ 成功                                        │
│           ↓                                        │
│        emit frame_ready(frame)  ← 對講機叫主執行緒  │
│           ↓                                        │
│        如果正在錄影 → writer.write(frame)          │
│           ↓                                        │
│        每 2 秒計算實際 FPS、emit status            │
│                                                    │
└────────────────────────────────────────────────────┘
   ↓ 使用者按中斷後 _running = False，迴圈結束
   ↓
cap.release() + writer.release()
   ↓
emit finished_signal
```

> **比喻**：這就像技師戴著耳機坐在機房，**一張接一張**地把遠端攝影機的畫面接下來，每接到一張就按一下對講機通知前台。如果線路突然斷掉，他不會慌張關店，而是**等 1 秒再嘗試接回**。

**為什麼順序是這樣？**

1. **環境變數要在 `VideoCapture` 之前設定**：OpenCV 在開啟連線時才會讀這個變數，事後改沒用
2. **`isOpened()` 檢查必須有**：連線失敗時 `cap.read()` 會無限失敗，沒有這個檢查會死迴圈
3. **斷線重連而不是直接結束**：監控場景下網路抖動很常見，遇到一次失敗就退出體驗很差
4. **FPS 統計用「兩秒平均」**：每張畫面都印太吵，剛開始幾張的瞬間 FPS 也不準

---

### 階段 4：影像送回主執行緒並顯示（前台貼畫面）

**對應**：`MainWindow.on_frame()`

```
背景執行緒 emit frame_ready(frame)
   ↓
Qt 自動把這個呼叫排到主執行緒的事件佇列
   ↓
主執行緒在下次事件迴圈空檔時執行 on_frame(frame)
   ↓
存一份到 self._last_frame（給「截圖」按鈕用）
   ↓
cv2.cvtColor(frame, BGR2RGB)
   │  ← OpenCV 預設 BGR，Qt 用 RGB；不轉換顏色會偏藍
   ↓
包成 QImage（告訴 Qt 寬高、stride、格式）
   ↓
QPixmap.fromImage().scaled()
   │  ← 縮放到 QLabel 目前大小，保持比例
   ↓
self.video_label.setPixmap(pix) → 畫面更新
```

> **比喻**：技師按了對講機，櫃台服務員聽到後，**順手把照片轉個方向（BGR→RGB）、調整大小、貼到佈告欄上**。

**為什麼順序是這樣？**

1. **先存原始 BGR frame 再做顏色轉換**：截圖功能用 `cv2.imwrite`，它預期 BGR；如果存 RGB 版本，存檔顏色會錯
2. **`KeepAspectRatio`**：視窗被使用者拖大拖小時，影像不會被扭曲變形
3. **`SmoothTransformation`**：縮放時做雙線性內插，畫面比較不會鋸齒

---

### 階段 5：錄影流程（延後建立 VideoWriter）

**對應**：`on_toggle_record()` → `start_recording()` → `_maybe_init_writer()` → `stop_recording()`

這個流程比較繞，但只要記住前面 Q3 的比喻（**要等照片洗出來才能訂相框**），就會看懂。

```
使用者按「開始錄影」
   ↓
on_toggle_record() 跳出 QFileDialog 讓使用者選存檔路徑
   ↓
worker.start_recording(path):
   ├─ 設定 _recording = True
   ├─ _writer 暫時保持為 None
   └─ 把 frame_ready 額外接到 _maybe_init_writer
                                  │
                                  ↓
                          (等下一張影像來)
                                  │
   ┌──────────────────────────────┘
   ↓
背景執行緒拉到下一張 frame
   ↓
emit frame_ready(frame)
   ↓
這個訊號現在有「兩個 slot」會接：
   ├─ MainWindow.on_frame()        ← 貼到畫面
   └─ RtspWorker._maybe_init_writer() ← 第一次會建立 writer
                                       之後每次都 if 檢查跳過
   ↓
回到 run() 迴圈，看到 _writer 已存在 → writer.write(frame)

使用者按「停止錄影」
   ↓
stop_recording():
   ├─ _recording = False
   ├─ writer.release()         ← 把檔案的尾巴寫好、收尾
   └─ disconnect _maybe_init_writer
```

> **比喻**：按下錄影就像跟技師說「下一卷膠卷請從現在開始錄」。技師等第一張畫面來時量好尺寸、裝好膠卷（建立 writer），之後每一張都順手存進去。按停止就是「停機、把膠卷收好封盒」（`release` 會寫入檔案的 metadata，沒有 release 的影片是壞檔）。

**為什麼順序是這樣？**

1. **延後建立 writer**：前面 Q3 已說明——尺寸要等到實際收到影像才知道
2. **`release()` 一定要呼叫**：MP4/AVI 的檔頭/檔尾需要在關閉時寫入，否則檔案打不開
3. **`disconnect` 那個 slot**：避免下次再錄影時觸發兩次

---

### 階段 6：中斷與關閉（收工）

**對應**：`on_disconnect()` → `RtspWorker.stop()` → `on_worker_finished()` → `closeEvent()`

```
使用者按「中斷」或關閉視窗
   ↓
on_disconnect():
   ├─ 如果正在錄影 → 先 stop_recording()    ← 順序很重要！
   ├─ worker.stop()    ← 只是把 _running 設為 False
   └─ worker.wait(3000)  ← 主執行緒等技師收工最多 3 秒
                          │
                          ↓
              背景執行緒下一次迴圈檢查 _running = False
                          ↓
                  跳出 while 迴圈
                          ↓
                  cap.release()、writer.release()
                          ↓
                  emit finished_signal
                          ↓
              主執行緒收到 → on_worker_finished()
                          ↓
                  按鈕狀態恢復成「未連線」
                          ↓
                  QLabel 清空、顯示「已中斷」
```

> **比喻**：「中斷」不是直接拔技師的電源——那會導致錄影檔損毀。而是**對著對講機說「收工」**，技師會把手上的活做完（關閉檔案、釋放網路連線），然後回報「我下班了」，前台才把店面恢復成打烊狀態。

**為什麼順序是這樣？**

1. **先停錄影、再停執行緒**：如果先停執行緒，writer 來不及 `release()`，錄影檔會壞
2. **`stop()` 不用 `terminate()`**：強制終止執行緒會跳過所有清理動作，是大禁忌
3. **`wait(3000)` 設超時**：避免技師如果卡在某個操作，主程式永遠關不掉
4. **`closeEvent` 呼叫 `on_disconnect`**：使用者按右上角 X 時，也要走一遍完整的關閉流程，不能直接讓視窗消失

---

## 四、整體流程一張圖

```
[啟動]
   │
   ▼
[QApplication + MainWindow] ─────── 主執行緒（GUI）
   │
   │ 使用者按「連線」
   ▼
[on_connect 建立 RtspWorker、connect signals、worker.start()]
   │
   ├──────────────────────────────► [run() 開始於背景執行緒]
   │                                       │
   │                                  cv2.VideoCapture()
   │                                       │
   │                                       ▼
   │   ◄── frame_ready ──────────  ┌─ while _running ─┐
   │   ◄── status ───────────────  │   cap.read()      │
   │                               │   emit frames     │
   │                               │   write if rec    │
   │                               └───────┬───────────┘
   │                                       │
   │                                  使用者按中斷
   │   ◄── finished_signal ────────  cap.release()
   │                                       │
   ▼                                       ▼
[on_worker_finished 恢復 UI]          [背景執行緒結束]
```

---

## 五、關鍵設計決策回顧

| 決策 | 不這樣做會怎樣 |
|---|---|
| RTSP 拉流放在 `QThread` | GUI 會凍結，按鈕沒反應 |
| 用 Signal/Slot 通訊 | 直接跨執行緒呼叫 GUI → 程式 crash |
| 強制 TCP（`rtsp_transport;tcp`） | UDP 會丟包，畫面破碎 |
| 斷線自動重連 | 網路一抖就要重按連線 |
| `VideoWriter` 延後建立 | 不知道相機解析度，無法建立 |
| `release()` 確實呼叫 | 錄影檔損毀、無法播放 |
| `BGR → RGB` 轉換 | 畫面顏色偏藍（藍紅互換） |
| `stop()` 而非 `terminate()` | 資源未清理、檔案損毀 |
| 先停錄影再停執行緒 | 錄影檔尾巴沒寫好 |

---

## 六、可能想再延伸的方向

讀懂之後，可以試試以下練習加深理解：

1. **加入「音訊」錄製**：OpenCV 不抓音訊，要改用 `ffmpeg-python` 或直接 subprocess 呼叫 ffmpeg
2. **多路相機同時顯示**：把 MainWindow 改成 grid layout，每路一個 Worker
3. **錄影分段**：每 10 分鐘自動換新檔案，避免單檔太大
4. **加上偵測**：在 `on_frame` 內接入 YOLO/MediaPipe，做物件或人臉偵測
5. **改用 GStreamer 後端**：低延遲場景下，GStreamer 比 FFmpeg 更可控

---

> **總結**：這支程式的精髓是「**分工 + 對講機**」。GUI 主執行緒只做它擅長的事（畫面、互動），把會卡住的網路 I/O 丟給背景執行緒，兩者透過 Qt 的 Signal/Slot 安全通訊。所有看似繁瑣的順序——先連 signal 後 start、先停錄影後停執行緒、writer 延後建立——都是為了確保「資源能安全清理、影像能正確顯示、檔案能順利存檔」這三件事。

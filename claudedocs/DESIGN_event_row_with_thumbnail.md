# Design: 「最新進出快訊」EventRow 加入縮圖

> 目的：把 [src/frontend/views.py:140](../src/frontend/views.py#L140) 右側「最新進出快訊」面板的列樣式改為符合 [`refData/規格書/工地看板_UI趨勢與即時快訊模板.pdf`](../refData/規格書/工地看板_UI趨勢與即時快訊模板.pdf) 第 3 頁模板：每列加入車輛 / 人像縮圖。
>
> 範圍：本文件僅為設計，不修改程式碼。確認後以 `/sc:implement` 套用。

---

## 1. 現況 vs 目標（視覺對比）

### 1.1 現況（widgets.py:226 `EventRow`）

```
┌────────────────────────────────────────────────────────┐
│ [進] 14:32  ABC-5288                       [白名單]   │
│           A03 · 大榮土木 · 砂石車                       │
└────────────────────────────────────────────────────────┘
                                  ↑ 底線分隔；無縮圖
```

### 1.2 目標（PDF 第 3 頁模板）

```
┌────────────────────────────────────────────────────────┐
│ ┌──────┐                                  進    14:32 │
│ │ 🚗   │  ABC-5288                       ┌────────┐    │
│ │ car  │  A03 · 砂石車 · 大榮土木        │ 白名單 │    │
│ └──────┘                                  └────────┘    │
└────────────────────────────────────────────────────────┘
   ↑ 64×44 縮圖             ↑ 主標 14pt bold     ↑ 右下徽章

┌────────────────────────────────────────────────────────┐
│ ┌──────┐                                  進    14:31 │
│ │ 👤   │  王 O 明                        ┌────────┐    │
│ │face  │  B01 · 建築工 · 證照有效        │  通行  │    │
│ └──────┘                                  └────────┘    │
└────────────────────────────────────────────────────────┘
   ↑ 44×44 圓形人臉
```

### 1.3 各狀態示意

| 狀態 | event_type | status_type | 縮圖 | 徽章顏色 |
|---|---|---|---|---|
| 車輛 · 白名單 | vehicle | whitelist | 🚗 (car.png) | 綠 |
| 車輛 · 陌生 | vehicle | stranger | 🚗 (car.png) | 黃 |
| 車輛 · 黑名單 | vehicle | blacklist | 🚗 (car.png，紅框) | 紅 |
| 人員 · 通行 | personnel | pass | 👤 (person.png) | 綠 |
| 人員 · 告警 | personnel | alert | 👤 (person.png，紅框) | 紅 |
| 名單未同步 | * | pending | 對應類型 | 灰 |

---

## 2. 元件設計

### 2.1 新 `EventRow` 結構

```
EventRow (QFrame, bgCard 背景 + 圓角 8px + 內距 12px)
├── HBox (spacing=12)
│   ├── EventThumbnail (64×44 車 / 44×44 人)         ← 新元件
│   ├── VBox (spacing=2, stretch=1)                ← 主要內容
│   │   ├── HBox: DirectionPill (小) + Time (mono, 右上)
│   │   ├── display_name (14pt bold, mono if vehicle)
│   │   └── meta line: site_id · contractor · detail (11pt textMuted)
│   └── VBox (右下對齊)
│       └── StatusBadge (尺寸略大: 13pt)
```

### 2.2 新元件 `EventThumbnail`

| 屬性 | 規格 |
|---|---|
| 位置 | `src/frontend/widgets.py`，置於 `FaceSnapshot` 之後 |
| 簽名 | `EventThumbnail(event_type: str, status_type: str, snapshot_path: str \| None = None, parent=None)` |
| 行為 | 1) 若 `snapshot_path` 存在且檔案讀得到 → QPixmap 縮放置中<br>2) 否則依 `event_type` 載入 `assets/placeholders/car.png` 或 `person.png`<br>3) `status_type ∈ {alert, blacklist}` → 紅框 2px；否則細灰框 1px<br>4) 圓角 6px，剪裁顯示 |
| 尺寸 | 車輛 64×44；人員 44×44（圓形 mask） |
| 失敗回退 | 圖檔缺漏時：fall back 到目前的向量繪製 [VehicleSnapshot](../src/frontend/widgets.py#L164) / [FaceSnapshot](../src/frontend/widgets.py#L131)（縮小版） |

### 2.3 EventRow 程式碼骨架（**設計參考，非套用**）

```python
class EventRow(QFrame):
    def __init__(self, ev: dict, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame{{background:{_HEX['bgCard']};"
            f"border:1px solid {_HEX['border']};border-radius:8px;}}")
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 10, 12, 10)
        h.setSpacing(12)

        # (1) 縮圖
        h.addWidget(EventThumbnail(
            ev.get("event_type", "vehicle"),
            ev.get("status_type"),
            ev.get("snapshot_url"),
        ))

        # (2) 主內容
        mid = QVBoxLayout()
        mid.setSpacing(2)

        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(DirectionPill(ev.get("direction")))
        top.addStretch(1)
        top.addWidget(_lbl(ev.get("event_time", "")[:5], "textDim", 11, mono=True))
        mid.addLayout(top)

        name = ev.get("display_name", "")
        if ev.get("secondary_id"):
            name += f"  / {ev['secondary_id']}"
        mid.addWidget(_lbl(name, "text", 14, bold=True,
                           mono=(ev.get("event_type") == "vehicle")))

        meta = " · ".join(x for x in (
            ev.get("site_id"), ev.get("contractor"), ev.get("detail")) if x)
        mid.addWidget(_lbl(meta, "textMuted", 11))
        h.addLayout(mid, 1)

        # (3) 右側狀態
        right = QVBoxLayout()
        right.addStretch(1)
        right.addWidget(StatusBadge(ev.get("status_type"),
                                     ev.get("status", "")),
                        0, Qt.AlignRight)
        h.addLayout(right)
```

---

## 3. 資源策略：佔位圖片

### 3.1 目錄佈局

```
CarRecogDashboard/
└── assets/
    └── placeholders/
        ├── car.png      ← 代表車輛縮圖（建議 256×176 px）
        └── person.png   ← 代表人員縮圖（建議 256×256 px 正方形）
```

### 3.2 圖片來源建議

- **car.png**：採用一張中性偏暗的車輛側面 / 前 45° 角照（深色車身、白底或灰底，避免高反差）
- **person.png**：建議用一張帶安全帽的工地人員半身像；或退而求其次以「人形剪影」icon 取代
- 兩張都應為 PNG 透明背景或深色 (#0F1B33) 底以與 dashboard 深色主題協調
- 授權：避免使用網路素材；若無內部素材，先以 [Heroicons](https://heroicons.com/) / [Tabler Icons](https://tabler-icons.io/) 之 truck / user icon SVG 轉 PNG 充用

### 3.3 載入策略

```python
# widgets.py 模組級單例（避免每列重複 load）
from pathlib import Path
from PyQt5.QtGui import QPixmap

_ASSETS = Path(__file__).resolve().parents[2] / "assets" / "placeholders"
_PLACEHOLDER_CAR    = QPixmap(str(_ASSETS / "car.png"))
_PLACEHOLDER_PERSON = QPixmap(str(_ASSETS / "person.png"))
```

未來真實 `snapshot_url`（後端 [ingest.py:234](../src/backend/ingest.py#L234) 已會嘗試從 `snapshot.cgi` 抓 JPEG）就緒後，`EventThumbnail` 自動切換到真實圖；佔位圖只在 fallback 時用。

### 3.4 .gitignore 影響

確認 [.gitignore](../.gitignore) 不會把 `assets/` 排除；目前看 .gitignore 只排除 `myenv/`、`data/`、`__pycache__`，`assets/` 會正常入版控。

---

## 4. 受影響檔案清單

| 檔案 | 變更 | 工作量 |
|---|---|---|
| [src/frontend/widgets.py](../src/frontend/widgets.py) | 新增 `EventThumbnail`、改寫 `EventRow`（L226–252） | 中 (~60 行) |
| [src/frontend/views.py](../src/frontend/views.py) | **無需改動** — `OverviewView._build` 已呼叫 `EventRow(e)` | — |
| `assets/placeholders/car.png` | 新增（256×176） | 1 檔 |
| `assets/placeholders/person.png` | 新增（256×256） | 1 檔 |
| [src/frontend/theme.py](../src/frontend/theme.py) | 可選 — 若需獨立 `bgRow` 顏色 | 小 |

> **注意**：[SiteBoardView](../src/frontend/views.py#L182-186) 的「最新事件」面板與 [VehicleView](../src/frontend/views.py#L284) / [PersonnelView](../src/frontend/views.py#L324) 用的是 `VehicleDetailRow` / `PersonnelDetailRow`，不是 `EventRow`。本次只動「最新進出快訊」（Overview 右側），其它列樣式保留。

---

## 5. 設計取捨

| 議題 | 選擇 | 理由 |
|---|---|---|
| 縮圖位置 | 左側固定 | 對齊 PDF 模板；視線掃描自然 |
| 車 vs 人尺寸 | 64×44 / 44×44 圓 | 車是橫向長方形（車寬比 ~1.45），人臉用方形 / 圓形剪裁更明確 |
| 圖片載入時機 | 模組級 lazy QPixmap 單例 | 避免每筆事件重複 IO；20 列也才一份記憶體 |
| 圖檔缺漏 fallback | 走原 `VehicleSnapshot` / `FaceSnapshot` 向量繪製 | 不會 crash；圖檔缺也能 demo |
| 真實 snapshot 接管 | `snapshot_url` 優先 | 預留未來 [ingest.py:234](../src/backend/ingest.py#L234) 真實圖串接 |
| 列分隔 | 卡片 + 行距 6px（移除底線） | 模板的卡片感較清楚；底線在縮圖列會被切割得不好看 |
| 整體 panel 寬度 | 維持 380px（views.py:139） | 不影響其它 layout |

---

## 6. 風險

| 風險 | 嚴重度 | 緩解 |
|---|---|---|
| 圖檔授權問題 | 🟡 中 | 設計建議用 icon-based 圖示（Heroicons 等 MIT 授權） |
| `QPixmap` 在 headless 測試環境失敗 | 🟢 低 | 載入失敗時靜默退回向量繪製（已在 §2.2 設計） |
| 列高拉長後 panel 可放下 20 列嗎 | 🟢 低 | 380px 寬 × 約 70px 列高 → 14–15 列可見 + scroll；模板第 3 頁範例也只展示 5 列 |
| 真實 snapshot URL 串接後的圖檔 IO 阻塞 | 🟡 中 | 後續 `/sc:implement` 階段：QPixmap loadFromData() 配合 ApiPoller 的 image cache，避免 UI thread 抓圖 |

---

## 7. 驗收標準

- [ ] Overview 頁右側「最新進出快訊」每列**都有縮圖**
- [ ] 車輛事件顯示 car.png；人員事件顯示 person.png
- [ ] 黑名單 / 告警事件的縮圖有紅框
- [ ] 圖檔不存在時仍可正常顯示（fallback 到向量繪製）
- [ ] [SiteBoardView](../src/frontend/views.py#L148) / [VehicleView](../src/frontend/views.py#L215) / [PersonnelView](../src/frontend/views.py#L290) 的列樣式**不變**

---

## 8. 下一步

確認此設計後，以 `/sc:implement` 套用：
1. 建立 `assets/placeholders/` 與兩張 PNG
2. 編輯 [src/frontend/widgets.py](../src/frontend/widgets.py)：新增 `EventThumbnail`、重寫 `EventRow`
3. `python -m src.frontend.main` 視覺驗證

如需我先準備 PNG 占位圖（SVG 轉 PNG），請指定來源 icon 集或允許我用 PyQt 程式產一張深色幾何圖案的代表圖。

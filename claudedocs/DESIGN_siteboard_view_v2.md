# Design: 「單一工地」分頁依模板 p.4 重整

> 目的：把 [src/frontend/views.py:148-211](../src/frontend/views.py#L148-L211) 的 `SiteBoardView` 對齊 [`refData/規格書/工地看板_UI趨勢與即時快訊模板.pdf`](../refData/規格書/工地看板_UI趨勢與即時快訊模板.pdf) 第 4 頁「人員 + 車輛同屏」模板。
>
> 範圍：本文件僅為設計，不修改程式碼。確認後以 `/sc:implement` 套用。

---

## 1. 模板 p.4 視覺結構

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ 單一工地看板模板：人員 + 車輛同屏      工地：A03 機電棟工區  [最後更新 14:32] │ ← Title bar
│ 切換到特定工地後，最重要的數字...                                            │   (NEW)
├──────────────────────────────────────────────────────────────────────────────┤
│ ┌─人員進場─┐ ┌─人員出場─┐ ┌─目前在場─┐ ┌─車輛進場─┐ ┌─車輛出場─┐ ┌─車輛在場─┐│
│ │ 186      │ │ 142      │ │ 44       │ │ 51       │ │ 38       │ │ 13       ││  ← KPI×6
│ │今日累計  │ │今日累計  │ │人員即時  │ │今日累計  │ │今日累計  │ │車輛即時  ││   ✅ 已有
│ └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘│
├──────────────────────────────────────────────────────────────────────────────┤
│ 今日 0-24 小時進出趨勢              │  最新快訊與截圖                        │
│ ┌─────────────────────────────────┐ │  ┌─[縮圖] 進  ABC-5288    14:32─┐    │
│ │ ▆ ▆▆ ▆▆▆ ▇▇█████▇▆▆▆▅▃▂      │ │  │ 大榮土木·砂石車·閘門已開啟[白]│    │
│ │ ━━━━╱╲___╱──────────╲___╱──━ │ │  └────────────────────────────────┘    │
│ │ 0  3  6  9  12  15  18  21      │ │  ┌─[縮圖] 進  王O明/E-1029  14:31─┐  │
│ │ ▆ 人員進場   ━ 車輛進場         │ │  │ 正興機電·高空作業證照有效[通行]│  │
│ └─────────────────────────────────┘ │  └────────────────────────────────┘  │
│                                     │  ┌─[縮圖] 進  李O華/E-0981  14:28─┐  │
│   ↑ 只有 2 種系列                   │  │ 隆泰工程·電焊證過期    [告警] │  │
│     (人員進場 bar、車輛進場 line)   │  └────────────────────────────────┘  │
├──────────────────────────────────────────────────────────────────────────────┤
│ 現場影像參考                                                                 │
│ ┌─[卡車]──┐ ┌─[人像]──┐ ┌─[卡車]──┐  快訊跳卡顯示 5-8 秒，可設定...      │
│ │ 大車    │ │ 工地人員│ │ 小卡車  │  黑名單、證照過期、陌生車牌會優先顯示│
│ └─────────┘ └─────────┘ └─────────┘                                          │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 現況 vs 模板差異

| 區塊 | 模板 p.4 | 現況 [views.py:148](../src/frontend/views.py#L148) | 動作 |
|---|---|---|---|
| **頂部 Title bar** | 「工地：A03 機電棟工區」+「最後更新 14:32」綠色徽章在右 | **沒有** | 🆕 新增 |
| KPI 列 | 6 卡片：人員進場/出場/在場 + 車輛進場/出場/在場 | ✅ 同 6 卡片 | 維持 |
| KPI 副標 | 「今日累計人次」/「人員即時在場」 | ✅ 同 | 維持 |
| 趨勢圖標題 | 「今日 0-24 小時進出趨勢」 | 「今日 0-24H 進出趨勢與預測」+「目前 N 時·AI預測延伸 4H·信賴帶 ±30%」 | ✏️ 簡化 |
| **趨勢圖系列** | **2 系列**：人員進場 (bar) + 車輛進場 (line) | **4 系列**：人員進場/離場 bars + 車輛進場/離場 lines | ⚠️ 簡化（移除離場、移除預測） |
| 趨勢圖 legend | 「■ 人員進場 ━ 車輛進場」2 項 | 4 項 | ✏️ 跟著簡化 |
| 右側面板標題 | 「最新快訊與截圖」 | 「最新事件」 | ✏️ 改名 |
| 右側列數 | 3 列（模板示意）| 8 列 + scroll | ✏️ 預設 3-5 列即可 |
| 右側 EventRow | 卡片式 + 縮圖 + 進/出 + 時間 + 子資訊 + 狀態徽章 | ✅ 已是新版（上次改的） | 維持 |
| 底部面板標題 | 「現場影像參考」 | 「最新現場影像」+「同步事件」 | ✏️ 改名 |
| 底部影像 | 3 張（2 車 + 1 人）橫排 | 動態混合（2 車 + 3 人）| ✏️ 固定 3 張、2:1 比例 |
| 底部說明文字 | 「快訊跳卡顯示 5-8 秒，可設定是否保留在右側最新清單。黑名單、證照過期、陌生車牌會優先顯示」 | 「● 顯示最近截圖 / 新事件進入時自動更新 / 黑名單 / 證照過期 截圖將紅框標示」 | ✏️ 改文案 |

---

## 3. 設計細節

### 3.1 新增 Title bar（最頂部）

新元件 `SiteHeaderBar(QWidget)`，放在 KPI 列之前：

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                                  工地：A03 機電棟工區  [最後更新 14:32]      │
└──────────────────────────────────────────────────────────────────────────────┘
                                            ↑ textMuted 14pt      ↑ 綠色徽章
                                                                    pass color
                                                                    bgCard 背景
                                                                    border-radius 4
```

| 元素 | 樣式 |
|---|---|
| 容器 | `QHBoxLayout`，無背景，右對齊 |
| 「工地：xxx」 | `_lbl` text 14pt，前綴 textMuted、後段 text |
| 「最後更新」徽章 | 12pt mono、`pass` 顏色、`rgba(pass, 0.18)` 背景、`padding:4px 10px`、`border-radius:4px` |
| 資料源 | `state.site_summary.last_update_time`（已存在）、`state.site_summary.site_name` |

### 3.2 趨勢圖簡化

修改 [`HourlyChart`](../src/frontend/charts.py) **呼叫端**，只放 2 系列：

```python
ch = HourlyChart(
    bars=[("people_in", "in", "人員進場")],          # 只 1 個 bar
    lines=[("vehicle_in", "vehicleIn", "車輛進場")], # 只 1 個 line
    show_forecast=False,                             # 關閉預測（模板沒有）
    legend=True)
```

- 移除「人員離場」「車輛離場」兩個系列（避免視覺過載）
- 關閉 forecast 虛線 + 信賴帶（模板沒有 AI 預測展示）
- 標題改成單純的「今日 0-24 小時進出趨勢」，無右側副標
- ✅ `HourlyChart` 元件本身不需改，只改呼叫參數

> **設計取捨**：模板簡化是為了讓「車輛 v.s 人員」對比一目了然；如未來需要「離場」對照，可在「車輛」「人員」分頁裡細看。

### 3.3 「最新快訊與截圖」面板

- 標題：`SectionTitle("最新快訊與截圖", "即時推送")`（與全工地總覽一致）
- 列數：**預設取最近 5 筆**（模板畫了 3，但 380px 寬度能容 5-6 列；保留 scroll）
- 元件：用上次改好的 `EventRow`（已含縮圖 + 下方狀態徽章）

### 3.4 底部「現場影像參考」面板

- 標題改：`SectionTitle("現場影像參考")`（無副標）
- 影像策略：取最近 **2 輛車 + 1 個人員**，按事件時間從新到舊排：
  ```python
  vehicle_evs = [e for e in evs if e["event_type"]=="vehicle"][:2]
  people_evs  = [e for e in evs if e["event_type"]=="personnel"][:1]
  ```
- 三張影像並排（左→右）：`VehicleSnapshot(200×130)` + `FaceSnapshot(120)` + `VehicleSnapshot(170×110)` — 與模板的 2 車 + 1 人比例一致
- 右側說明文字（textMuted 12pt，wordWrap）：
  > 快訊跳卡顯示 5–8 秒，可設定是否保留在右側最新清單。
  > 黑名單、證照過期、陌生車牌會優先顯示。
- 黑名單/證照過期事件的截圖加紅框（已由 `alert=True` 參數實作）

### 3.5 整體 layout 比例

| 層級 | 元素 | stretch |
|---|---|---|
| 頂部 | SiteHeaderBar | 固定高度 (~32px) |
| KPI 列 | 6 cards | 固定 ~80px |
| 中段 | chart_panel : ev_panel | **16 : 10**（維持，與模板視覺比例 ~60:40 一致）|
| 底部 | snap_panel | 固定 ~180px |

---

## 4. 程式骨架（參考）

```python
class SiteBoardView(_BaseView):
    def _build(self):
        s = self.state
        k = s.get("site_summary", {})
        tr = s.get("trend", {})
        evs = s.get("events", [])

        # (1) Header bar (NEW)
        self._root.addWidget(SiteHeaderBar(
            site_name=k.get("site_name", ""),
            last_update=k.get("last_update_time", "—"),
        ))

        # (2) KPI row — unchanged
        kpi = QHBoxLayout(); kpi.setSpacing(10)
        for lab, key, ck, sub in (
            ("人員進場", "people_in",      "in",        "今日累計人次"),
            ("人員出場", "people_out",     "out",       "今日累計人次"),
            ("目前在場", "people_inside",  "pass",      "人員即時在場"),
            ("車輛進場", "vehicle_in",     "vehicleIn", "今日累計車次"),
            ("車輛出場", "vehicle_out",    "vehicleOut","今日累計車次"),
            ("車輛在場", "vehicle_inside", "stranger",  "車輛即時在場"),
        ):
            kpi.addWidget(KpiCard(lab, k.get(key, 0), sub, ck))
        self._root.addLayout(kpi)

        # (3) Mid row: chart (left) + events (right)
        mid = QHBoxLayout(); mid.setSpacing(12)

        chart_panel = Panel()
        chart_panel.v.addWidget(SectionTitle("今日 0-24 小時進出趨勢"))
        ch = HourlyChart(
            bars=[("people_in", "in", "人員進場")],
            lines=[("vehicle_in", "vehicleIn", "車輛進場")],
            show_forecast=False, legend=True)
        ch.set_data(tr.get("trend", []), [], tr.get("current_hour", 14))
        chart_panel.v.addWidget(ch, 1)
        mid.addWidget(chart_panel, 16)

        ev_panel = Panel()
        ev_panel.v.addWidget(SectionTitle("最新快訊與截圖", "即時推送"))
        ev_panel.v.addWidget(_scroll_list([EventRow(e) for e in evs[:5]]), 1)
        mid.addWidget(ev_panel, 10)
        self._root.addLayout(mid, 1)

        # (4) Field images (renamed)
        snap = Panel()
        snap.v.addWidget(SectionTitle("現場影像參考"))
        row = QHBoxLayout(); row.setSpacing(14)
        vehicle_evs  = [e for e in evs if e.get("event_type") == "vehicle"][:2]
        people_evs   = [e for e in evs if e.get("event_type") == "personnel"][:1]
        if vehicle_evs:
            row.addWidget(VehicleSnapshot(
                vehicle_evs[0]["display_name"], 200, 130,
                alert=vehicle_evs[0].get("status_type") in ("alert","blacklist")))
        if people_evs:
            row.addWidget(FaceSnapshot(
                people_evs[0]["display_name"], 120,
                alert=people_evs[0].get("status_type") == "alert"))
        if len(vehicle_evs) > 1:
            row.addWidget(VehicleSnapshot(
                vehicle_evs[1]["display_name"], 170, 110,
                alert=vehicle_evs[1].get("status_type") in ("alert","blacklist")))
        note = _lbl("快訊跳卡顯示 5–8 秒，可設定是否保留在右側最新清單。\n"
                    "黑名單、證照過期、陌生車牌會優先顯示。",
                    "textMuted", 12)
        note.setWordWrap(True)
        row.addWidget(note, 1)
        rw = QWidget(); rw.setStyleSheet("background:transparent;"); rw.setLayout(row)
        snap.v.addWidget(rw)
        self._root.addWidget(snap)
```

---

## 5. 受影響檔案

| 檔案 | 變更 | 工作量 |
|---|---|---|
| [src/frontend/widgets.py](../src/frontend/widgets.py) | 新增 `SiteHeaderBar` 元件（~25 行） | 小 |
| [src/frontend/views.py:148-211](../src/frontend/views.py#L148-L211) | 重寫 `SiteBoardView._build`（淨增約 5 行，更改約 40 行） | 中 |
| [src/frontend/charts.py](../src/frontend/charts.py) | **不動** — `HourlyChart` 已支援 `show_forecast=False` 與 single-series | — |
| 其他 view | **不動** — `OverviewView` / `VehicleView` / `PersonnelView` 等保持原樣 | — |

---

## 6. 設計取捨

| 議題 | 選擇 | 理由 |
|---|---|---|
| 趨勢圖系列數 | 2 系列（進場 vs 進場）| 模板優先「對比車 vs 人」，離場資料在「車輛」「人員」分頁查看 |
| AI 預測虛線 | 關閉 | 模板 p.4 沒有；總覽 (`OverviewView`) 與「趨勢」分頁仍保留 |
| 右側預設列數 | 5 列（模板畫 3）| 380px panel 容得下；scroll 保留 |
| 底部影像比例 | 2 車 + 1 人（固定）| 與模板嚴格一致；缺資料時退回向量 placeholder |
| 標題列位置 | 在 KPI 上方 | 模板把工地名 + 最後更新時間放在最頂端 |
| 標題列高度 | ~32px（無 panel 背景）| 不浪費螢幕空間；與「最後更新 14:32」綠徽章對齊 |

---

## 7. 視覺驗收標準

- [ ] 頂部出現「工地：xxx」+「最後更新 HH:MM」綠色徽章
- [ ] KPI 6 卡片無變化
- [ ] 趨勢圖只有 2 系列（人員進場 bar、車輛進場 line）+ 對應 legend，無預測虛線
- [ ] 右側面板標題改成「最新快訊與截圖」，最近 5 筆事件（卡片式，含縮圖）
- [ ] 底部面板標題改成「現場影像參考」，固定 2 車 + 1 人共 3 張影像
- [ ] 黑名單 / 告警事件的縮圖有紅框
- [ ] 整體版面比例（chart : events ≈ 60:40）與模板一致

---

## 8. 風險

| 風險 | 等級 | 緩解 |
|---|---|---|
| `HourlyChart` legend 在單 bar + 單 line 時的排版可能太空 | 🟢 低 | 預先驗證；如太空可加 spacer |
| `SiteHeaderBar` 在窄螢幕（< 1280px）右對齊可能擠 | 🟢 低 | 用 `addStretch(1)` 推到右側即可 |
| 無人員事件時底部只剩 2 張車截圖 | 🟢 低 | 已有向量 fallback（`FaceSnapshot` 不傳入也能畫） |
| 「最後更新時間」格式 vs `site_summary.last_update_time` 後端格式 | 🟢 低 | 已驗證為 `HH:MM:SS`；header 顯示時截 `HH:MM` |

---

## 9. 下一步

確認此設計後，以 `/sc:implement` 套用：
1. 在 [widgets.py](../src/frontend/widgets.py) 新增 `SiteHeaderBar`
2. 重寫 [views.py:148-211](../src/frontend/views.py#L148-L211) `SiteBoardView._build`
3. `python -m src.frontend.main`，按數字鍵 `2` 切到「單一工地」分頁視覺驗證

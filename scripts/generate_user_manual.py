"""Generate CarDashboard / Site Board Dashboard user manual (docx)."""
from docx import Document
from docx.shared import Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement


def set_cell_bg(cell, color_hex: str):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), color_hex)
    tc_pr.append(shd)


def add_heading(doc, text, level=1):
    h = doc.add_heading(text, level=level)
    for run in h.runs:
        run.font.name = "Microsoft JhengHei"
        run.font.color.rgb = RGBColor(0x0F, 0x3B, 0x73)
    return h


def add_para(doc, text, bold=False, size=11, italic=False):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.font.name = "Microsoft JhengHei"
    run.font.size = Pt(size)
    run.bold = bold
    run.italic = italic
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), "Microsoft JhengHei")
    return p


def add_bullets(doc, items):
    for it in items:
        p = doc.add_paragraph(style="List Bullet")
        run = p.add_run(it)
        run.font.name = "Microsoft JhengHei"
        run.font.size = Pt(11)
        rpr = run._element.get_or_add_rPr()
        rfonts = rpr.find(qn("w:rFonts"))
        if rfonts is None:
            rfonts = OxmlElement("w:rFonts")
            rpr.append(rfonts)
        rfonts.set(qn("w:eastAsia"), "Microsoft JhengHei")


def add_numbered(doc, items):
    for it in items:
        p = doc.add_paragraph(style="List Number")
        run = p.add_run(it)
        run.font.name = "Microsoft JhengHei"
        run.font.size = Pt(11)
        rpr = run._element.get_or_add_rPr()
        rfonts = rpr.find(qn("w:rFonts"))
        if rfonts is None:
            rfonts = OxmlElement("w:rFonts")
            rpr.append(rfonts)
        rfonts.set(qn("w:eastAsia"), "Microsoft JhengHei")


def add_table(doc, header, rows, col_widths=None):
    table = doc.add_table(rows=1 + len(rows), cols=len(header))
    table.style = "Light Grid Accent 1"
    hdr_cells = table.rows[0].cells
    for i, h in enumerate(header):
        hdr_cells[i].text = ""
        p = hdr_cells[i].paragraphs[0]
        run = p.add_run(h)
        run.bold = True
        run.font.size = Pt(10.5)
        run.font.name = "Microsoft JhengHei"
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        rpr = run._element.get_or_add_rPr()
        rfonts = rpr.find(qn("w:rFonts"))
        if rfonts is None:
            rfonts = OxmlElement("w:rFonts")
            rpr.append(rfonts)
        rfonts.set(qn("w:eastAsia"), "Microsoft JhengHei")
        set_cell_bg(hdr_cells[i], "0F3B73")
    for r_idx, row in enumerate(rows, start=1):
        cells = table.rows[r_idx].cells
        for c_idx, val in enumerate(row):
            cells[c_idx].text = ""
            p = cells[c_idx].paragraphs[0]
            run = p.add_run(str(val))
            run.font.size = Pt(10)
            run.font.name = "Microsoft JhengHei"
            rpr = run._element.get_or_add_rPr()
            rfonts = rpr.find(qn("w:rFonts"))
            if rfonts is None:
                rfonts = OxmlElement("w:rFonts")
                rpr.append(rfonts)
            rfonts.set(qn("w:eastAsia"), "Microsoft JhengHei")
    if col_widths:
        for row in table.rows:
            for i, w in enumerate(col_widths):
                row.cells[i].width = Cm(w)
    return table


# ============================================================
# 開始建立文件
# ============================================================
doc = Document()

# 預設字型
style = doc.styles["Normal"]
style.font.name = "Microsoft JhengHei"
style.font.size = Pt(11)
rpr = style.element.get_or_add_rPr()
rfonts = OxmlElement("w:rFonts")
rfonts.set(qn("w:eastAsia"), "Microsoft JhengHei")
rpr.append(rfonts)

# ============================================================
# 封面
# ============================================================
title = doc.add_paragraph()
title.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = title.add_run("CarDashboard / 工地看板\n使用者操作手冊")
run.bold = True
run.font.size = Pt(28)
run.font.name = "Microsoft JhengHei"
run.font.color.rgb = RGBColor(0x0F, 0x3B, 0x73)

sub = doc.add_paragraph()
sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = sub.add_run("Site Board Dashboard · User Manual")
run.font.size = Pt(14)
run.font.color.rgb = RGBColor(0x5A, 0x70, 0x99)
run.italic = True

doc.add_paragraph()
meta = doc.add_paragraph()
meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = meta.add_run("版本:Demo v2  ·  發行日期:2026/05/15  ·  適用對象:工地主任、工安督導、保全、IT 管理員")
run.font.size = Pt(11)

doc.add_page_break()

# ============================================================
# 目錄說明
# ============================================================
add_heading(doc, "目錄", level=1)
toc_items = [
    "1. 系統簡介",
    "2. 主要使用對象與情境總覽",
    "3. 介面架構與導覽元件",
    "4. 子頁籤功能詳述",
    "    4.1 全工地總覽 (Overview)",
    "    4.2 單一工地 (Site Board)",
    "    4.3 車輛看板 (Vehicle)",
    "    4.4 人員看板 (Personnel)",
    "    4.5 趨勢全螢幕 (Trend)",
    "    4.6 異常事件牆 (Alert)",
    "5. AI 副駕駛與可解釋性",
    "6. 跳卡浮層 (Flash Card) 即時通知",
    "7. 完整執行路徑 (Execution Paths)",
    "8. 使用情境 (Scenarios)",
    "9. 使用案例 (Use Cases)",
    "10. 快速鍵與快捷操作",
    "11. 狀態色彩與圖示說明",
    "12. 常見問題與排除",
    "13. 名詞對照表",
]
add_bullets(doc, toc_items)
doc.add_page_break()

# ============================================================
# 1. 系統簡介
# ============================================================
add_heading(doc, "1. 系統簡介", level=1)
add_para(doc,
    "「工地看板 (Site Board Dashboard)」是一套面向營建工地的即時人車進出監控與 AI 風險判讀平台。"
    "系統整合 ALPR(車牌辨識)、FaceID(人臉辨識)、白名單/黑名單比對、證照效期資料庫與工地巡檢資料,"
    "在單一畫面上提供「現況 KPI、趨勢、AI 預測、即時事件、異常告警與建議行動」六大維度的監控能力。")
add_para(doc,
    "本系統以「AI 副駕駛 + 人類拍板」為設計核心:AI 提供信心度、判定依據、誤判/漏判代價(Value Matrix)與建議下一步,"
    "最後由現場管理人員確認執行,以兼顧效率、安全與法規責任。")

add_heading(doc, "1.1 核心能力", level=2)
add_bullets(doc, [
    "車輛辨識:車牌讀取 (ALPR v2.3) 與白名單/黑名單比對,陌生車牌自動建檔 (UNKNOWN-NNN)。",
    "人員辨識:人臉比對 (FaceID v1.8) 與證照效期檢查 (高空作業證、電焊證、工安證等)。",
    "AI 預測:依當日已發生的進出資料,對未來 4 小時人員進場數進行預測,並附信賴帶 (±30%)。",
    "異常告警:四大類型 — 黑名單車牌、證照過期、陌生車牌、API 資料延遲。",
    "AI 副駕駛摘要:每小時自動產生重點摘要與優先處理建議。",
    "雙層 Tab 架構:主分類 (工地看板/人員管理/車輛管理/系統設定) + 6 個子頁籤。",
    "自動輪播:可依設定秒數自動切換子頁籤,適合大螢幕看板模式。",
    "跳卡浮層:重要事件以浮層卡片彈出,告警卡片含「確認/誤判」按鈕。",
])

# ============================================================
# 2. 使用對象
# ============================================================
add_heading(doc, "2. 主要使用對象與情境總覽", level=1)
add_table(doc,
    header=["角色", "主要目標", "最常使用的頁籤"],
    rows=[
        ["工地主任", "掌握全工地人車現況,排除異常", "全工地總覽 → 異常事件牆"],
        ["工安督導", "確認進場人員證照與作業類別合規", "人員看板 → 異常事件牆"],
        ["保全 / 警衛", "驗證車輛白名單,阻擋黑名單", "車輛看板 → 跳卡浮層"],
        ["IT 管理員", "監看 API 健康度,排查資料延遲", "全工地總覽 (API KPI) → 異常事件牆"],
        ["管理階層", "查看 KPI、趨勢、AI 摘要", "全工地總覽 → 趨勢全螢幕"],
    ],
    col_widths=[3, 6, 5])

# ============================================================
# 3. 介面架構
# ============================================================
add_heading(doc, "3. 介面架構與導覽元件", level=1)

add_heading(doc, "3.1 頂部主 Tab 列", level=2)
add_para(doc, "畫面最上方為主分類列,目前 Demo 僅啟用「工地看板」,其餘三項為預留模組:")
add_bullets(doc, [
    "工地看板 (Dashboard) — 預設啟用",
    "人員管理 (Personnel Mgmt) — 預留位置",
    "車輛管理 (Vehicle Mgmt) — 預留位置",
    "系統設定 (Settings) — 預留位置",
])
add_para(doc, "右上方顯示:現在日期時間、API 狀態 (例如「● API 正常 2/2」)。")

add_heading(doc, "3.2 子頁籤列與控制列", level=2)
add_bullets(doc, [
    "工地選擇器:下拉式選單,選項為「全部工地 / A01~C04 (共 12 個工地)」。",
    "子頁籤 1~6:全工地總覽、單一工地、車輛看板、人員看板、趨勢全螢幕、異常事件牆,每個頁籤右側顯示對應的鍵盤快捷數字。",
    "自動輪播按鈕:啟用後依各頁設定秒數循環切換 (Overview/Site/Trend = 30s,Vehicle/Personnel/Alert = 20s)。",
    "刷新倒數:每 60 秒倒數一次,可按「R」立即重置。",
])

# ============================================================
# 4. 子頁籤
# ============================================================
add_heading(doc, "4. 子頁籤功能詳述", level=1)

add_heading(doc, "4.1 全工地總覽 (Overview)", level=2)
add_para(doc, "用途:一眼掌握所有工地總體現況。")
add_para(doc, "畫面組成:", bold=True)
add_bullets(doc, [
    "AI 副駕駛摘要區:顯示近 1 小時關鍵異常與建議優先處理。",
    "四個大 KPI 卡:今日人員進場 / 今日車輛進場 / 異常事件 / API 狀態。",
    "12 個工地小卡:每張顯示人員與車輛即時在場數、12 點 mini 長條趨勢、異常或延遲標籤。",
    "右側「最新進出快訊」即時清單。",
])

add_heading(doc, "4.2 單一工地 (Site Board)", level=2)
add_para(doc, "用途:聚焦單一工地的 KPI 與趨勢預測。")
add_bullets(doc, [
    "6 個 KPI 卡:人員進場/離場/在場、車輛進場/離場/在場。",
    "今日 0-24H 進出趨勢與 AI 預測圖:含實際長條 (進/離場)、車輛折線、未來 4H 預測虛線與 ±30% 信賴帶。",
    "目前時間以紅色「目前」垂直參考線標示 (Ch 13 You Are Here)。",
    "最新事件列表 (6 筆) 與最新現場影像區 (車牌截圖、車輛照、人臉縮圖)。",
])

add_heading(doc, "4.3 車輛看板 (Vehicle)", level=2)
add_bullets(doc, [
    "4 個 KPI:進場車次 / 離場車次 / 目前在場 / 陌生車牌數量。",
    "最新車輛截圖區:大圖 + 車牌特寫 + 承包商資訊 + 閘門狀態。",
    "每小時車輛進出趨勢柱狀圖。",
    "最新車輛事件清單:含進/出方向 Pill、時間、車牌縮圖、承包商、狀態徽章。",
])

add_heading(doc, "4.4 人員看板 (Personnel)", level=2)
add_bullets(doc, [
    "4 個 KPI:進場人次 / 離場人次 / 目前在場 / 證照異常數 (過期 + 缺漏)。",
    "每小時人員進出趨勢柱狀圖。",
    "最新人員辨識清單:人臉縮圖 + 員工編號 + 承包商 + 證照狀態徽章。",
])

add_heading(doc, "4.5 趨勢全螢幕 (Trend)", level=2)
add_para(doc, "用途:會議室大螢幕展示用,字級放大、留白拉大,單一工地一日完整趨勢圖。")
add_bullets(doc, [
    "ComposedChart:人員進/離場柱狀 + 車輛進/離場折線。",
    "紅色「目前 N 時」參考線。",
    "每分鐘自動刷新。",
])

add_heading(doc, "4.6 異常事件牆 (Alert)", level=2)
add_para(doc, "用途:集中呈現需立即處理的所有異常,並提供 AI 解釋與行動建議。")
add_para(doc, "上方紅色橫幅:顯示最嚴重的單一異常摘要 (例:車牌平台回傳延遲 92 秒)。")
add_para(doc, "AI 副駕駛摘要區:整體風險快讀。")
add_para(doc, "異常事件牆 (4 欄卡片):每張告警卡含:", bold=True)
add_bullets(doc, [
    "類別標籤:黑名單 / 證照過期 / 陌生車牌 / 資料延遲。",
    "AI 信心度 (Confidence Chip,如 AI 99%、AI 73%、規則判定)。",
    "目標物件視覺 (車牌縮圖或人臉縮圖,API 類則顯示大字「API」)。",
    "工地代碼與發生次數標記 (例如「7 日內第 3 次」)。",
    "判定依據 (Explainability) — 文字描述為何 AI 認定為異常。",
    "誤判代價 (FP) / 漏判代價 (FN) 二格 Value Matrix。",
    "AI 建議下一步:1~3 條序號建議。",
    "兩個拍板按鈕:「採納並處理」/「誤判」。",
])
add_para(doc, "排序原則:黑名單 / 證照過期 > API 斷線 > 陌生車牌 > 資料延遲。", italic=True)

# ============================================================
# 5. AI 副駕駛與可解釋性
# ============================================================
add_heading(doc, "5. AI 副駕駛與可解釋性", level=1)
add_para(doc, "本系統將 AI 視為「副駕駛」,所有 AI 判讀都附帶可解釋性元件,協助使用者快速決定是否覆寫:")
add_table(doc,
    header=["元件", "出現位置", "意義"],
    rows=[
        ["ConfidenceChip", "事件列、跳卡、告警卡", "顯示 AI 信心度百分比;≥90% 綠、75-89% 黃、<75% 紅;無分數時顯示「規則判定」"],
        ["ExplainBlock", "告警跳卡、告警卡片", "顯示「判定依據」與「資料來源」(例:FaceID v1.8 · 證照資料庫)"],
        ["Value Matrix", "告警卡片", "並列誤判代價 (FP) 與漏判代價 (FN) 文字"],
        ["AI 建議", "告警卡片", "1~3 條建議行動,讓人類拍板"],
        ["AI 副駕駛摘要", "全工地總覽、異常事件牆", "每小時自動產生的執行摘要,標示優先處理對象"],
    ],
    col_widths=[3.5, 4.5, 7])

# ============================================================
# 6. 跳卡浮層
# ============================================================
add_heading(doc, "6. 跳卡浮層 (Flash Card) 即時通知", level=1)
add_para(doc, "右下角浮層,最多同時顯示 3 張,系統每 6 秒會將最新事件推入。")
add_bullets(doc, [
    "一般事件卡 (進場/離場):5 秒自動消失。",
    "告警卡 (黑名單/證照過期):8 秒自動消失,內含 ExplainBlock 與「確認告警」、「標記為誤判」按鈕。",
    "車輛事件:顯示車輛與車牌縮圖、承包商、閘門結果。",
    "人員事件:顯示人臉縮圖、員工編號、證照狀態。",
])

# ============================================================
# 7. 執行路徑
# ============================================================
add_heading(doc, "7. 完整執行路徑 (Execution Paths)", level=1)
add_para(doc, "下列為從「啟動」到「結束處理」的所有可達路徑分類列舉。")

add_heading(doc, "7.1 啟動與導覽路徑", level=2)
add_numbered(doc, [
    "開啟瀏覽器 → 載入 dashboard-standalone_demo2.html → 預設進入「工地看板 → 全工地總覽」。",
    "點選頂部主 Tab → 切換主分類 (僅工地看板可用)。",
    "點選子頁籤或按 1~6 → 切換到對應子頁。",
    "選擇工地下拉 → 將上下文範圍切換到指定工地或「全部工地」。",
    "點擊「自動輪播」→ 系統依設定秒數循環切換子頁。",
    "按「R」鍵 → 重置 60 秒刷新倒數。",
])

add_heading(doc, "7.2 監看與分析路徑", level=2)
add_numbered(doc, [
    "全工地總覽 → 觀察 4 大 KPI → 點選某工地小卡 (帶有「異常」/「延遲」標籤) → 切換到單一工地或異常事件牆深入查看。",
    "單一工地 → 對照趨勢圖紅色「目前」參考線 → 比較實際 vs AI 預測 (虛線) → 評估是否要派工或叫車。",
    "車輛看板 → 查看陌生車牌數 → 切換到異常事件牆 → 點選對應陌生車牌告警卡 → 採納或誤判。",
    "人員看板 → 查看「證照異常」KPI → 若 ≥1 則切換到異常事件牆 → 處理對應「證照過期」告警卡。",
    "趨勢全螢幕 → 大螢幕展示用,無互動。",
])

add_heading(doc, "7.3 告警處理路徑", level=2)
add_numbered(doc, [
    "跳卡浮層彈出告警 → 立刻點「確認告警」或「標記為誤判」。",
    "或不操作 → 8 秒後自動消失 → 仍可於異常事件牆找到該事件。",
    "在異常事件牆檢視 AI 信心度 + ExplainBlock + 代價 → 採用 AI 建議列表的第 1 條 → 點「採納並處理」。",
    "若認為 AI 誤判 → 點「誤判」→ 系統記錄樣本以供未來模型迭代 (人在迴路 HITL)。",
])

add_heading(doc, "7.4 系統健康監看路徑", level=2)
add_numbered(doc, [
    "頂部右上「● API 正常 X/Y」→ 出現紅 / 黃時通知 IT。",
    "異常事件牆「資料延遲」類別告警 → 依建議檢查 API 服務 / 切換備援通道 / 通報 IT。",
])

# ============================================================
# 8. 使用情境
# ============================================================
add_heading(doc, "8. 使用情境 (Scenarios)", level=1)

add_heading(doc, "情境 A:早班尖峰大量進場 (07:00-09:00)", level=2)
add_para(doc, "工地主任於早班開始前 30 分鐘啟動大螢幕。打開「趨勢全螢幕」對照昨日同時段,確認進場節奏正常。"
              "若 AI 預測值高於信賴帶上界且實際進場曲線跟上,可預先通知警衛多開一道閘門。")

add_heading(doc, "情境 B:黑名單車牌闖入嘗試", level=2)
add_para(doc, "保全在警衛室監看跳卡浮層,看到「車輛告警 · ZZZ-7777」紅色卡片彈出。"
              "AI 信心度 99%,代價提示顯示漏判代價極高 (安全風險)。"
              "保全立即按「確認告警」並依 AI 建議「通知保全在閘門攔截」、「通報工地主任」、「保留進入時段影像」。")

add_heading(doc, "情境 C:電焊工證照過期", level=2)
add_para(doc, "工安督導於早會前打開「異常事件牆」,看到「李O華 / E-0981」告警 (7 日內第 3 次)。"
              "依 AI 建議聯繫承包商「隆泰工程」更新證照,並於補件前暫停其電焊作業。")

add_heading(doc, "情境 D:人臉 API 異常", level=2)
add_para(doc, "IT 管理員看到頂部 API 狀態變成「11/12」,異常事件牆出現「人臉 API · B04 西側門 · 延遲 92 秒」。"
              "依建議:檢查 API 服務狀態 → 切換到備援辨識通道 → 確認 B04 進出仍被記錄。")

add_heading(doc, "情境 E:陌生車牌反覆出現", level=2)
add_para(doc, "車輛看板「陌生車牌」KPI 上升到 4。督導打開異常事件牆「UNKNOWN-019」告警,信心度 73% (黃)。"
              "依建議請警衛詢問來訪事由;若為合作廠商,將該車牌加入白名單以避免重複告警 (在預留「車輛管理」模組維護)。")

add_heading(doc, "情境 F:管理階層巡視看板", level=2)
add_para(doc, "高階主管走進指揮中心。系統處於「自動輪播」模式,每 20-30 秒換頁。"
              "AI 副駕駛摘要區直接呈現「過去 1 小時 4 件異常,集中於 A03,優先處理李O華證照與 ZZZ-7777」,"
              "主管不需理解原始數據即可掌握重點。")

# ============================================================
# 9. 使用案例
# ============================================================
add_heading(doc, "9. 使用案例 (Use Cases)", level=1)
add_table(doc,
    header=["UC #", "案例名稱", "主要角色", "前置條件", "結束狀態"],
    rows=[
        ["UC-01", "切換子頁籤監看", "全部使用者", "已開啟系統", "目標子頁顯示於畫面"],
        ["UC-02", "啟用自動輪播", "管理階層", "處於工地看板主 Tab", "頁籤依秒數自動循環"],
        ["UC-03", "選定單一工地檢視", "工地主任", "已選擇工地下拉", "KPI/趨勢以該工地為範圍"],
        ["UC-04", "AI 預測檢視", "工地主任", "進入單一工地頁", "預測虛線 + 信賴帶顯示"],
        ["UC-05", "處理黑名單告警", "保全", "跳卡或事件牆出現黑名單卡", "AI 建議被執行,事件被採納"],
        ["UC-06", "處理證照過期告警", "工安督導", "出現證照過期卡", "通知承包商,作業暫停"],
        ["UC-07", "標記 AI 誤判", "工安督導", "出現信心度 ≥75% 但情境不符之告警", "事件被標記誤判,送回模型訓練池"],
        ["UC-08", "監看 API 健康度", "IT 管理員", "API 狀態 ≠ N/N", "重啟服務或切換備援"],
        ["UC-09", "陌生車牌覆核", "保全 + 工地主任", "車輛看板陌生車牌 ≥1", "車牌被加入白名單或記為訪客"],
        ["UC-10", "趨勢全螢幕投影", "管理階層", "進入趨勢頁籤", "大螢幕呈現完整 24H 趨勢"],
        ["UC-11", "AI 副駕駛摘要查閱", "管理階層", "進入總覽或事件牆", "摘要文字呈現重點異常"],
        ["UC-12", "鍵盤快捷導覽", "熟手使用者", "畫面已聚焦", "按 1~6 即切換頁籤,按 R 重置倒數"],
    ],
    col_widths=[1.5, 3.5, 2.5, 4.0, 3.5])

# ============================================================
# 10. 快速鍵
# ============================================================
add_heading(doc, "10. 快速鍵與快捷操作", level=1)
add_table(doc,
    header=["按鍵 / 動作", "效果"],
    rows=[
        ["1", "切換到「全工地總覽」"],
        ["2", "切換到「單一工地」"],
        ["3", "切換到「車輛看板」"],
        ["4", "切換到「人員看板」"],
        ["5", "切換到「趨勢全螢幕」"],
        ["6", "切換到「異常事件牆」"],
        ["R / r", "重置 60 秒刷新倒數"],
        ["點選自動輪播按鈕", "啟用 / 停用自動輪播"],
        ["點選工地下拉", "切換目前工地上下文 (含 ALL)"],
    ],
    col_widths=[5, 10])

# ============================================================
# 11. 色彩與圖示
# ============================================================
add_heading(doc, "11. 狀態色彩與圖示說明", level=1)
add_table(doc,
    header=["色彩 / 圖示", "代表意義", "出現場景"],
    rows=[
        ["青藍 (#22D3EE)", "人員進場 / 系統主色 / AI 副駕駛", "進場長條、Logo、AI 文字"],
        ["紫 (#A78BFA)", "人員離場", "離場長條"],
        ["橘 (#F59E0B)", "車輛進場", "車輛折線"],
        ["粉紅 (#FB7185)", "車輛離場", "車輛離場折線"],
        ["綠 (#34D399)", "通行 / 白名單 / 高信心度 (≥90%)", "通行徽章、白名單徽章、Confidence Chip"],
        ["黃 (#FBBF24)", "陌生 / 資料延遲 / 中信心度 (75-89%)", "陌生車牌、API 延遲、警示帶"],
        ["紅 (#F87171)", "告警 / 黑名單 / 證照過期 / 低信心度 (<75%)", "告警卡、Now Line、紅框截圖"],
        ["進 / 出 Pill", "事件方向", "事件列表左側徽章"],
        ["虛線 (5 5)", "AI 預測值", "趨勢圖未來小時"],
    ],
    col_widths=[3.5, 4.5, 7])

# ============================================================
# 12. 常見問題
# ============================================================
add_heading(doc, "12. 常見問題與排除", level=1)
add_table(doc,
    header=["問題", "可能原因", "建議處理"],
    rows=[
        ["「人員管理 / 車輛管理 / 系統設定」按不動",
         "Demo 版預留位置 (disabled)", "等待正式版上線"],
        ["跳卡浮層沒出現", "近 6 秒內無新事件,或事件已超過 3 張上限", "等待下一輪推送"],
        ["AI 預測虛線從目前小時往後不見", "未到該小時或預測資料未產出", "稍候並按 R 重置倒數"],
        ["異常事件牆出現「資料延遲」卡片", "對應工地的辨識 API 心跳中斷 > 5 分鐘",
         "依 AI 建議檢查服務、切備援、通知 IT"],
        ["「目前在場」KPI 與實際不符",
         "進出事件配對失敗或人員未掃離場", "由現場補登,人工調整"],
        ["按鍵盤無反應", "視窗未取得焦點", "點一下畫面任意處再試"],
    ],
    col_widths=[4.5, 4.5, 6])

# ============================================================
# 13. 名詞表
# ============================================================
add_heading(doc, "13. 名詞對照表", level=1)
add_table(doc,
    header=["名詞", "解釋"],
    rows=[
        ["ALPR", "Automatic License Plate Recognition,自動車牌辨識。本系統使用 v2.3。"],
        ["FaceID v1.8", "人臉辨識服務版本"],
        ["白名單 / 黑名單", "允許 / 拒絕進場的車牌或人員清單"],
        ["UNKNOWN-NNN", "ALPR 辨識到但白名單無此車時自動建立的暫時識別碼"],
        ["Confidence", "AI 給予該判讀的信心度,0~1 (顯示為百分比)"],
        ["FP / FN", "False Positive (誤判) / False Negative (漏判)"],
        ["Value Matrix", "比較 FP 與 FN 代價的決策框架"],
        ["HITL", "Human-In-The-Loop,人在迴路;告警最終由人類拍板"],
        ["Confidence Cone", "AI 預測的信賴帶區域 (上下界陰影)"],
        ["Now Line", "趨勢圖中標示「目前」的紅色垂直參考線"],
    ],
    col_widths=[4, 11])

# ============================================================
# 附錄
# ============================================================
doc.add_page_break()
add_heading(doc, "附錄 A:本手冊資料來源", level=1)
add_para(doc,
    "本手冊內容由 demo/dashboard-standalone_demo2.html 之 React 元件與 MOCK_DATA "
    "(SITES、OVERVIEW_KPI、SITE_KPI、HOURLY_TREND、LATEST_EVENTS、ALERTS、HOURLY_TREND_FORECAST) 整理而成。"
    "若實際生產環境的工地數、KPI 欄位、告警類型有所增減,請參考最終版 API 規格更新本文件。")

add_heading(doc, "附錄 B:預留模組待補資訊", level=1)
add_para(doc, "下列模組目前為 Demo 預留,完整化前需補充以下資料:")
add_bullets(doc, [
    "人員管理:員工資料表欄位 (工號、姓名、承包商、職類、證照清單與效期、人臉註冊照)。",
    "車輛管理:車輛主檔欄位 (車牌、承包商、車種、白/黑名單狀態、進場限制時段)。",
    "系統設定:角色與權限矩陣、API 端點與金鑰、輪播秒數、刷新頻率、告警通知通道 (Email / Webhook / LINE)。",
])

# ============================================================
# Save
# ============================================================
import os
out_dir = "/home/user/CarRecogDashboard/docs"
os.makedirs(out_dir, exist_ok=True)
out_path = os.path.join(out_dir, "CarDashboard_User_Manual.docx")
doc.save(out_path)
print(out_path)

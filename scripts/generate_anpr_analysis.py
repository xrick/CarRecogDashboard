"""Generate ANPR -> Vehicle Detection Dashboard integration / programming analysis (docx)."""
import os
from docx import Document
from docx.shared import Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

FONT = "Microsoft JhengHei"


def _eastasia(run):
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), FONT)


def set_cell_bg(cell, color_hex):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), color_hex)
    tc_pr.append(shd)


def add_heading(doc, text, level=1):
    h = doc.add_heading(text, level=level)
    for run in h.runs:
        run.font.name = FONT
        run.font.color.rgb = RGBColor(0x0F, 0x3B, 0x73)
        _eastasia(run)
    return h


def add_para(doc, text, bold=False, size=11, italic=False):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.font.name = FONT
    run.font.size = Pt(size)
    run.bold = bold
    run.italic = italic
    _eastasia(run)
    return p


def add_code(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.4)
    run = p.add_run(text)
    run.font.name = "Consolas"
    run.font.size = Pt(9.5)
    run.font.color.rgb = RGBColor(0x10, 0x2A, 0x43)
    pPr = p._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), "F0F3F8")
    pPr.append(shd)
    return p


def add_bullets(doc, items):
    for it in items:
        p = doc.add_paragraph(style="List Bullet")
        run = p.add_run(it)
        run.font.name = FONT
        run.font.size = Pt(11)
        _eastasia(run)


def add_numbered(doc, items):
    for it in items:
        p = doc.add_paragraph(style="List Number")
        run = p.add_run(it)
        run.font.name = FONT
        run.font.size = Pt(11)
        _eastasia(run)


def add_table(doc, header, rows, col_widths=None):
    table = doc.add_table(rows=1 + len(rows), cols=len(header))
    table.style = "Light Grid Accent 1"
    for i, h in enumerate(header):
        c = table.rows[0].cells[i]
        c.text = ""
        run = c.paragraphs[0].add_run(h)
        run.bold = True
        run.font.size = Pt(10)
        run.font.name = FONT
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        _eastasia(run)
        set_cell_bg(c, "0F3B73")
    for r_idx, row in enumerate(rows, start=1):
        for c_idx, val in enumerate(row):
            c = table.rows[r_idx].cells[c_idx]
            c.text = ""
            run = c.paragraphs[0].add_run(str(val))
            run.font.size = Pt(9.5)
            run.font.name = FONT
            _eastasia(run)
    if col_widths:
        for row in table.rows:
            for i, w in enumerate(col_widths):
                row.cells[i].width = Cm(w)
    return table


doc = Document()
st = doc.styles["Normal"]
st.font.name = FONT
st.font.size = Pt(11)
rpr = st.element.get_or_add_rPr()
rf = OxmlElement("w:rFonts")
rf.set(qn("w:eastAsia"), FONT)
rpr.append(rf)

# ---------------- 封面 ----------------
t = doc.add_paragraph()
t.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = t.add_run("Smart ANPR 相機\n車輛偵測看板系統 — 整合與程式設計分析")
r.bold = True
r.font.size = Pt(26)
r.font.name = FONT
r.font.color.rgb = RGBColor(0x0F, 0x3B, 0x73)
_eastasia(r)

s = doc.add_paragraph()
s.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = s.add_run("API · 操作範例 · 資料流 · 看板系統設計建議")
r.font.size = Pt(13)
r.italic = True
r.font.color.rgb = RGBColor(0x5A, 0x70, 0x99)
_eastasia(r)

doc.add_paragraph()
m = doc.add_paragraph()
m.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = m.add_run("分析來源:Smart_ANPR_Camera_Web_5.0_Operation_Manual_V1.1.0.pdf\n"
              "技術補充:中性简体_HTTP_API_协议规范V3.87.pdf  ·  產出日期:2026/05/15")
r.font.size = Pt(10.5)
_eastasia(r)
doc.add_page_break()

# ---------------- 0. 重要說明 ----------------
add_heading(doc, "0. 重要說明:文件性質與資料補充", 1)
add_para(doc,
    "您指定分析的《Smart ANPR Camera Web 5.0 Operation Manual V1.1.0》是一份「網頁介面操作手冊」,"
    "內容描述的是透過相機 Web 後台「用滑鼠點選」完成各項設定的步驟,本身並不包含可供程式呼叫的 HTTP API "
    "端點、請求/回應範例或程式碼。", bold=True)
add_para(doc,
    "因此,為了滿足您「找出 API、範例、操作某樣功能(刪除白名單、加入黑名單)、提供程式設計相關資料」的需求,"
    "本文件做了兩件事:")
add_numbered(doc, [
    "從 Operation Manual 萃取與「車輛偵測看板系統」相關的功能、資料、整合介面與人工操作路徑。",
    "從同目錄下的《HTTP API 協議規範 V3.87》補充對應的可程式化 HTTP API 與實際請求範例 "
    "(此相機系列與該 API 規範屬同一產品線,recordUpdater / recordFinder / snapManager 介面通用)。",
])
add_para(doc, "若您要 100% 僅依 Operation Manual,則白名單/黑名單只能用第 9 章描述的「Web 後台人工操作」"
              "與「ITSAPI 推播 / FTP / 平台伺服器」整合;真正的 CRUD API 必須以 HTTP API 規範為準。", italic=True)
add_para(doc, "需要您補充的資料(若要落地實作):", bold=True)
add_bullets(doc, [
    "相機實際 IP、帳號/密碼(API 採 HTTP Digest 認證)。",
    "相機韌體版本與機型(確認 recordUpdater / snapManager 介面是否啟用、CGI 是否開放)。",
    "看板系統後端語言/框架(以便提供對應 SDK 範例)。",
    "是否已有平台伺服器(ITSAPI / 大華 SDK / 第三方 VMS)作為事件匯流。",
])

# ---------------- 1. 系統架構與資料流 ----------------
add_heading(doc, "1. 車輛偵測看板系統架構與資料流", 1)
add_para(doc, "依手冊與 API 規範,一個車輛偵測看板的端到端資料流如下:")
add_para(doc,
    "[ANPR 相機] --(抓拍/辨識車牌)--> [事件推播 attachFileProc / ITSAPI] --> "
    "[看板後端 (代理 + 資料庫)] --> [看板前端 Dashboard UI]\n"
    "                                  ↑\n"
    "         [白名單/黑名單 CRUD recordUpdater.cgi] <-- 看板管理頁",
    size=10)
add_table(doc,
    ["層", "角色", "對應手冊 / API 章節"],
    [
        ["相機端", "車牌辨識 (ANPR)、白/黑名單比對、閘門控制、抓拍存圖", "手冊 §7 ANPR、§7.4 名單、§7.5 閘門"],
        ["整合介面", "ITSAPI 推播、FTP/平台伺服器上傳、訂閱事件串流、CGI 名單管理", "手冊 §9.3、§16.2.9.3、§16.3.4;API §4.4.3、§10.3"],
        ["看板後端", "接收事件、寫入 DB、轉發前端、代理名單 CRUD(隱藏相機憑證)", "需自建"],
        ["看板前端", "KPI、趨勢、即時事件牆、名單管理 UI(對應 demo dashboard)", "demo/dashboard-standalone_demo2.html"],
    ],
    [2.0, 6.5, 6.5])

# ---------------- 2. 整合介面總覽 ----------------
add_heading(doc, "2. 與看板系統相關的整合介面(出自 Operation Manual)", 1)
add_table(doc,
    ["介面", "用途", "手冊章節", "看板用途"],
    [
        ["ITSAPI", "將擷取的車輛/違規資訊以 JSON 主動推播到平台伺服器", "§16.2.9.3", "即時事件來源(推模式)"],
        ["平台伺服器 Platform Server", "自動/手動上傳 SD 卡抓拍圖到平台", "§9.3", "事件截圖來源"],
        ["FTP / SFTP 網路儲存", "斷網自動回補(ANR),網路恢復後上傳", "§9.2.2", "圖片儲存與回補"],
        ["RTMP", "推流到第三方平台做即時影像", "§16.2.11", "看板內嵌即時影像"],
        ["訂閱告警 Subscribe Alarm", "黑名單命中、外部告警、IVS 等事件", "§16.3.4", "異常事件牆 / 跳卡來源"],
        ["Snapshot/Passed Vehicles Records", "查詢過車紀錄、白名單通行報表並匯出", "§11.1、§11.6", "歷史趨勢與報表"],
        ["Basic Services (CGI/ONVIF)", "開放 CGI 介面與信任站台白名單", "§16.2.10", "啟用 HTTP API 的前提"],
    ],
    [2.6, 5.2, 1.8, 4.0])
add_para(doc, "ITSAPI 技術要點(§16.2.9.3):所有通訊基於 HTTP、符合 RFC2616、支援 Digest 認證;"
              "業務資料為 JSON,HTTP 標頭 Content-Type: application/json;charset=UTF-8;"
              "支援註冊、心跳保活、上傳內容類型 ALL/Data/Picture、失敗重傳次數設定。", italic=True)

# ---------------- 3. 即時過車事件訂閱 ----------------
add_heading(doc, "3. 看板資料核心:即時過車事件訂閱 API", 1)
add_para(doc, "看板「最新進出/即時事件牆」的資料來源,建議用事件訂閱長連線(API §4.4.3「訂閱抓圖及相關事件」)。")
add_para(doc, "Request", bold=True)
add_code(doc,
    "GET http://<server>/cgi-bin/snapManager.cgi?action=attachFileProc\n"
    "    &channel=1&heartbeat=5&Flags[0]=Event&Events=[TrafficJunction]\n"
    "認證: HTTP Digest")
add_para(doc, "重要參數", bold=True)
add_table(doc,
    ["參數", "說明"],
    [
        ["channel", "視訊通道,-1 表示訂閱所有通道"],
        ["heartbeat", "心跳秒數 [1,60],逾時無資料會送字串 \"Heartbeat\" 保活"],
        ["Flags[0]=Event", "訂閱類型固定為 Event"],
        ["Events", "事件代碼陣列。TrafficJunction=交通卡口(過車);亦可 All、TrafficParking、FaceRecognition 等"],
    ],
    [3.0, 11.0])
add_para(doc, "Response(multipart/x-mixed-replace 串流,持續推送):", bold=True)
add_code(doc,
    "HTTP/1.1 200 OK\n"
    "Content-Type: multipart/x-mixed-replace; boundary=<boundary>\n\n"
    "--<boundary>\n"
    "Content-Type: text/plain\n\n"
    "Events[0].Channel=0\n"
    "Events[0].EventBaseInfo.Code=TrafficJunction\n"
    "Events[0].EventBaseInfo.Action=Pulse\n"
    "Events[0].Lane=1\n"
    "Events[0].PTS=42949485818.0\n"
    "Events[0].TrafficCar.PlateNumber=ZZZ12345\n"
    "Events[0].TrafficCar.DeviceAddress=XXXRoad\n"
    "...")
add_para(doc, "看板可直接把 TrafficCar.PlateNumber、Lane、時間、通道、截圖映射到 demo 的事件卡片欄位"
              "(displayName / site / time / direction)。黑名單命中則另發 Vehicle blocklist 告警(見 §16.3.4)。")

# ---------------- 4. 白名單/黑名單 CRUD API ----------------
add_heading(doc, "4. 白名單 / 黑名單 CRUD API(看板管理頁核心)", 1)
add_para(doc, "名單表名:紅名單(白名單/允許清單)= \"TrafficRedList\";黑名單(封鎖清單)= \"TrafficBlackList\"。"
              "PlateNumber 為唯一鍵;紅/黑名單各最多 110,000 筆(手冊 §7.4.2 / §7.4.3)。", bold=True)
add_table(doc,
    ["操作", "URL (GET 除註明外)", "關鍵參數"],
    [
        ["新增", "/cgi-bin/recordUpdater.cgi?action=insert", "name, PlateNumber(必填), MasterOfCar, PlateColor, BeginTime, CancelTime, AuthorityList.OpenGate(僅紅名單)"],
        ["更新", "/cgi-bin/recordUpdater.cgi?action=update", "name, recno(必填), PlateNumber, …"],
        ["刪除(依 recno)", "/cgi-bin/recordUpdater.cgi?action=remove", "name, recno"],
        ["刪除(依車牌,增強版)", "/cgi-bin/recordUpdater.cgi?action=removeEx", "name, PlateNumber 或 recno"],
        ["查詢", "/cgi-bin/recordFinder.cgi?action=find", "name, condition.PlateNumber, StartTime, EndTime, count"],
        ["批次匯入 CSV", "POST /cgi-bin/trafficRecord.cgi?action=uploadFile", "Type, format=CSV, code=utf-8;body 為 multipart 檔案"],
        ["非同步匯出", "/cgi-bin/recordUpdater.cgi?action=exportAsyncFile", "name, filename, format"],
    ],
    [2.8, 5.6, 6.0])
add_para(doc, "回應:insert 回 RecNo=<id>(-1 表示設備非同步處理);update/remove/removeEx/upload 回 OK;"
              "find 回 totalCount / found / records[] 列表。", italic=True)

# ---------------- 5. 操作範例 ----------------
add_heading(doc, "5. 操作範例(對應您指定的功能)", 1)

add_heading(doc, "5.1 加入黑名單某一筆資料", 2)
add_para(doc, "將車牌 AC00001(車主 ZhangSan、黃牌、藍色車身、有效期間 2011-01-01~2011-01-10)加入黑名單:")
add_code(doc,
    "GET http://192.168.1.108/cgi-bin/recordUpdater.cgi?action=insert\n"
    "    &name=TrafficBlackList\n"
    "    &PlateNumber=AC00001\n"
    "    &MasterOfCar=ZhangSan\n"
    "    &PlateColor=Yellow\n"
    "    &VehicleColor=Blue\n"
    "    &BeginTime=2011-01-01%2012:00:00\n"
    "    &CancelTime=2011-01-10%2012:00:00\n\n"
    "回應: RecNo=12345")

add_heading(doc, "5.2 刪除白名單某一筆資料", 2)
add_para(doc, "方式 A — 已知記錄 id(recno):")
add_code(doc,
    "GET http://192.168.1.108/cgi-bin/recordUpdater.cgi?action=remove\n"
    "    &name=TrafficRedList&recno=12345\n\n"
    "回應: OK")
add_para(doc, "方式 B — 只知道車牌(增強版 removeEx,看板最常用):")
add_code(doc,
    "GET http://192.168.1.108/cgi-bin/recordUpdater.cgi?action=removeEx\n"
    "    &name=TrafficRedList&PlateNumber=AC00001\n\n"
    "回應: OK")

add_heading(doc, "5.3 查詢名單(供看板列表/搜尋)", 2)
add_code(doc,
    "GET http://192.168.1.108/cgi-bin/recordFinder.cgi?action=find\n"
    "    &name=TrafficBlackList\n"
    "    &condition.PlateNumber=AC00001\n"
    "    &count=100\n\n"
    "回應:\n"
    "totalCount=1000\n"
    "found=100\n"
    "records[0].RecNo=12345\n"
    "records[0].PlateNumber=AC00001\n"
    "records[0].MasterOfCar=ZhangSan")

add_heading(doc, "5.4 更新名單某一筆", 2)
add_code(doc,
    "GET http://192.168.1.108/cgi-bin/recordUpdater.cgi?action=update\n"
    "    &name=TrafficBlackList&recno=12345&PlateNumber=AC00001\n"
    "    &MasterOfCar=ZhangSan&PlateColor=Yellow\n\n"
    "回應: OK")

add_heading(doc, "5.5 批次匯入黑名單 CSV", 2)
add_code(doc,
    "POST http://192.168.1.108/cgi-bin/trafficRecord.cgi?action=uploadFile\n"
    "     &Type=TrafficBlackList&format=CSV&code=utf-8\n"
    "Content-Type: multipart/form-data; boundary=<boundary>\n\n"
    "--<boundary>\n"
    'Content-Disposition: form-data; name="blackfile"; filename="TrafficBlackList.CSV"\n'
    "Content-Type: application/vnd.ms-excel\n\n"
    "<CSV 檔內容>\n"
    "--<boundary>--\n\n"
    "回應: OK")

# ---------------- 6. 程式碼範例 ----------------
add_heading(doc, "6. 程式設計範例(看板後端代理)", 1)
add_para(doc, "建議由看板後端代理相機,不要讓前端直接接觸相機憑證。以下為 Python (requests, Digest 認證) 範例。")
add_para(doc, "6.1 加入黑名單 / 刪除白名單", bold=True)
add_code(doc,
    "import requests\n"
    "from requests.auth import HTTPDigestAuth\n\n"
    "CAM = 'http://192.168.1.108'\n"
    "AUTH = HTTPDigestAuth('admin', 'PASSWORD')\n\n"
    "def add_blacklist(plate, owner='', begin='', cancel=''):\n"
    "    p = {'action':'insert','name':'TrafficBlackList','PlateNumber':plate,\n"
    "         'MasterOfCar':owner,'BeginTime':begin,'CancelTime':cancel}\n"
    "    r = requests.get(f'{CAM}/cgi-bin/recordUpdater.cgi', params=p, auth=AUTH, timeout=10)\n"
    "    return r.text  # RecNo=12345\n\n"
    "def delete_whitelist_by_plate(plate):\n"
    "    p = {'action':'removeEx','name':'TrafficRedList','PlateNumber':plate}\n"
    "    r = requests.get(f'{CAM}/cgi-bin/recordUpdater.cgi', params=p, auth=AUTH, timeout=10)\n"
    "    return r.text  # OK")
add_para(doc, "6.2 訂閱即時過車事件(串流)", bold=True)
add_code(doc,
    "def stream_events(on_event):\n"
    "    url = f'{CAM}/cgi-bin/snapManager.cgi'\n"
    "    p = {'action':'attachFileProc','channel':-1,'heartbeat':5,\n"
    "         'Flags[0]':'Event','Events':'[TrafficJunction]'}\n"
    "    with requests.get(url, params=p, auth=AUTH, stream=True, timeout=None) as r:\n"
    "        for line in r.iter_lines(decode_unicode=True):\n"
    "            if not line or line == 'Heartbeat':\n"
    "                continue\n"
    "            if line.startswith('Events[') and 'TrafficCar.PlateNumber' in line:\n"
    "                on_event(line.split('=',1)[1])  # 推到看板 WebSocket")
add_para(doc, "curl 等效:", bold=True)
add_code(doc,
    "curl --digest -u admin:PASSWORD \\\n"
    '  "http://192.168.1.108/cgi-bin/recordUpdater.cgi?action=insert&name=TrafficBlackList&PlateNumber=AC00001"')

# ---------------- 7. 無 API 時的人工操作路徑 ----------------
add_heading(doc, "7. 替代路徑:Operation Manual 的 Web 後台人工操作(§7.4)", 1)
add_para(doc, "若相機未開放 CGI,或僅能依手冊操作,白名單/黑名單維護路徑如下(手冊 §7.4.2 / §7.4.3):")
add_numbered(doc, [
    "登入相機 Web → 首頁點 ANPR → 選 Vehicle Blocklist/Allowlist → Allowlist 或 Blocklist。",
    "新增單筆:點 Add → 填 Plate No.、Owner Name、Vehicle Color、Start/End Time → OK(勾 Add More 可連續新增)。",
    "批次新增:點 Import → Download Template → 填好 → Select File → Open。",
    "編輯:點該筆的編輯圖示修改。",
    "刪除單筆:點該筆的刪除圖示(若啟用『依允許清單開閘』,該車將無法通行)。",
    "刪除全部:點 Clear(不可復原)。刪除過期:點 Clear Expired Data。",
    "匯出:點 Export,選擇是否加密 → OK。",
])
add_para(doc, "Fuzzy Match(§7.4.1):允許相機誤判首尾字元或近似字元(如 0<->D 規則,最多 6 條),"
              "看板顯示通行原因時可一併呈現此機制造成的『模糊命中』。", italic=True)
add_para(doc, "閘門控制模式(§7.5.1):All Vehicles / Licensed Vehicles / Allowlist / Command(Platform)。"
              "選 Command(Platform) 時看板/平台可直接下令開閘(對應 demo『閘門已開啟』狀態)。", italic=True)

# ---------------- 8. 看板資料模型對應 ----------------
add_heading(doc, "8. 相機資料 → 看板欄位對應(對照 demo dashboard)", 1)
add_table(doc,
    ["看板欄位(demo)", "相機/API 來源", "說明"],
    [
        ["displayName(車牌)", "TrafficCar.PlateNumber", "過車事件車牌"],
        ["statusType whitelist/alert", "命中 TrafficRedList / TrafficBlackList", "比對名單結果"],
        ["status 白名單/告警", "Vehicle blocklist 告警(§16.3.4)", "黑名單命中觸發告警"],
        ["accessResult 閘門已開啟", "Barrier Control 結果(§7.5)", "是否開閘"],
        ["confidence(信心度)", "辨識可信度 / 是否 Fuzzy Match", "完整辨識 vs 模糊命中"],
        ["time / site / Lane", "事件 PTS、DeviceAddress、Lane", "時間/地點/車道"],
        ["截圖", "Platform Server / FTP 上傳之抓拍圖(§9)", "事件縮圖"],
        ["趨勢/報表", "Passed Vehicles Records(§11.6)匯出", "歷史統計"],
    ],
    [3.6, 5.0, 5.8])

# ---------------- 9. 安全性 ----------------
add_heading(doc, "9. 安全性與整合注意事項", 1)
add_bullets(doc, [
    "認證:HTTP API 採 Digest 認證;ITSAPI 可另開使用者/認證密碼(§16.2.9.3)。",
    "啟用前提:需在 Basic Services 開啟 CGI;建議用 Basic Services 信任站台白名單限制可存取 IP(§16.2.10)。",
    "傳輸加密:建議啟用 HTTPS / SFTP,避免在 URL 明文帶帳密(§14.2.2、§9.2.2)。",
    "防護:Account Lockout、Anti-DoS、Firewall 可能擋住高頻輪詢,事件請優先用訂閱長連線而非輪詢(§14.3)。",
    "容量限制:紅/黑名單各上限 110,000 筆;PlateNumber 唯一,重複新增需先 update 或 removeEx。",
    "斷線回補:啟用 ANR + FTP,網路恢復後自動補傳抓拍圖,避免看板事件缺漏(§9.2.2)。",
    "代理層:看板後端應封裝相機憑證,前端只呼叫後端 REST,並做操作稽核(誰刪了哪筆名單)。",
])

# ---------------- 10. 名詞對照 ----------------
add_heading(doc, "10. 名詞與表名對照", 1)
add_table(doc,
    ["名詞", "說明"],
    [
        ["ANPR", "Automatic Number Plate Recognition,自動車牌辨識"],
        ["Allowlist / 紅名單 / TrafficRedList", "允許通行清單(本文之『白名單』)"],
        ["Blocklist / 黑名单 / TrafficBlackList", "封鎖清單(本文之『黑名單』)"],
        ["recordUpdater.cgi", "名單寫入介面:insert/update/remove/removeEx/export"],
        ["recordFinder.cgi", "名單查詢介面:find"],
        ["snapManager.cgi attachFileProc", "事件與抓圖訂閱長連線"],
        ["ITSAPI", "智慧交通平台推播協議(JSON over HTTP,Digest)"],
        ["ANR", "Automatic Network Recovery,斷網自動回補"],
        ["recno / RecNo", "名單記錄的唯一 id"],
        ["Fuzzy Match", "車牌模糊比對(容許首尾/近似字元誤判)"],
    ],
    [5.5, 8.5])

doc.add_page_break()
add_heading(doc, "附錄:資料來源頁碼索引", 1)
add_table(doc,
    ["主題", "Operation Manual", "HTTP API 規範"],
    [
        ["白名單/黑名單操作", "§7.4(p.37-40)", "§10.3(p.680-688)"],
        ["閘門控制", "§7.5(p.40-41)", "—"],
        ["事件訂閱", "§16.3.4(p.124-126)", "§4.4.3(p.68-70)"],
        ["平台/上傳", "§9.3(p.62)、§16.2.9.3(p.117-118)", "—"],
        ["過車紀錄查詢", "§11.6(p.69)", "§10.3.4(p.682-683)"],
    ],
    [4.0, 5.5, 4.5])
add_para(doc, "本文件之 API 端點與請求範例均逐字取自前述 PDF;若實機韌體與規範版本不同,以實機回應為準。", italic=True)

out_dir = "/home/user/CarRecogDashboard/docs"
os.makedirs(out_dir, exist_ok=True)
out_path = os.path.join(out_dir, "ANPR_Dashboard_Integration_Analysis.docx")
doc.save(out_path)
print(out_path)

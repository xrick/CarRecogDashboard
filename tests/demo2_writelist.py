"""
白名單管理 PyQt5 範例 — 對應「中性简体 HTTP API 协议规范 V3.87」第 10.7 章
车辆组 / AllowListDB 相關 endpoint。

執行：
    source ../myenv/bin/activate
    python demo1.py
"""

from __future__ import annotations

import json
import re
import sys
import traceback
from dataclasses import dataclass
from typing import Any

import requests
from requests.auth import HTTPDigestAuth
import urllib3
from PyQt5.QtCore import QObject, QThread, Qt, pyqtSignal

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QSpinBox, QStatusBar, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)


# ----------------------------- API Client ----------------------------- #

@dataclass
class DeviceConfig:
    host: str           # 192.168.1.108 or 192.168.1.108:80
    username: str
    password: str
    scheme: str = "http"
    timeout: float = 8.0

    @property
    def base_url(self) -> str:
        return f"{self.scheme}://{self.host}"


class ApiError(RuntimeError):
    pass


# ---- helpers ---- #

_KV_TOKEN = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def _parse_kv(text: str) -> dict[str, Any]:
    """解析 Dahua 設備的 `key=value` 純文字回應（含巢狀 `records[0].PlateNumber=...`）。
    用於 §10.3 recordFinder/recordUpdater 等舊式 endpoint 的回應。"""
    root: dict[str, Any] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or "=" not in line or line.startswith("#"):
            continue
        key, _, val = line.partition("=")
        tokens: list[tuple[str, Any]] = []
        for m in _KV_TOKEN.finditer(key.strip()):
            name, idx = m.group(1), m.group(2)
            tokens.append(("k", name) if name is not None else ("i", int(idx)))
        cur: Any = root
        for i, (kind, t) in enumerate(tokens):
            is_last = i == len(tokens) - 1
            next_kind = None if is_last else tokens[i + 1][0]
            if kind == "k":
                if is_last:
                    cur[t] = val.strip()
                else:
                    if t not in cur or not isinstance(cur[t], (list, dict)):
                        cur[t] = [] if next_kind == "i" else {}
                    cur = cur[t]
            else:  # index
                while len(cur) <= t:
                    cur.append({} if next_kind == "k" else (None if is_last else []))
                if is_last:
                    cur[t] = val.strip()
                else:
                    if not isinstance(cur[t], (list, dict)):
                        cur[t] = {} if next_kind == "k" else []
                    cur = cur[t]
    return root


# ---- base HTTP client ---- #

class _BaseHttpClient:
    """共用 Digest session、tracing、HTTP method wrappers、smoke_test。"""

    def __init__(self, cfg: DeviceConfig, on_trace: "callable | None" = None,
                 session: requests.Session | None = None):
        self.cfg = cfg
        self._session = session or requests.Session()
        self._session.auth = HTTPDigestAuth(cfg.username, cfg.password)
        # ANPR 相機通常使用自簽憑證；HTTPS 時關閉驗證並抑制 warning。
        self._session.verify = False
        self._on_trace = on_trace

    def _trace(self, msg: str) -> None:
        if self._on_trace:
            try:
                self._on_trace(msg)
            except Exception:
                pass

    def _request(self, method: str, path: str, *, payload: dict[str, Any] | None = None,
                 params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.cfg.base_url}{path}"
        body_preview = json.dumps(payload, ensure_ascii=False)[:300] if payload is not None else ""
        suffix = f"  body={body_preview}" if payload is not None else (
            f"  params={params}" if params else ""
        )
        self._trace(f"→ {method} {url}{suffix}")
        try:
            r = self._session.request(
                method, url,
                json=payload if payload is not None else None,
                params=params,
                timeout=self.cfg.timeout,
                headers={"Content-Type": "application/json"} if payload is not None else None,
            )
        except requests.exceptions.SSLError as e:
            raise ApiError(f"SSL 錯誤 @ {url}：{e}") from e
        except requests.exceptions.ConnectionError as e:
            raise ApiError(
                f"連線失敗 @ {url}\n"
                f"→ 檢查 host/port/scheme（目前 scheme={self.cfg.scheme}）與設備是否在線。\n"
                f"原始錯誤：{e}"
            ) from e
        except requests.exceptions.Timeout as e:
            raise ApiError(f"請求逾時 @ {url}（{self.cfg.timeout}s）") from e
        except requests.RequestException as e:
            raise ApiError(f"網路錯誤 @ {url}：{e}") from e

        body_text = r.text or ""
        self._trace(f"← {r.status_code} {url}  body={body_text[:300]}")

        if r.status_code == 401:
            raise ApiError("認證失敗 (401)：請確認帳號 / 密碼")
        if r.status_code >= 400:
            raise ApiError(
                f"HTTP {r.status_code} @ {url}\n"
                f"response body: {body_text[:1000]}"
            )

        return r  # type: ignore[return-value]

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        r = self._request("POST", path, payload=payload)
        if not r.content:
            return {}
        try:
            return r.json()
        except json.JSONDecodeError:
            raise ApiError(f"回應非 JSON @ {r.url}：{r.text[:300]}")

    def _get_text(self, path: str, params: dict[str, Any] | None = None) -> str:
        """GET 並回 raw text — 用於 §10.3 舊式 key=value 回應。"""
        r = self._request("GET", path, params=params)
        return r.text or ""

    def smoke_test(self) -> str:
        """打 magicBox.getSystemInfo (Digest GET) 驗證設備可達 + 帳密正確。
        幾乎所有中性/Dahua-like 韌體都有這支，可以拿來把「連線/帳密」與
        「VehicleRegisterDB 是否支援」兩個問題拆開。"""
        return self._get_text("/cgi-bin/magicBox.cgi", {"action": "getSystemInfo"})


class VehicleRegisterDBClient(_BaseHttpClient):
    """章節 10.7 机动车管理 — VehicleRegisterDB.
    新版 POST + JSON + HTTP Digest 認證（RFC 7616, 章節 3.4）。"""

    mode_label = "新版 (§10.7 VehicleRegisterDB)"

    # 10.7.1 createGroup
    def create_group(self, name: str, detail: str, group_type: str = "AllowListDB") -> str:
        resp = self._post(
            "/cgi-bin/api/VehicleRegisterDB/createGroup",
            {"group": {"GroupName": name, "GroupDetail": detail, "GroupType": group_type}},
        )
        return resp.get("groupID", "")

    # 10.7.3 deleteGroup
    def delete_group(self, group_id: str) -> None:
        self._post("/cgi-bin/api/VehicleRegisterDB/deleteGroup", {"groupID": group_id})

    # 10.7.4 findGroup ("" = 查全部)
    def find_group(self, group_id: str = "") -> list[dict[str, Any]]:
        resp = self._post("/cgi-bin/api/VehicleRegisterDB/findGroup", {"groupID": group_id})
        return resp.get("GroupList", []) or []

    # 10.7.5 multiAppend
    def append_vehicles(self, vehicles: list[dict[str, Any]]) -> dict[str, Any]:
        return self._post("/cgi-bin/api/VehicleRegisterDB/multiAppend", {"vehicle": vehicles})

    # 10.7.6 modifyVehicle
    def modify_vehicle(self, vehicle: dict[str, Any]) -> None:
        self._post("/cgi-bin/api/VehicleRegisterDB/modifyVehicle", {"vehicle": vehicle})

    # 10.7.7 deleteVehicle
    def delete_vehicle(self, group_id: str, plate_number: str = "", uid: int | None = None) -> None:
        body: dict[str, Any] = {"groupID": group_id}
        if uid is not None:
            body["UID"] = uid
        if plate_number:
            body["plateNumber"] = plate_number
        self._post("/cgi-bin/api/VehicleRegisterDB/deleteVehicle", {"vehicle": body})

    # 10.7.8 / 10.7.9 / 10.7.10 startFind → doFind → stopFind
    def list_vehicles(self, group_id: str, page_size: int = 50,
                      extra_filter: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        vehicle_filter: dict[str, Any] = {"GroupID": group_id, "UID": 0}
        if extra_filter:
            vehicle_filter.update(extra_filter)

        start_resp = self._post(
            "/cgi-bin/api/VehicleRegisterDB/startFind",
            {"vehicle": vehicle_filter},
        )
        token = start_resp.get("token")
        total = int(start_resp.get("totalCount", 0))
        if token is None:
            raise ApiError(f"startFind 回應缺少 token：{start_resp}")

        items: list[dict[str, Any]] = []
        try:
            begin = 0
            while begin < total:
                resp = self._post(
                    "/cgi-bin/api/VehicleRegisterDB/doFind",
                    {"condition": {"token": token, "beginNumber": begin, "count": page_size}},
                )
                cands = resp.get("results", {}).get("candidates", []) or []
                if not cands:
                    break
                for c in cands:
                    items.append(c.get("Vehicle", c))
                begin += len(cands)
        finally:
            try:
                self._post("/cgi-bin/api/VehicleRegisterDB/stopFind", {"token": token})
            except ApiError:
                pass
        return items


class LegacyTrafficListClient(_BaseHttpClient):
    """章節 10.3 交通记录 — 舊式 GET + query-string + key=value 回應。
    給 XC-204BLPR / ITC413-PW4D / 其他 §10.7 不支援的韌體使用。

    與 VehicleRegisterDBClient 同樣的方法簽名，但底層走 recordUpdater.cgi / recordFinder.cgi，
    且只支援兩張固定的「合成群組」：TrafficRedList（白）/ TrafficBlackList（黑）。
    """

    mode_label = "舊版 (§10.3 TrafficRedList/BlackList)"

    SYNTHETIC_GROUPS = [
        {"groupID": "TrafficRedList",   "groupName": "白名單 (TrafficRedList)",
         "groupDetail": "舊式韌體 §10.3", "groupType": "AllowListDB", "groupSize": -1},
        {"groupID": "TrafficBlackList", "groupName": "黑名單 (TrafficBlackList)",
         "groupDetail": "舊式韌體 §10.3", "groupType": "BlockListDB", "groupSize": -1},
    ]

    def create_group(self, name: str, detail: str, group_type: str = "AllowListDB") -> str:
        raise ApiError("舊式 §10.3 韌體不支援自建群組；只可使用 TrafficRedList / TrafficBlackList")

    def delete_group(self, group_id: str) -> None:
        raise ApiError("舊式 §10.3 韌體不支援刪除群組")

    def find_group(self, group_id: str = "") -> list[dict[str, Any]]:
        if not group_id:
            return [dict(g) for g in self.SYNTHETIC_GROUPS]
        return [dict(g) for g in self.SYNTHETIC_GROUPS if g["groupID"] == group_id]

    # 10.3.4 recordFinder.find
    def list_vehicles(self, group_id: str, page_size: int = 50,
                      extra_filter: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if group_id not in {"TrafficRedList", "TrafficBlackList"}:
            raise ApiError(f"舊式 API 不認得 GroupID={group_id}（限 TrafficRedList / TrafficBlackList）")
        params: dict[str, Any] = {"action": "find", "name": group_id, "count": page_size}
        if extra_filter:
            for k, v in extra_filter.items():
                params[f"condition.{k}"] = v
        text = self._get_text("/cgi-bin/recordFinder.cgi", params)
        parsed = _parse_kv(text)
        records = parsed.get("records", []) or []
        return [
            {
                "UID": rec.get("RecNo", ""),
                "PlateNumber": rec.get("PlateNumber", ""),
                "GroupID": group_id,
                "Name": rec.get("MasterOfCar", ""),
                "PhoneNo": "",
                "PlateCountry": "",
            }
            for rec in records if isinstance(rec, dict)
        ]

    # 10.3.1 recordUpdater.insert
    def append_vehicles(self, vehicles: list[dict[str, Any]]) -> dict[str, Any]:
        for v in vehicles:
            gid = v.get("GroupID") or "TrafficRedList"
            params: dict[str, Any] = {
                "action": "insert",
                "name": gid,
                "PlateNumber": v["PlateNumber"],
            }
            if v.get("Name"):
                params["MasterOfCar"] = v["Name"]
            # 白名單預設授權開閘
            if gid == "TrafficRedList":
                params["AuthorityList.OpenGate"] = "true"
            self._get_text("/cgi-bin/recordUpdater.cgi", params)
        return {}

    # 10.3.2 recordUpdater.update
    def modify_vehicle(self, vehicle: dict[str, Any]) -> None:
        if "UID" not in vehicle:
            raise ApiError("舊式 API 修改記錄需要 RecNo (UID)")
        gid = vehicle.get("GroupID") or "TrafficRedList"
        params: dict[str, Any] = {
            "action": "update",
            "name": gid,
            "recno": vehicle["UID"],
            "PlateNumber": vehicle["PlateNumber"],
        }
        if vehicle.get("Name"):
            params["MasterOfCar"] = vehicle["Name"]
        self._get_text("/cgi-bin/recordUpdater.cgi", params)

    # 10.3.5 recordUpdater.removeEx (可用 plate 當識別)
    def delete_vehicle(self, group_id: str, plate_number: str = "",
                       uid: int | None = None) -> None:
        gid = group_id or "TrafficRedList"
        params: dict[str, Any] = {"action": "removeEx", "name": gid}
        if uid is not None and str(uid).strip():
            params["recno"] = uid
        if plate_number:
            params["PlateNumber"] = plate_number
        if "recno" not in params and "PlateNumber" not in params:
            raise ApiError("removeEx 至少需提供 recno 或 PlateNumber")
        self._get_text("/cgi-bin/recordUpdater.cgi", params)


# ----------------------------- Worker Thread ----------------------------- #

class Worker(QObject):
    """同步呼叫丟到 QThread，避免阻塞 UI。"""
    success = pyqtSignal(object)
    failure = pyqtSignal(str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn, self._args, self._kwargs = fn, args, kwargs

    def run(self):
        try:
            self.success.emit(self._fn(*self._args, **self._kwargs))
        except Exception as e:
            self.failure.emit(f"{e}\n{traceback.format_exc()}")


# ----------------------------- Vehicle Dialog ----------------------------- #

class VehicleDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, vehicle: dict[str, Any] | None = None,
                 group_id: str = "", mode: str = "add"):
        super().__init__(parent)
        self.setWindowTitle("新增車輛" if mode == "add" else "修改車輛")
        v = vehicle or {}

        form = QFormLayout()
        self.plate = QLineEdit(str(v.get("PlateNumber", "")))
        self.group_id = QLineEdit(str(v.get("GroupID", group_id)))
        self.group_id.setReadOnly(True)
        self.uid = QLineEdit(str(v.get("UID", "")))
        self.uid.setReadOnly(mode == "modify")
        self.owner_name = QLineEdit(str(v.get("Name", "")))
        self.phone = QLineEdit(str(v.get("PhoneNo", "")))
        self.country = QLineEdit(str(v.get("PlateCountry", "CN")))

        form.addRow("GroupID", self.group_id)
        form.addRow("UID", self.uid)
        form.addRow("車牌號碼 *", self.plate)
        form.addRow("車主姓名", self.owner_name)
        form.addRow("電話", self.phone)
        form.addRow("國別 (ISO3166)", self.country)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(btns)

    def value(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "GroupID": self.group_id.text().strip(),
            "PlateNumber": self.plate.text().strip(),
        }
        if self.uid.text().strip().isdigit():
            d["UID"] = int(self.uid.text().strip())
        if self.owner_name.text().strip():
            d["Name"] = self.owner_name.text().strip()
        if self.phone.text().strip():
            d["PhoneNo"] = self.phone.text().strip()
        if self.country.text().strip():
            d["PlateCountry"] = self.country.text().strip()
        return d


# ----------------------------- Main Window ----------------------------- #

class WhitelistWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("白名單管理 — VehicleRegisterDB Demo")
        self.resize(1100, 720)
        self.client: VehicleRegisterDBClient | None = None
        self._thread: QThread | None = None
        self._worker: Worker | None = None

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.addWidget(self._build_conn_box())
        root.addWidget(self._build_group_box(), 1)
        root.addWidget(self._build_vehicle_box(), 2)
        root.addWidget(self._build_log_box(), 1)
        self.setStatusBar(QStatusBar())

    # top: connection
    def _build_conn_box(self) -> QGroupBox:
        box = QGroupBox("設備連線（HTTP Digest 認證）")
        layout = QGridLayout(box)
        # self.ed_host = QLineEdit("192.168.1.108")
        self.ed_host = QLineEdit("192.168.0.10")
        self.ed_user = QLineEdit("admin")
        self.ed_pass = QLineEdit()
        self.ed_pass.setEchoMode(QLineEdit.Password)
        self.cb_https = QCheckBox("HTTPS")
        self.btn_connect = QPushButton("連線 / 重新建立 Session")
        self.btn_connect.clicked.connect(self.on_connect)

        layout.addWidget(QLabel("Host"),     0, 0); layout.addWidget(self.ed_host, 0, 1)
        layout.addWidget(QLabel("User"),     0, 2); layout.addWidget(self.ed_user, 0, 3)
        layout.addWidget(QLabel("Password"), 0, 4); layout.addWidget(self.ed_pass, 0, 5)
        layout.addWidget(self.cb_https,      0, 6)
        layout.addWidget(self.btn_connect,   0, 7)
        layout.setColumnStretch(1, 2)
        layout.setColumnStretch(3, 1)
        layout.setColumnStretch(5, 2)
        return box

    def _build_group_box(self) -> QGroupBox:
        box = QGroupBox("車輛組 (AllowListDB / BlockListDB)")
        v = QVBoxLayout(box)

        bar = QHBoxLayout()
        self.btn_find_groups = QPushButton("查詢所有群組 (findGroup)")
        self.btn_find_groups.clicked.connect(self.on_find_groups)
        self.btn_create_group = QPushButton("新增白名單群組 (createGroup)")
        self.btn_create_group.clicked.connect(self.on_create_group)
        self.btn_delete_group = QPushButton("刪除選取群組 (deleteGroup)")
        self.btn_delete_group.clicked.connect(self.on_delete_group)
        bar.addWidget(self.btn_find_groups)
        bar.addWidget(self.btn_create_group)
        bar.addWidget(self.btn_delete_group)
        bar.addStretch(1)
        v.addLayout(bar)

        self.tbl_groups = QTableWidget(0, 5)
        self.tbl_groups.setHorizontalHeaderLabels(["GroupID", "Name", "Detail", "Type", "Size"])
        self.tbl_groups.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tbl_groups.setSelectionBehavior(QTableWidget.SelectRows)
        self.tbl_groups.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tbl_groups.itemSelectionChanged.connect(self._on_group_selected)
        v.addWidget(self.tbl_groups)
        return box

    def _build_vehicle_box(self) -> QGroupBox:
        box = QGroupBox("白名單車輛 — 取讀 / 新增 / 修改 / 刪除")
        v = QVBoxLayout(box)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("目前 GroupID："))
        self.cmb_group = QComboBox()
        self.cmb_group.setMinimumWidth(220)
        bar.addWidget(self.cmb_group)

        bar.addWidget(QLabel("分頁大小："))
        self.spn_page = QSpinBox()
        self.spn_page.setRange(1, 1000)
        self.spn_page.setValue(50)
        bar.addWidget(self.spn_page)

        self.btn_list_vehicles = QPushButton("取讀白名單 (startFind→doFind→stopFind)")
        self.btn_list_vehicles.clicked.connect(self.on_list_vehicles)
        self.btn_add_vehicle = QPushButton("新增車牌 (multiAppend)")
        self.btn_add_vehicle.clicked.connect(self.on_add_vehicle)
        self.btn_mod_vehicle = QPushButton("修改選取車牌 (modifyVehicle)")
        self.btn_mod_vehicle.clicked.connect(self.on_modify_vehicle)
        self.btn_del_vehicle = QPushButton("刪除選取車牌 (deleteVehicle)")
        self.btn_del_vehicle.clicked.connect(self.on_delete_vehicle)
        bar.addWidget(self.btn_list_vehicles)
        bar.addWidget(self.btn_add_vehicle)
        bar.addWidget(self.btn_mod_vehicle)
        bar.addWidget(self.btn_del_vehicle)
        bar.addStretch(1)
        v.addLayout(bar)

        self.tbl_vehicles = QTableWidget(0, 6)
        self.tbl_vehicles.setHorizontalHeaderLabels(
            ["UID", "PlateNumber", "GroupID", "Name", "PhoneNo", "PlateCountry"]
        )
        self.tbl_vehicles.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tbl_vehicles.setSelectionBehavior(QTableWidget.SelectRows)
        self.tbl_vehicles.setEditTriggers(QTableWidget.NoEditTriggers)
        v.addWidget(self.tbl_vehicles)
        return box

    def _build_log_box(self) -> QGroupBox:
        box = QGroupBox("Log")
        v = QVBoxLayout(box)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        v.addWidget(self.log)
        return box

    # helpers
    def _log(self, msg: str) -> None:
        self.log.append(msg)

    def _require_client(self) -> VehicleRegisterDBClient | None:
        if self.client is None:
            QMessageBox.warning(self, "尚未連線", "請先按上方「連線」按鈕建立 Session。")
            return None
        return self.client

    def _busy(self, busy: bool) -> None:
        for btn in (self.btn_find_groups, self.btn_create_group, self.btn_delete_group,
                    self.btn_list_vehicles, self.btn_add_vehicle, self.btn_mod_vehicle,
                    self.btn_del_vehicle, self.btn_connect):
            btn.setEnabled(not busy)
        self.statusBar().showMessage("處理中…" if busy else "就緒")

    def _run_async(self, fn, on_success, *args, on_failure=None, **kwargs) -> None:
        """執行阻塞呼叫於 QThread。
        on_failure: 若提供，覆寫預設錯誤處理（用於能力探測等需自訂錯誤分支的情境）。
        """
        if self._thread is not None:
            QMessageBox.information(self, "請稍候", "上一個請求仍在執行。")
            return
        self._busy(True)
        self._thread = QThread(self)
        self._worker = Worker(fn, *args, **kwargs)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)

        def _cleanup() -> None:
            """必須在執行使用者 callback **之前**跑完，否則 callback 內若再
            觸發 _run_async 會被開頭的 self._thread is not None 擋掉。"""
            self._busy(False)
            t, w = self._thread, self._worker
            self._thread = None
            self._worker = None
            if t is not None:
                t.quit()
                t.wait()
                t.deleteLater()
            if w is not None:
                w.deleteLater()

        def _finish_ok(r):
            _cleanup()
            on_success(r)

        def _finish_err(e):
            _cleanup()
            if on_failure is not None:
                on_failure(e)
            else:
                self._on_error(e)

        self._worker.success.connect(_finish_ok)
        self._worker.failure.connect(_finish_err)
        self._thread.start()

    def _on_error(self, msg: str) -> None:
        first = msg.splitlines()[0]
        self._log(f"[ERROR] {first}")
        QMessageBox.critical(self, "API 錯誤", first)

    # handlers
    def on_connect(self) -> None:
        host = self.ed_host.text().strip()
        user = self.ed_user.text().strip()
        pwd = self.ed_pass.text()
        if not host or not user:
            QMessageBox.warning(self, "欄位不完整", "Host / User 必填")
            return
        cfg = DeviceConfig(
            host=host, username=user, password=pwd,
            scheme="https" if self.cb_https.isChecked() else "http",
        )
        self._cfg = cfg
        self.client = VehicleRegisterDBClient(cfg, on_trace=self._log)
        self._log(f"[OK] Session 已建立：{cfg.base_url} as {user}")
        self.statusBar().showMessage(f"已連線 — 偵測中…")

        # Smoke test → 能力探測 → 列群組。
        def _smoke_ok(info: str) -> None:
            head = (info or "").splitlines()[0:3]
            self._log("[OK] smoke_test 通過：" + " | ".join(s.strip() for s in head if s.strip()))
            self._probe_api_mode()

        self._run_async(self.client.smoke_test, _smoke_ok)

    def _probe_api_mode(self) -> None:
        """先試新版 §10.7 findGroup；若回 HTTP 4xx 自動切換到 §10.3 舊版 API。"""
        def _ok(groups: list[dict[str, Any]]) -> None:
            self._log(f"[detect] 新版 §10.7 VehicleRegisterDB 可用")
            self.statusBar().showMessage(f"已連線 — API: {self.client.mode_label}")
            self._render_groups(groups)

        def _fail(msg: str) -> None:
            first = msg.splitlines()[0]
            # 只有「設備明確回 4xx」才視為「新版不支援」；網路 / SSL / 401 等不切換。
            looks_unsupported = (
                "HTTP 400" in msg or "HTTP 404" in msg or "HTTP 405" in msg
                or "HTTP 501" in msg
            )
            if not looks_unsupported:
                self._on_error(msg)
                return
            self._log(f"[detect] 新版 API 不支援（{first}） → 切換到舊版 §10.3 TrafficRedList")
            # 沿用同一個 requests.Session，避免 Digest 重新挑戰
            old_session = self.client._session
            self.client = LegacyTrafficListClient(
                self._cfg, on_trace=self._log, session=old_session
            )
            self.statusBar().showMessage(f"已連線 — API: {self.client.mode_label}")
            self.on_find_groups()

        self._run_async(self.client.find_group, _ok, "", on_failure=_fail)

    def on_find_groups(self) -> None:
        c = self._require_client()
        if not c:
            return
        self._run_async(c.find_group, self._render_groups, "")

    def _render_groups(self, groups: list[dict[str, Any]]) -> None:
        self.tbl_groups.setRowCount(0)
        self.cmb_group.clear()
        for g in groups:
            row = self.tbl_groups.rowCount()
            self.tbl_groups.insertRow(row)
            cells = [
                g.get("groupID", ""), g.get("groupName", ""), g.get("groupDetail", ""),
                str(g.get("groupType", "")).strip(), str(g.get("groupSize", "")),
            ]
            for col, val in enumerate(cells):
                self.tbl_groups.setItem(row, col, QTableWidgetItem(str(val)))
            self.cmb_group.addItem(
                f"{g.get('groupID', '')}  —  {g.get('groupName', '')}",
                g.get("groupID", ""),
            )
        self._log(f"[OK] findGroup 回傳 {len(groups)} 個群組。")

    def _on_group_selected(self) -> None:
        rows = self.tbl_groups.selectionModel().selectedRows()
        if not rows:
            return
        gid_item = self.tbl_groups.item(rows[0].row(), 0)
        if not gid_item:
            return
        idx = self.cmb_group.findData(gid_item.text())
        if idx >= 0:
            self.cmb_group.setCurrentIndex(idx)

    def on_create_group(self) -> None:
        c = self._require_client()
        if not c:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("新增白名單群組")
        f = QFormLayout(dlg)
        ed_name = QLineEdit("白名單-A")
        ed_detail = QLineEdit("Demo")
        cmb_type = QComboBox()
        cmb_type.addItems(["AllowListDB", "BlockListDB"])
        f.addRow("名稱 *", ed_name)
        f.addRow("備註",   ed_detail)
        f.addRow("類型",   cmb_type)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        f.addRow(btns)
        if dlg.exec_() != QDialog.Accepted:
            return
        name = ed_name.text().strip()
        if not name:
            QMessageBox.warning(self, "名稱必填", "請輸入群組名稱。")
            return

        def _ok(gid: str) -> None:
            self._log(f"[OK] createGroup → GroupID = {gid}")
            self.on_find_groups()

        self._run_async(c.create_group, _ok, name, ed_detail.text().strip(), cmb_type.currentText())

    def on_delete_group(self) -> None:
        c = self._require_client()
        if not c:
            return
        rows = self.tbl_groups.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "未選擇", "請先在表格中選擇要刪除的群組。")
            return
        gid = self.tbl_groups.item(rows[0].row(), 0).text()
        if QMessageBox.question(
                self, "確認刪除",
                f"確定要刪除 GroupID = {gid} 嗎？（其下所有車輛也會被刪除）"
        ) != QMessageBox.Yes:
            return

        def _ok(_):
            self._log(f"[OK] deleteGroup {gid}")
            self.on_find_groups()

        self._run_async(c.delete_group, _ok, gid)

    def _current_group_id(self) -> str:
        return self.cmb_group.currentData() or ""

    def on_list_vehicles(self) -> None:
        c = self._require_client()
        if not c:
            return
        gid = self._current_group_id()
        if not gid:
            QMessageBox.information(self, "請先選 Group", "請先在群組下拉選擇一個 GroupID。")
            return

        def _ok(rows: list[dict[str, Any]]) -> None:
            self.tbl_vehicles.setRowCount(0)
            for v in rows:
                r = self.tbl_vehicles.rowCount()
                self.tbl_vehicles.insertRow(r)
                cells = [
                    str(v.get("UID", "")), v.get("PlateNumber", ""), v.get("GroupID", ""),
                    v.get("Name", ""), v.get("PhoneNo", ""), v.get("PlateCountry", ""),
                ]
                for col, val in enumerate(cells):
                    self.tbl_vehicles.setItem(r, col, QTableWidgetItem(str(val)))
            self._log(f"[OK] startFind/doFind/stopFind → GroupID={gid} 共 {len(rows)} 筆")

        self._run_async(c.list_vehicles, _ok, gid, self.spn_page.value())

    def on_add_vehicle(self) -> None:
        c = self._require_client()
        if not c:
            return
        gid = self._current_group_id()
        if not gid:
            QMessageBox.information(self, "請先選 Group", "請先在群組下拉選擇一個 GroupID。")
            return
        dlg = VehicleDialog(self, group_id=gid, mode="add")
        if dlg.exec_() != QDialog.Accepted:
            return
        v = dlg.value()
        if not v.get("PlateNumber"):
            QMessageBox.warning(self, "缺欄位", "PlateNumber 必填。")
            return

        def _ok(_resp):
            self._log(f"[OK] multiAppend：{v.get('PlateNumber')} → {gid}")
            self.on_list_vehicles()

        self._run_async(c.append_vehicles, _ok, [v])

    def on_modify_vehicle(self) -> None:
        c = self._require_client()
        if not c:
            return
        rows = self.tbl_vehicles.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "未選擇", "請先在白名單列表中選擇一筆。")
            return
        r = rows[0].row()
        cur = {
            "UID": self.tbl_vehicles.item(r, 0).text(),
            "PlateNumber": self.tbl_vehicles.item(r, 1).text(),
            "GroupID": self.tbl_vehicles.item(r, 2).text(),
            "Name": self.tbl_vehicles.item(r, 3).text(),
            "PhoneNo": self.tbl_vehicles.item(r, 4).text(),
            "PlateCountry": self.tbl_vehicles.item(r, 5).text(),
        }
        dlg = VehicleDialog(self, vehicle=cur, mode="modify")
        if dlg.exec_() != QDialog.Accepted:
            return
        v = dlg.value()
        if "UID" not in v:
            QMessageBox.warning(self, "缺 UID", "修改車輛需要 UID。")
            return

        def _ok(_):
            self._log(f"[OK] modifyVehicle UID={v['UID']}")
            self.on_list_vehicles()

        self._run_async(c.modify_vehicle, _ok, v)

    def on_delete_vehicle(self) -> None:
        c = self._require_client()
        if not c:
            return
        rows = self.tbl_vehicles.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "未選擇", "請先選擇要刪除的車牌。")
            return
        r = rows[0].row()
        uid_str = self.tbl_vehicles.item(r, 0).text().strip()
        plate = self.tbl_vehicles.item(r, 1).text().strip()
        gid = self.tbl_vehicles.item(r, 2).text().strip() or self._current_group_id()
        uid = int(uid_str) if uid_str.isdigit() else None
        if QMessageBox.question(
                self, "確認刪除",
                f"刪除車牌？\nUID={uid_str}\nPlate={plate}\nGroup={gid}"
        ) != QMessageBox.Yes:
            return

        def _ok(_):
            self._log(f"[OK] deleteVehicle UID={uid_str} Plate={plate}")
            self.on_list_vehicles()

        self._run_async(c.delete_vehicle, _ok, gid, plate, uid)


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = WhitelistWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

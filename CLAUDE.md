# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Internal tooling for a "Car Recognition Dashboard" that interacts with **Dahua / 中性 ANPR cameras** (e.g. XC-204BLPR, ITC413-PW4D series) over their L7 HTTP API. The final deliverable is a web dashboard (Chinese title: 中華航空AI智慧工安辨識事件管理系統 / "China Airlines AI Security Event Management"), but `src/` is currently an empty placeholder; all active code lives in `demo/` (UI demos) and `tests/` (exploratory utilities — these are **not** pytest tests, they are stand-alone scripts).

No build/lint/test framework is configured. There is no `requirements.txt` — the active environment is the in-tree venv at `myenv/` (Python 3.12; pre-installed: PyQt5, opencv-python 4.13, requests, scapy, netifaces, urllib3).

## Running things

```bash
source run_env.sh            # equivalent to: source myenv/bin/activate
python demo/demo1.py         # PyQt5 whitelist (VehicleRegisterDB) manager demo
python tests/rtsp_viewer_parallel_3.py   # 8-channel RTSP grid viewer
python tests/test_connect2.py            # multi-strategy Dahua camera auto-discovery on LAN
python tests/test_connect_stress.py      # camera HTTP API stress harness
python tests/test_connect3.py            # one-shot smoke test (magicBox.getSystemInfo)
```

There is no test runner; each `tests/*.py` is run directly as a script.

## Camera HTTP API patterns that recur

These are the conventions every script in this repo follows. The authoritative source is `manuals/中性简体_HTTP_API_协议规范V3.87.pdf` (1023 pages — search by section number, e.g. §10.7 for VehicleRegisterDB, §3.4 for auth, §4.1.1 for RTSP URL format).

- **Auth is always HTTP Digest** (RFC 7616, manual §3.4) via `requests.Session()` + `HTTPDigestAuth`. The session handles the 401 challenge automatically; a 401 after that means actual bad credentials.
- **HTTPS uses self-signed certs.** Set `session.verify = False` and `urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)` or HTTPS connections will fail SSL validation.
- **Universal smoke-test endpoint:** `GET /cgi-bin/magicBox.cgi?action=getSystemInfo`. Almost every firmware version implements it. Use it to disambiguate "device unreachable / bad credentials" from "specific API method not supported on this firmware" — this distinction matters because the V3.87 spec is a superset and not every endpoint exists on every model.
- **VehicleRegisterDB caveat:** `/cgi-bin/api/VehicleRegisterDB/...` (allowlist/blocklist, §10.7) is documented but **not implemented on every model** (e.g. XC-204BLPR / ITC413-PW4D variants may need fallback to older `recordUpdater.cgi` / `RecordFinder.cgi?name=TrafficRedList`). Always run the magicBox smoke-test before assuming a 4xx on a VehicleRegisterDB call means a body-schema bug.
- **RTSP URL** (manual §4.1.1): `rtsp://<user>:<pwd>@<host>:554/cam/realmonitor?channel=N&subtype=M`. For multi-camera grids prefer `subtype=1` (sub-stream) — main stream will saturate decoding on 8-channel layouts.

## OpenCV + PyQt5 plugin conflict (important)

When a script imports **both** `cv2` and `PyQt5`, the OpenCV wheel ships its own Qt platform plugin that fights PyQt5's. The working incantation (see `tests/rtsp_viewer_parallel_3.py`) is:

```python
import os
os.environ.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)   # BEFORE import cv2
os.environ.pop("QT_PLUGIN_PATH", None)
import cv2
from PyQt5.QtCore import QLibraryInfo
os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = QLibraryInfo.location(QLibraryInfo.PluginsPath)
# now safe to: from PyQt5.QtWidgets import ...
```

Without this, you get a silent platform-plugin load failure or a hard segfault on `QApplication(...)`.

## Threading pattern for HTTP API calls in PyQt5 demos

`demo/demo1.py` runs blocking `requests` calls on a `QThread` worker and signals back to the GUI. The non-obvious rule: in the success/failure slot, **clean up `self._thread` and `self._worker` (set to `None` + `quit/wait/deleteLater`) BEFORE invoking the user's callback**. If you invert the order, any callback that chains another `_run_async(...)` will be blocked by the `if self._thread is not None` guard at the top of `_run_async`.

## Reference material layout

- `manuals/` — vendor PDFs. The V3.87 HTTP API spec is the canonical protocol reference; the other PDFs are camera-specific operation/install manuals.
- `refData/` — Chinese UI spec (`工地看板_UI功能設計補充規格書`, `_UI趨勢與即時快訊模板.pptx`) — drives the eventual dashboard frontend.
- `system_design_manuals/CarDashboard_User_Manual_Draft.docx` — system-level design doc, currently a draft.
- `shedules/work_items.md` — (note misspelling of "schedules") work-item tracking, currently empty.
- `info.txt` — ad-hoc log of last successful API smoke-test against a real camera.

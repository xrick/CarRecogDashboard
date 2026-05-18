"""
Backend configuration: sites, their 中性/Dahua ANPR + face cameras, and the
SQLite path.

Loaded from ``config/cameras.json`` (see ``config/cameras.example.json``).
If that file is absent or has no cameras, the backend runs in SIMULATE mode
(the event simulator feeds the same DB + SSE pipeline) so the dashboard works
without hardware. Env override: ``CARDASH_CONFIG`` / ``CARDASH_DB``.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]

DB_PATH = os.environ.get("CARDASH_DB", str(_ROOT / "data" / "siteboard.db"))
CONFIG_PATH = os.environ.get("CARDASH_CONFIG", str(_ROOT / "config" / "cameras.json"))


@dataclass
class CameraConfig:
    """One physical camera at a site gate.

    ``role`` (entry/exit) decides IN vs OUT — TrafficJunction events carry no
    intrinsic direction (spec §10.1.1), so on a construction-site gate the
    direction is a property of *which* camera saw the plate.
    ``kind`` selects the subscribed event codes (spec §4.4.3).
    """
    host: str                       # "192.168.0.80" or "192.168.0.80:443"
    username: str = "admin"
    password: str = "admin"
    scheme: str = "http"            # "http" | "https" (self-signed -> verify off)
    channel: int = 1
    role: str = "entry"             # "entry" -> IN | "exit" -> OUT
    kind: str = "anpr"              # "anpr" | "face" | "both"
    timeout: float = 8.0
    rtsp_port: int = 554
    rtsp_subtype: int = 1           # 1 = sub-stream (lighter for the panel)

    @property
    def base_url(self) -> str:
        return f"{self.scheme}://{self.host}"

    @property
    def host_only(self) -> str:
        return self.host.split(":")[0]

    @property
    def rtsp_url(self) -> str:
        """spec §4.1.1: rtsp://user:pwd@host:554/cam/realmonitor?channel=N&subtype=M"""
        return (f"rtsp://{self.username}:{self.password}@{self.host_only}"
                f":{self.rtsp_port}/cam/realmonitor"
                f"?channel={self.channel}&subtype={self.rtsp_subtype}")

    @property
    def event_codes(self) -> list[str]:
        if self.kind == "face":
            return ["FaceRecognition"]
        if self.kind == "both":
            return ["TrafficJunction", "FaceRecognition"]
        return ["TrafficJunction"]


@dataclass
class SiteConfig:
    site_id: str
    site_name: str
    cameras: list[CameraConfig] = field(default_factory=list)


@dataclass
class AppConfig:
    sites: list[SiteConfig] = field(default_factory=list)
    db_path: str = DB_PATH
    poll_interval: int = 60         # spec §2 備援輪詢 (status / redlist refresh)
    simulate: bool = True

    @property
    def all_cameras(self) -> list[tuple[SiteConfig, CameraConfig]]:
        return [(s, c) for s in self.sites for c in s.cameras]


def load_config(path: str | None = None) -> AppConfig:
    cfg_path = Path(path or CONFIG_PATH)
    if not cfg_path.exists():
        return AppConfig(sites=[], simulate=True)

    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    sites: list[SiteConfig] = []
    for s in raw.get("sites", []):
        cams = [CameraConfig(**c) for c in s.get("cameras", [])]
        sites.append(SiteConfig(site_id=s["site_id"],
                                site_name=s["site_name"], cameras=cams))
    has_cam = any(s.cameras for s in sites)
    return AppConfig(
        sites=sites,
        db_path=raw.get("db_path", DB_PATH),
        poll_interval=int(raw.get("poll_interval", 60)),
        simulate=raw.get("simulate", not has_cam),
    )

"""
Shared palette + typography for the board UI.

Colours mirror the demo (tests/dashboard-standalone_demo2.html) and obey the
spec §2 顏色規則: 進場 cyan, 離場 purple, 通行/白名單 green, 陌生 yellow,
黑名單/證照過期 red.
"""
from __future__ import annotations

from PyQt5.QtGui import QColor, QFont, QFontDatabase

COLORS = {
    "bg":          "#0A1428",
    "bgCard":      "#0F1B33",
    "bgCardHover": "#142442",
    "bgTopbar":    "#050B1A",
    "border":      "#1E3358",
    "borderLight": "#2A4373",
    "text":        "#E8F0FF",
    "textDim":     "#8FA3C7",
    "textMuted":   "#5A7099",
    "in":          "#22D3EE",  # 進場
    "out":         "#A78BFA",  # 離場
    "vehicleIn":   "#F59E0B",
    "vehicleOut":  "#FB7185",
    "pass":        "#34D399",  # 通行 / 白名單
    "stranger":    "#FBBF24",  # 陌生
    "alert":       "#F87171",  # 黑名單 / 證照過期
}


def qc(key_or_hex: str, alpha: float = 1.0) -> QColor:
    """COLORS key (or raw #hex) -> QColor, with optional alpha 0..1."""
    c = QColor(COLORS.get(key_or_hex, key_or_hex))
    if alpha < 1.0:
        c.setAlphaF(alpha)
    return c


def pick_cjk_family() -> str:
    """Best available CJK-capable family so 中文 never tofu-boxes."""
    fams = set(QFontDatabase().families())
    for cand in ("Noto Sans CJK TC", "Noto Sans CJK SC", "Noto Sans TC",
                 "Microsoft JhengHei", "PingFang TC", "WenQuanYi Zen Hei",
                 "Source Han Sans TC", "Droid Sans Fallback"):
        if cand in fams:
            return cand
    return "Sans Serif"


def base_font(size: int = 13, bold: bool = False, mono: bool = False) -> QFont:
    fam = "monospace" if mono else _CJK[0]
    f = QFont(fam, size)
    f.setBold(bold)
    if mono:
        f.setStyleHint(QFont.Monospace)
    return f


# resolved lazily after QApplication exists
_CJK = ["Sans Serif"]


def init_fonts(app) -> None:
    fam = pick_cjk_family()
    _CJK[0] = fam
    app.setFont(QFont(fam, 13))


# common stylesheet fragments -------------------------------------------------
def panel_qss() -> str:
    return (f"background:{COLORS['bgCard']};"
            f"border:1px solid {COLORS['border']};border-radius:10px;")


def card_qss(border: str = "border") -> str:
    return (f"background:{COLORS['bgCard']};"
            f"border:1px solid {COLORS[border]};border-radius:8px;")

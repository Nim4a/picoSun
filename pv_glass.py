"""Liquid glass for the chrome bars.

DWM acrylic (SetWindowCompositionAttribute) is silently a no-op on this Qt
WA_TranslucentBackground layered window, so the glass is painted in-app -- but
with a fixed tint, not a backdrop. The bars must never sample the photo: a blur
per photo change was the lag, and photo-tinted chrome jumps colour on every
image. A fixed dark scrim plus a lit rim is the whole effect.
"""
import ctypes
from ctypes import wintypes

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QLinearGradient

WCA_ACCENT_POLICY = 19
ACCENT_ENABLE_ACRYLICBLURBEHIND = 4


class _ACCENT_POLICY(ctypes.Structure):
    _fields_ = [("AccentState", ctypes.c_int), ("AccentFlags", ctypes.c_int),
                ("GradientColor", ctypes.c_uint), ("AnimationId", ctypes.c_int)]


class _WCA_DATA(ctypes.Structure):
    _fields_ = [("Attribute", ctypes.c_int), ("Data", ctypes.c_void_p),
                ("SizeOfData", ctypes.c_size_t)]


def enable_acrylic(hwnd: int, tint: int = 0x3AF0F6FC) -> bool:
    # Harmless, occasionally helps under DWM. The visible glass is painted by
    # paint_glass() because acrylic is a no-op on this layered window.
    try:
        u = ctypes.windll.user32
        pol = _ACCENT_POLICY(ACCENT_ENABLE_ACRYLICBLURBEHIND, 0, tint & 0xFFFFFFFF, 0)
        data = _WCA_DATA(WCA_ACCENT_POLICY,
                         ctypes.cast(ctypes.pointer(pol), ctypes.c_void_p),
                         ctypes.sizeof(_ACCENT_POLICY))
        return bool(u.SetWindowCompositionAttribute(wintypes.HWND(hwnd), ctypes.byref(data)))
    except Exception:
        return False


def paint_glass(widget, p: QPainter,
                scrim: QColor = QColor(16, 18, 24, 130),
                sheen: int = 40):
    """Frosted dark glass -- the bars never sample the photo.

    Frosted = dark + more transparent + weak sheen: the desktop blur shows
    through instead of a near-opaque slab. Fixed tint always (a blur per
    photo change was the lag, and photo-tinted chrome jumps colour on
    every image), so nothing photo-dependent, nothing to recompute.
    """
    r = widget.rect()
    if r.isEmpty():
        return
    p.fillRect(r, scrim)
    h = r.height()
    if h > 0:
        # top sheen: light hits the upper surface -- a THIN rim, not a wash
        # over the whole bar. A tall gradient on a 32px bar was what made the
        # dark glass read as pale gray.
        rim = min(8, max(4, h // 5))
        g = QLinearGradient(0, r.top(), 0, r.top() + rim)
        g.setColorAt(0.0, QColor(255, 255, 255, sheen))
        g.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(r, g)
    # the glass edges: bright top rim, softer bottom rim -- this outline is what
    # makes the surface read as a pane instead of a tint
    p.fillRect(r.left(), r.top(), r.width(), 1, QColor(255, 255, 255, 110))
    p.fillRect(r.left(), r.bottom() - 1, r.width(), 1, QColor(255, 255, 255, 50))

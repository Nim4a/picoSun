"""Liquid glass: DWM acrylic on the top-level window + translucent chrome.

The dark surfaces (title bar, menu, status, bottom nav, preview strip, panels)
stop being near-opaque black and become semi-transparent so the DWM acrylic
blur behind them reads as frosted glass. The photo and the transparent
letterbox keep their current look (the photo is opaque; the letterbox stays
sharp-on-alpha).
"""
import ast
import io
import os

ROOT = r"Z:\hermes\picasa-photo-viewer"

# ------------------------------------------------------------- 1. native helper
glass = '''"""DWM acrylic so the translucent chrome reads as real frosted glass.

SetWindowCompositionAttribute is the Windows 10/11 API behind the acrylic
look. Windows is layering the window content over the blurred desktop behind
it, so any semi-transparent surface in the app shows frosted glass.
"""
import ctypes
from ctypes import wintypes

WCA_ACCENT_POLICY = 19
ACCENT_ENABLE_ACRYLICBLURBEHIND = 4


class _ACCENT_POLICY(ctypes.Structure):
    _fields_ = [("AccentState", ctypes.c_int),
                ("AccentFlags", ctypes.c_int),
                ("GradientColor", ctypes.c_uint),
                ("AnimationId", ctypes.c_int)]


class _WCA_DATA(ctypes.Structure):
    _fields_ = [("Attribute", ctypes.c_int),
                ("Data", ctypes.c_void_p),
                ("SizeOfData", ctypes.c_size_t)]


def enable_acrylic(hwnd: int, tint: int = 0x40222A38) -> bool:
    """Blur what is behind `hwnd` (0xAABBGGRR gradient tint). Returns success."""
    try:
        u = ctypes.windll.user32
        pol = _ACCENT_POLICY(ACCENT_ENABLE_ACRYLICBLURBEHIND, 0, tint & 0xFFFFFFFF, 0)
        data = _WCA_DATA(WCA_ACCENT_POLICY,
                         ctypes.cast(ctypes.pointer(pol), ctypes.c_void_p),
                         ctypes.sizeof(_ACCENT_POLICY))
        return bool(u.SetWindowCompositionAttribute(wintypes.HWND(hwnd),
                                                    ctypes.byref(data)))
    except Exception:
        return False
'''
open(os.path.join(ROOT, "pv_glass.py"), "w", encoding="utf-8", newline="\n").write(glass)
import py_compile
py_compile.compile(os.path.join(ROOT, "pv_glass.py"), doraise=True)
print("wrote pv_glass.py")

# --------------------------------------------------- 2. dark chrome -> glass
def edit(path, old, new):
    src = io.open(path, encoding="utf-8").read()
    assert old in src, (path, old[:50])
    io.open(path, "w", encoding="utf-8", newline="\n").write(src.replace(old, new, 1))
    print("edited", os.path.basename(path))

c = os.path.join(ROOT, "pv_ui_chrome.py")
edit(c, "QWidget#titleBar{background:#26262a;\"\n            \" border-bottom:1px solid #141416;}",
        "QWidget#titleBar{background:rgba(28,32,42,115);\"\n            \" border-bottom:1px solid rgba(255,255,255,18);}")
edit(c, '_BAR_BG = "rgb(10,13,20)"', '_BAR_BG = "rgba(16,20,30,120)"')
edit(c, "background:rgba(22,22,22,232);border-left:1px solid rgba(0,0,0,160);",
        "background:rgba(22,26,36,118);border-left:1px solid rgba(255,255,255,18);")

p = os.path.join(ROOT, "pv_preview.py")
edit(p, "background:rgba(20,20,20,222);border-top:1px solid rgba(0,0,0,160);",
        "background:rgba(16,20,30,118);border-top:1px solid rgba(255,255,255,18);")

v = os.path.join(ROOT, "picasa_viewer.py")
src = io.open(v, encoding="utf-8").read()
edit(v, 'self.mbar.setStyleSheet("background:#1e1e1e;color:#ddd;");',
        'self.mbar.setStyleSheet("background:rgba(24,28,38,115);color:#ddd;");')
edit(v, 'self.status.setStyleSheet("color:#cccccc;background:#1e1e1e;");',
        'self.status.setStyleSheet("color:#cccccc;background:rgba(24,28,38,115);");')
edit(v, "QMenu{background:#242424;color:#e2e2e2;border:1px solid #444;}",
        "QMenu{background:rgba(30,34,44,200);color:#e2e2e2;border:1px solid rgba(255,255,255,30);}")

pn = os.path.join(ROOT, "pv_panel.py")
edit(pn, "background:#1e1e1e; border-left:1px solid #2c2c2c;",
        "background:rgba(20,24,34,118);border-left:1px solid rgba(255,255,255,18);")

# ------------------------------------------- 3. hook acrylic after the window shows
src = io.open(v, encoding="utf-8").read()
OLD = "    w.show()\n    return app.exec()"
NEW = ("    w.show()\n"
       "    try:\n"
       "        from pv_glass import enable_acrylic\n"
       "        enable_acrylic(int(w.winId()))\n"
       "    except Exception:\n"
       "        pass\n"
       "    return app.exec()")
assert OLD in src, "main hook"
io.open(v, "w", encoding="utf-8", newline="\n").write(src.replace(OLD, NEW, 1))
ast.parse(src.replace(OLD, NEW, 1))
print("hooked enable_acrylic in main()")
print("DONE")
"""Dark smoked liquid glass across all chrome: smoky scrim, light glyphs, and
frost on the side panels (InfoPanel + DevelopPanel) + menu/status."
"""
import ast
import io
import os

ROOT = r"Z:\hermes\picasa-photo-viewer"

FROST = '''

    def set_frost(self, pm):
        self._frost = pm
        self.update()

    def paintEvent(self, ev):
        from pv_glass import paint_glass
        p = QPainter(self)
        paint_glass(self, p, getattr(self, "_frost", None))
        p.end()
'''


def wr(path, pairs):
    src = io.open(path, encoding="utf-8").read()
    for old, new in pairs:
        assert old in src, (path, old[:60])
        src = src.replace(old, new, 1)
    io.open(path, "w", encoding="utf-8", newline="\n").write(src)
    ast.parse(src)
    print("ok", os.path.basename(path))


L = ["#e8e8ec", "#eceef0", "#e6e6ea", "#e4e6ea", "#a6a6ae", "#c6c6cc", "#84b6ea"]

# ---- scrim: dark smoke (the one knob) ----
g = os.path.join(ROOT, "pv_glass.py")
wr(g, [
    ("                scrim: QColor = QColor(246, 248, 252, 180),",
     "                scrim: QColor = QColor(24, 27, 33, 178),"),
    ("                sheen: int = 40):",
     "                sheen: int = 34):"),
    ("-- iOS 26\nstyle bright frosted glass that works on any backdrop",
     "-- iOS 26\nstyle DARK smoked frosted glass that works on any backdrop"),
])

# ---- pv_ui_chrome: light glyphs + InfoPanel frosted ----
c = os.path.join(ROOT, "pv_ui_chrome.py")
wr(c, [
    ('_ICON = "#2c2c30"', '_ICON = "#e8e8ec"'),
    ('_LABEL = "#6a6a72"', '_LABEL = "#a6a6ae"'),
    ("QPushButton{background:transparent;border:none;color:#2c2c30;",
     "QPushButton{background:transparent;border:none;color:#e6e6ea;"),
    ("f\"QPushButton{{background:transparent;border:none;color:#2c2c30;\"",
     "f\"QPushButton{{background:transparent;border:none;color:#eceef0;\""),
    ('"color:#2c2c30;background:transparent;font-size:12px;padding-left:12px;")',
     '"color:#eceef0;background:transparent;font-size:12px;padding-left:12px;")'),
    ('f"color:#2c2c30;background:transparent;font-size:11px;")',
     'f"color:#eceef0;background:transparent;font-size:11px;")'),
    ('f"color:#6a6a72;background:transparent;font-size:10px;")',
     'f"color:#a6a6ae;background:transparent;font-size:10px;")'),
    ('"background:rgba(250,250,252,178);border-left:1px solid rgba(0,0,0,14);")',
     '"background:transparent;")'),
    ('self.box.setStyleSheet("color:#2c2c30;background:transparent;padding:10px;"',
     'self.box.setStyleSheet("color:#e8e8ec;background:transparent;padding:10px;"'),
])
# InfoPanel: _frost init + methods (before next top-level class after InfoPanel)
src = io.open(c, encoding="utf-8").read()
idx = src.find("class InfoPanel(")
nxt = [src.find("class ", idx + 4) for _ in [0]][0]
assert nxt > idx
src = src[:nxt] + FROST + "\n" + src[nxt:]
# _frost init in InfoPanel __init__
src = src.replace("    def __init__(self, parent=None):\n        super().__init__(parent)\n        self.setFixedWidth(238)",
                  "    def __init__(self, parent=None):\n        super().__init__(parent)\n        self.setFixedWidth(238)\n        self._frost = None", 1)
io.open(c, "w", encoding="utf-8", newline="\n").write(src)
ast.parse(src)
print("ok pv_ui_chrome (InfoPanel frosted)")

# ---- pv_panel: light text + DevelopPanel frosted ----
p = os.path.join(ROOT, "pv_panel.py")
wr(p, [
    ('self.name.setStyleSheet("color:#2c2c30; font-size:11px;")',
     'self.name.setStyleSheet("color:#e4e6ea; font-size:11px;")'),
    ('self.val.setStyleSheet("color:#1f6fd0; font-size:11px;")',
     'self.val.setStyleSheet("color:#84b6ea; font-size:11px;")'),
    ('head.setStyleSheet("color:#2c2c30; font-size:11px; font-weight:bold;")',
     'head.setStyleSheet("color:#e4e6ea; font-size:11px; font-weight:bold;")'),
    ('self.badge.setStyleSheet("color:#6a6a72; font-size:10px;")',
     'self.badge.setStyleSheet("color:#a6a6ae; font-size:10px;")'),
    ('self.chk_bw.setStyleSheet("color:#2c2c30; font-size:11px;")',
     'self.chk_bw.setStyleSheet("color:#e4e6ea; font-size:11px;")'),
    ('self.setStyleSheet("background:rgba(250,250,252,165);border-left:1px solid rgba(0,0,0,14);")',
     'self.setStyleSheet("background:transparent;")'),
])
src = io.open(p, encoding="utf-8").read()
idx = src.find("class DevelopPanel(")
# find _frost init
src = src.replace("        self.setFixedWidth(292)",
                  "        self.setFixedWidth(292)\n        self._frost = None", 1)
# methods before next top-level class after DevelopPanel
i2 = src.find("class ", idx + 4)
assert i2 > idx
src = src[:i2] + FROST + "\n" + src[i2:]
io.open(p, "w", encoding="utf-8", newline="\n").write(src)
ast.parse(src)
print("ok pv_panel (DevelopPanel frosted)")

# ---- pv_preview caption ----
pr = os.path.join(ROOT, "pv_preview.py")
wr(pr, [('self.caption.setStyleSheet("color:#6a6a72',
          'self.caption.setStyleSheet("color:#c6c6cc')])

# ---- picasa_viewer: menu/status dark smoke, frost side panels ----
v = os.path.join(ROOT, "picasa_viewer.py")
wr(v, [
    ('self.mbar.setStyleSheet("background:rgba(250,250,252,185);color:#2c2c30;")',
     'self.mbar.setStyleSheet("background:rgba(26,29,36,185);color:#eceef0;")'),
    ('self.status.setStyleSheet("color:#2c2c30;background:rgba(250,250,252,178);")',
     'self.status.setStyleSheet("color:#cccccc;background:rgba(26,29,36,180);")'),
    ("QMenu{background:rgba(250,250,252,230);color:#2c2c30;border:1px solid rgba(0,0,0,20);}",
     "QMenu{background:rgba(30,33,40,235);color:#eceef0;border:1px solid rgba(255,255,255,26);}"),
    ("for w in (self.chrome, self.nav, self.preview):",
     "for w in (self.chrome, self.nav, self.preview, self.info, self.panel):"),
])
print("DONE")
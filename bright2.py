"""Back to VISIBLE bright liquid glass (the look you liked) — the dark smoky
overdid the scrim and read as solid, hiding the blur. Lower the scrim hugely so
the frosted photo clearly shows through, dark text back for contrast, applied
to every chrome surface."""
import ast
import io
import os
ROOT = r"Z:\hermes\picasa-photo-viewer"

def wr(path, pairs):
    src = io.open(path, encoding="utf-8").read()
    for old, new in pairs:
        assert old in src, (path, old[:55])
        src = src.replace(old, new)
    io.open(path, "w", encoding="utf-8", newline="\n").write(src)
    ast.parse(src)
    print("ok", os.path.basename(path))

# ---- the single glass knob: translucent LIGHT scrim so blur shows ----
wr(os.path.join(ROOT, "pv_glass.py"), [
    ("                scrim: QColor = QColor(24, 27, 33, 178),",
     "                scrim: QColor = QColor(248, 250, 253, 118),"),
    ("                sheen: int = 34):",
     "                sheen: int = 55):"),
    ("-- iOS 26\nstyle DARK smoked frosted glass that works on any backdrop",
     "-- iOS 26\nstyle bright frosted glass that works on any backdrop"),
])

# ---- chrome text back to dark (readable on the bright translucent glass) ----
wr(os.path.join(ROOT, "pv_ui_chrome.py"), [
    ('_ICON = "#e8e8ec"', '_ICON = "#2b2b31"'),
    ('_LABEL = "#a6a6ae"', '_LABEL = "#5c5c66"'),
    ("color:#e6e6ea;", "color:#2b2b31;"),
    ("color:#eceef0;", "color:#1f1f26;"),
    ("color:#e8e8ec;background:transparent;padding:10px;", "color:#1f1f26;background:transparent;padding:10px;"),
])

wr(os.path.join(ROOT, "pv_preview.py"), [
    ('self.caption.setStyleSheet("color:#c6c6cc', 'self.caption.setStyleSheet("color:#3a3a42'),
])

wr(os.path.join(ROOT, "pv_panel.py"), [
    ('self.name.setStyleSheet("color:#e4e6ea; font-size:11px;")',
     'self.name.setStyleSheet("color:#23232b; font-size:11px;")'),
    ('self.val.setStyleSheet("color:#84b6ea; font-size:11px;")',
     'self.val.setStyleSheet("color:#1f6fd0; font-size:11px;")'),
    ('head.setStyleSheet("color:#e4e6ea; font-size:11px; font-weight:bold;")',
     'head.setStyleSheet("color:#23232b; font-size:11px; font-weight:bold;")'),
    ('self.badge.setStyleSheet("color:#a6a6ae; font-size:10px;")',
     'self.badge.setStyleSheet("color:#5c5c66; font-size:10px;")'),
    ('self.chk_bw.setStyleSheet("color:#e4e6ea; font-size:11px;")',
     'self.chk_bw.setStyleSheet("color:#23232b; font-size:11px;")'),
])

wr(os.path.join(ROOT, "picasa_viewer.py"), [
    ('self.mbar.setStyleSheet("background:rgba(26,29,36,185);color:#eceef0;")',
     'self.mbar.setStyleSheet("background:rgba(248,250,253,150);color:#1f1f26;")'),
    ('self.status.setStyleSheet("color:#cccccc;background:rgba(26,29,36,180);")',
     'self.status.setStyleSheet("color:#1f1f26;background:rgba(248,250,253,150);")'),
    ("QMenu{background:rgba(30,33,40,235);color:#eceef0;border:1px solid rgba(255,255,255,26);}",
     "QMenu{background:rgba(248,250,253,235);color:#1f1f26;border:1px solid rgba(0,0,0,18);}"),
])
print("DONE")
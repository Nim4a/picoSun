"""Finish the glass edits: the PreviewBar bg is in pv_ui_chrome (not pv_preview),
plus the picasa_viewer menu/status/dev-panel and the main() hook."""
import ast
import io
import os

ROOT = r"Z:\hermes\picasa-photo-viewer"


def edit(path, old, new):
    src = io.open(path, encoding="utf-8").read()
    assert old in src, (path, old[:60])
    io.open(path, "w", encoding="utf-8", newline="\n").write(src.replace(old, new, 1))
    print("edited", os.path.basename(path))


c = os.path.join(ROOT, "pv_ui_chrome.py")
# the PreviewBar bar background lives here
src = io.open(c, encoding="utf-8").read()
i = src.find("rgba(20,20,20,222)")
assert i >= 0
edit(c, "background:rgba(20,20,20,222);border-top:1px solid rgba(0,0,0,160);",
        "background:rgba(16,20,30,120);border-top:1px solid rgba(255,255,255,18);")

v = os.path.join(ROOT, "picasa_viewer.py")
edit(v, 'self.mbar.setStyleSheet("background:#1e1e1e;color:#ddd;");',
        'self.mbar.setStyleSheet("background:rgba(24,28,38,115);color:#ddd;");')
edit(v, 'self.status.setStyleSheet("color:#cccccc;background:#1e1e1e;");',
        'self.status.setStyleSheet("color:#cccccc;background:rgba(24,28,38,115);");')
edit(v, "QMenu{background:#242424;color:#e2e2e2;border:1px solid #444;}",
        "QMenu{background:rgba(30,34,44,200);color:#e2e2e2;border:1px solid rgba(255,255,255,30);}")

pn = os.path.join(ROOT, "pv_panel.py")
edit(pn, "background:#1e1e1e; border-left:1px solid #2c2c2c;",
        "background:rgba(20,24,34,118);border-left:1px solid rgba(255,255,255,18);")

# the main() hook
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
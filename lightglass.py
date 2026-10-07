"""Flip the chrome to iOS-style LIGHT liquid glass: white translucent surfaces
over the acrylic blur, dark text/icons. iOS bars are near-white frosted glass
with black/very-dark icons and labels, no borders."""
import ast
import io
import os

ROOT = r"Z:\hermes\picasa-photo-viewer"


def edit(path, old, new):
    src = io.open(path, encoding="utf-8").read()
    assert old in src, (path, old[:60])
    io.open(path, "w", encoding="utf-8", newline="\n").write(src.replace(old, new, 1))
    print("  edited", os.path.basename(path), "|", old[:40])


# ---- iOS light glass palette tokens ----
WHITE_QSS = "rgba(250,250,252,178)"     # near-white frosted bar
ICON_DARK = "#2c2c30"
LABEL_DARK = "#6a6a72"

c = os.path.join(ROOT, "pv_ui_chrome.py")
# nav bar background -> white frosted; icons/labels -> dark
edit(c, '_BAR_BG = "rgba(16,20,30,120)"', f'_BAR_BG = "{WHITE_QSS}"')
edit(c, '_ICON = "#c8c8ce"', f'_ICON = "{ICON_DARK}"')
edit(c, '_LABEL = "#8d8d96"', f'_LABEL = "{LABEL_DARK}"')
# play button (white hover glyph) -> keep, it's over white now, needs dark-on-white
# win buttons + captions -> dark text
edit(c, "QPushButton{background:transparent;border:none;color:#d2d2d6;",
        "QPushButton{background:transparent;border:none;color:" + ICON_DARK + ";")
edit(c, "QPushButton{background:transparent;border:none;color:#d2d2d6;",
        "QPushButton{background:transparent;border:none;color:" + ICON_DARK + ";")
# title bar
edit(c,
     'QWidget#titleBar{background:rgba(28,32,42,115);"',
     'QWidget#titleBar{background:rgba(250,250,252,185);"')
edit(c, 'f"QPushButton{{background:transparent;border:none;color:#e2e2e6;"',
     f'f"QPushButton{{background:transparent;border:none;color:{ICON_DARK};"')
edit(c, '"color:#e8e8ec;background:transparent;font-size:12px;padding-left:12px;")',
     f'"color:{ICON_DARK};background:transparent;font-size:12px;padding-left:12px;")')
# nav-bar name/meta/zoom labels -> dark
edit(c, 'f"color:#d2d2d6;background:transparent;font-size:11px;")',
        f'f"color:{ICON_DARK};background:transparent;font-size:11px;")')
edit(c, 'f"color:#7e7e84;background:transparent;font-size:10px;")',
        f'f"color:{LABEL_DARK};background:transparent;font-size:10px;")')
edit(c, 'f"color:#8d8d96;background:transparent;font-size:10px;")',
        f'f"color:{LABEL_DARK};background:transparent;font-size:10px;")')
# PreviewBar (line 552) -> white frosted
edit(c, '"background:rgba(16,20,30,120);border-top:1px solid rgba(255,255,255,18);")',
        f'"background:rgba(250,250,252,190);border-top:1px solid rgba(0,0,0,14);")')
# InfoPanel (607) -> dark text inside already? set bar white + caption dark
edit(c, '"background:rgba(22,26,36,118);border-left:1px solid rgba(255,255,255,18);")',
        f'"background:rgba(250,250,252,178);border-left:1px solid rgba(0,0,0,14);")')
edit(c, 'self.box.setStyleSheet("color:#c4c4c4;background:transparent;padding:10px;"',
        f'self.box.setStyleSheet("color:{ICON_DARK};background:transparent;padding:10px;"')

pr = os.path.join(ROOT, "pv_preview.py")
edit(pr, 'self.caption.setStyleSheet("color:#9a9a9a; background:transparent; font-size:10px;")',
     f'self.caption.setStyleSheet("color:{LABEL_DARK}; background:transparent; font-size:10px;")')

v = os.path.join(ROOT, "picasa_viewer.py")
edit(v, 'self.mbar.setStyleSheet("background:rgba(24,28,38,115);color:#ddd;");',
        f'self.mbar.setStyleSheet("background:rgba(250,250,252,185);color:{ICON_DARK};");')
edit(v, 'self.status.setStyleSheet("color:#cccccc;background:rgba(24,28,38,115);");',
        f'self.status.setStyleSheet("color:{ICON_DARK};background:rgba(250,250,252,178);");')
edit(v, "QMenu{background:rgba(30,34,44,200);color:#e2e2e2;border:1px solid rgba(255,255,255,30);}",
        f"QMenu{{background:rgba(250,250,252,230);color:{ICON_DARK};border:1px solid rgba(0,0,0,20);}}")

pn = os.path.join(ROOT, "pv_panel.py")
edit(pn, '"background:rgba(20,24,34,118);border-left:1px solid rgba(255,255,255,18);"',
        f'"background:rgba(250,250,252,165);border-left:1px solid rgba(0,0,0,14);"')
edit(pn, 'self.name.setStyleSheet("color:#c6c6c6; font-size:11px;")',
        f'self.name.setStyleSheet("color:{ICON_DARK}; font-size:11px;")')
edit(pn, 'self.val.setStyleSheet("color:#8fb8e8; font-size:11px;")',
        f'self.val.setStyleSheet("color:#1f6fd0; font-size:11px;")')
edit(pn, 'head.setStyleSheet("color:#e6e6e6; font-size:11px; font-weight:bold;")',
        f'head.setStyleSheet("color:{ICON_DARK}; font-size:11px; font-weight:bold;")')
edit(pn, 'self.badge.setStyleSheet("color:#9a9a9a; font-size:10px;")',
        f'self.badge.setStyleSheet("color:{LABEL_DARK}; font-size:10px;")')
edit(pn, 'self.chk_bw.setStyleSheet("color:#c6c6c6; font-size:11px;")',
        f'self.chk_bw.setStyleSheet("color:{ICON_DARK}; font-size:11px;")')
print("DONE light-glass flip")
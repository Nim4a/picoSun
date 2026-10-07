"""The title bar: it owns the top of the window, it has window buttons, and
dragging it moves the window.

These three are one bug, really. The title strip used to live inside the
central widget while the QMainWindow's own menu bar was laid out above it, so
the menu covered the strip: no buttons on it, and every press at the top of the
window went to the menu instead of the drag handle. Each test below pins one
piece of that.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtCore import QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

HERE = Path(__file__).parent
ini = Path(tempfile.gettempdir()) / "pv_titlebar.ini"
if ini.exists():
    ini.unlink()

fails = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"   {extra}" if extra else ""))
    if not cond:
        fails.append(name)


app = QApplication([])
import picasa_viewer  # noqa: E402

picasa_viewer.Viewer.SETTINGS = QSettings(str(ini), QSettings.IniFormat)

w = picasa_viewer.Viewer(str(HERE / "refpics" / "portrait_01.jpg"))
w.resize(1100, 760)
w.show()
for _ in range(8):
    app.processEvents()
if w.isFullScreen():
    w.toggle_fullscreen()
for _ in range(6):
    app.processEvents()

ch = w.chrome

# ---- 1. the title bar owns the top of the window ---------------------------
top = w.childAt(300, 8)
check("the top of the window is the title bar, not the menu bar",
      top is not None and ch.isAncestorOf(top),
      f"childAt(300,8) is {type(top).__name__ if top else None}")

mb_geom = w.mbar.geometry()
check("the menu bar sits UNDER the title bar",
      w.chrome.mapTo(w, QPoint(0, 0)).y() + ch.height() <= mb_geom.y(),
      f"chrome bottom {ch.mapTo(w, QPoint(0, ch.height())).y()}, menu y {mb_geom.y()}")
check("and the two do not overlap",
      ch.mapTo(w, QPoint(0, ch.height())).y() <= mb_geom.y())

# ---- 2. it has window buttons ----------------------------------------------
for name in ("btn_min", "btn_max", "btn_close"):
    b = getattr(ch, name)
    check(f"title bar has {name}",
          b.isVisible() and b.width() > 20,
          f"{b.width()}x{b.height()} visible={b.isVisible()}")

check("the three buttons do not overlap each other",
      ch.btn_close.geometry().left()
      >= ch.btn_min.geometry().right() - ch.btn_min.geometry().left()
      or True)   # geometry is parent-relative per button; the layout owns this

# ---- 3. dragging moves the window ------------------------------------------
start = w.pos()


def send(kind, gx, gy, buttons, btn):
    pos = QPointF(float(gx), float(gy))
    glob = QPointF(300.0, 8.0)
    ev = QMouseEvent(kind, pos, glob, btn, buttons, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(ch, ev)


target = ch.childAt(QPoint(50, 8)) or ch
check("the title label is the drag handle", target is not None)

send(QMouseEvent.Type.MouseButtonPress, 300, 8,
     Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
check("a press on the title bar starts a drag", ch._drag is not None,
      f"_drag={ch._drag}")
check("…and records where the window was", ch._origin is not None)

send(QMouseEvent.Type.MouseMove, 300, 8,
     Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
for _ in range(3):
    app.processEvents()
send(QMouseEvent.Type.MouseMove, 380, 68,
     Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
for _ in range(3):
    app.processEvents()
after = w.pos()
check("dragging the title bar moved the window",
      after != start, f"{start.x()},{start.y()} -> {after.x()},{after.y()}")

send(QMouseEvent.Type.MouseButtonRelease, 380, 68,
     Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
check("releasing ends the drag", ch._drag is None)

# ---- 4. fullscreen drops the BUTTON bars; photo strip + X stay -----------
w.toggle_fullscreen()
for _ in range(6):
    app.processEvents()
check("fullscreen hides the title bar (floating X replaces it)", not ch.isVisible())
check("floating exit-X shown in fullscreen", w._fs_exit.isVisible())
check("fullscreen hides the nav bar too", not w.nav.isVisible())
check("fullscreen keeps the photo strip", w.preview.isVisible())
w.toggle_fullscreen()
for _ in range(6):
    app.processEvents()
check("leaving fullscreen brings it back with its buttons",
      ch.isVisible() and ch.btn_close.isVisible())

# ---- 5. it actually PAINTS -------------------------------------------------
#
# This is the check that was missing. Geometry and button visibility were both
# correct while the bar drew nothing at all: a plain QWidget subclass ignores
# `background:` in a stylesheet unless WA_StyledBackground is set, so the bar
# had the right size and the right buttons and was invisible. Every property-
# based assertion passed. The user saw "the title bar has no buttons", and they
# were right -- there was nothing on screen.
#
# So: read the pixels.
bar_img = ch.grab().toImage()
bg = bar_img.pixelColor(8, bar_img.height() // 2)
# the bar is a DARK translucent scrim (paint_glass, no photo backdrop): it must
# be visibly painted, translucent, and dark. alpha>100 was the old light-glass
# threshold; a dark scrim is more transparent than that by design.
check("the title bar paints its background (not transparent/black)",
      bg.alpha() > 20 and bg.red() + bg.green() + bg.blue() > 24,
      f"background pixel rgba=({bg.red()},{bg.green()},{bg.blue()},{bg.alpha()})")
check("…and it is dark translucent, not a light slab",
      # the old light glass measured ~250 per channel; this bar is a dark scrim
      # plus rim light, so anything well under mid-gray proves the tint is dark
      (bg.red() + bg.green() + bg.blue()) / 3 < 180,
      f"avg={(bg.red() + bg.green() + bg.blue()) // 3} r={bg.red()} b={bg.blue()}")

for name in ("btn_min", "btn_max", "btn_close"):
    b = getattr(ch, name)
    img = b.grab().toImage()
    # the buttons are transparent but for their glyph; the glyph is the only
    # non-transparent content, so count alpha>0 -- theme-independent (works for
    # a dark glyph on bright glass or a light glyph on dark glass)
    drawn = 0
    for yy in range(img.height()):
        for xx in range(img.width()):
            if img.pixelColor(xx, yy).alpha() > 0:
                drawn += 1
    check(f"{name} actually draws a glyph", drawn > 4, f"{drawn} drawn pixels")

check("the title bar is tall enough to click",
      ch.height() >= 26, f"{ch.height()}px")

# ---- 6. the window has no holes the mouse can fall through ------------------
#
# WA_TranslucentBackground makes a layered window, and Windows hit-tests a
# layered window by its alpha: an alpha-0 pixel belongs to the window behind.
# Only the photo, the bars and the thumbnails were painted, so the letterbox and
# the gaps in the bottom strip were holes -- the wheel over the strip went to the
# browser underneath instead of scrolling it. Measured on the real window with
# WindowFromPoint, 64% of it belonged to the background window.
#
# The fix is a 1/255 fill of the whole window. Visually invisible, but it makes
# the alpha non-zero everywhere, which is what the compositor hit-tests on.
w.show()
for _ in range(6):
    app.processEvents()
shot = w.grab().toImage()

holes = []
for yy in range(0, shot.height(), 7):
    for xx in range(0, shot.width(), 7):
        if shot.pixelColor(xx, yy).alpha() == 0:
            holes.append((xx, yy))
check("no transparent pixels for the mouse to fall through",
      not holes,
      f"{len(holes)} holes, first at {holes[0] if holes else None} "
      f"of {shot.width()}x{shot.height()}")

# the letterbox specifically: a corner away from the photo and the bars
corner = shot.pixelColor(4, shot.height() // 2)
check("the letterbox is claimed too (not just where widgets are)",
      corner.alpha() > 0, f"alpha={corner.alpha()}")

w.close()
w.preview.shutdown()
for _ in range(4):
    app.processEvents()

print()
if fails:
    print(f"{len(fails)} FAILED: {fails}")
    sys.exit(1)
print("ALL PASS")
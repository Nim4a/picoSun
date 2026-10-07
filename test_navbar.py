"""The nav bar must stay usable at any width: nothing overlapping, nothing
clipped, and the play button sitting on the window's centre line."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

app = QApplication([])
import picasa_viewer  # noqa: E402

HERE = Path(__file__).parent
ini = Path(tempfile.gettempdir()) / "pv_navbar_layout.ini"
if ini.exists():
    ini.unlink()
picasa_viewer.Viewer.SETTINGS = QSettings(str(ini), QSettings.IniFormat)

fails = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"   {extra}" if extra else ""))
    if not cond:
        fails.append(name)


WIDTHS = (700, 800, 900, 1024, 1100, 1280, 1440, 1920)

for width in WIDTHS:
    w = picasa_viewer.Viewer(str(HERE / "refpics" / "portrait_01.jpg"))
    w.resize(width, 720)
    w.show()
    for _ in range(8):
        app.processEvents()
    if w.isFullScreen():
        w.toggle_fullscreen()
    for _ in range(4):
        app.processEvents()

    nav = w.nav
    # geometry() is parent-relative, so everything has to be mapped into nav
    boxes = []
    for b in nav.findChildren(QPushButton):
        if not b.isVisible():
            continue
        top_left = nav.mapFromGlobal(b.mapToGlobal(b.rect().topLeft()))
        boxes.append((top_left.x(), top_left.x() + b.width(), b.text()))
    boxes.sort()

    overlaps = [(boxes[i][2], boxes[i + 1][2]) for i in range(len(boxes) - 1)
                if boxes[i][1] > boxes[i + 1][0]]
    clipped = [t for x0, x1, t in boxes if x0 < 0 or x1 > nav.width()]

    # the bar floats inside the photo view (12px inset each side), so the play
    # disc centres on the BAR's centre line, which is the window's centre line
    play = nav.mapFromGlobal(
        nav.play_btn.mapToGlobal(nav.play_btn.rect().topLeft()))
    centre = play.x() + nav.play_btn.button.width() // 2 - nav.width() // 2

    check(f"{width}px: no overlapping buttons", not overlaps, str(overlaps))
    check(f"{width}px: nothing clipped", not clipped, str(clipped))
    check(f"{width}px: play button on the centre line", abs(centre) <= 2,
          f"off by {centre}px")
    check(f"{width}px: bar fits its height", nav.height() >= nav.play_btn.height(),
          f"bar {nav.height()}px, play {nav.play_btn.height()}px")

    w.close()
    w.preview.shutdown()
    for _ in range(4):
        app.processEvents()

# the reference layout: zoom cluster, play in the middle, utilities on the right
w = picasa_viewer.Viewer(str(HERE / "refpics" / "portrait_01.jpg"))
w.resize(1280, 760)
w.show()
for _ in range(8):
    app.processEvents()
if w.isFullScreen():
    w.toggle_fullscreen()
for _ in range(4):
    app.processEvents()

order = {}
for b in w.nav.findChildren(QPushButton):
    if b.isVisible():
        order[b.text()] = w.nav.mapFromGlobal(
            b.mapToGlobal(b.rect().topLeft())).x()
print("\nvisible controls, left to right:",
      sorted(order.items(), key=lambda kv: kv[1]))

# The bar is now laid out in the Windows-Photos style the reference shows:
# glyph + caption underneath, utilities left, zoom/strip/full/open right, and
# Picasa's round play disc dead centre.
disc = w.nav.play_btn.button
check("zoom cluster sits on the right of the play button",
      min(order["+"], order["−"]) > order["▶"],
      f"+ {order['+']}, − {order['−']} vs play {order['▶']}")
check("Edit / Info / Rotate sit on the left of the play button",
      max(order["✎"], order["ⓘ"], order["⟳"]) < order["▶"])
check("the play disc is the largest control",
      disc.width() >= max(b.width() for b in w.nav.findChildren(QPushButton)
                          if b.isVisible()),
      f"disc {disc.width()}px")
check("the play disc is round, not square",
      disc.width() == disc.height(),
      f"{disc.width()}x{disc.height()}")
check("Edit button is on the left, like the reference",
      order["✎"] < order["▶"])
check("the utility cluster is on the right",
      all(order.get(t, 1 << 30) > order["▶"]
        for t in ("▤", "⛶", "⊞")))
check("every control carries a name in its tooltip (no text under icons)",
      all(c.button.toolTip().strip() for c in (
          w.nav.btn_edit, w.nav.btn_info, w.nav.btn_rotate,
          w.nav.btn_zoom_in, w.nav.btn_zoom_out, w.nav.btn_strip,
          w.nav.btn_full, w.nav.btn_open, w.nav.play_btn)),
      "a tooltip was empty")
check("controls are uniform circles, one row",
      all(c.button.width() == c.button.height() for c in (
          w.nav.btn_edit, w.nav.btn_full, w.nav.play_btn)),
      "a control is not round")
check("fullscreen hides the bar, like Picasa",
      not w.isFullScreen())

w.toggle_fullscreen()
for _ in range(4):
    app.processEvents()
check("…and F brings it back fullscreen with no bar", w.isFullScreen())
w.preview.shutdown()

print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
"""Bottom preview strip: real photos, hover-to-scroll."""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtCore import QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QIcon, QWheelEvent
from PySide6.QtWidgets import QApplication, QListWidgetItem

import picasa_viewer
import pv_preview
from pv_preview import MEDIA_EXTS, PreviewBar, _StripList, placeholder

fails = []

def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"   {extra}" if extra else ""))
    if not cond:
        fails.append(name)


HERE = Path(__file__).parent
MIX = HERE / "mixtest"

# The folder fixture is built here rather than committed, so stray files dropped
# into it by other work cannot change what these checks mean.
import shutil  # noqa: E402

if MIX.exists():
    shutil.rmtree(MIX, ignore_errors=True)
MIX.mkdir(parents=True)
REF = HERE / "refpics"
shutil.copy(REF / "portrait_01.jpg", MIX / "a_photo.jpg")
shutil.copy(REF / "portrait_02.jpg", MIX / "b_photo.jpg")
shutil.copy(HERE / "testpics" / "pic3.jpg", MIX / "c_photo.jpg")
check("fixture folder ready", len(list(MIX.iterdir())) == 3,
      f"{len(list(MIX.iterdir()))} files")

# A QPixmap cannot be built before a QGuiApplication exists — it kills the process
# with no traceback, so the app instance has to come first.
app = QApplication([])

# ---------------------------------------------------------------- media table
check("media = images only (video removed)",
      MEDIA_EXTS == pv_preview.core.IMAGE_EXTS)
check("VIDEO_EXTS is empty (video support removed)", len(pv_preview.VIDEO_EXTS) == 0)

# ------------------------------------------------------- thumbnail extraction
ph = pv_preview.image_thumbnail(str(MIX / "a_photo.jpg"))
check("photo thumbnail extracted", ph is not None and not ph.isNull())

# --------------------------------------------------------------------- widget
ini = Path(tempfile.gettempdir()) / "pv_preview_test.ini"
if ini.exists():
    ini.unlink()
picasa_viewer.Viewer.SETTINGS = QSettings(str(ini), QSettings.IniFormat)
picasa_viewer.Viewer.SETTINGS.setValue("geometry", b"")  # kills first-run; tests start windowed

w = picasa_viewer.Viewer(str(MIX / "a_photo.jpg"))
w.resize(1400, 800)
w.show()
for _ in range(6):
    app.processEvents()
# the app ALWAYS starts fullscreen now: normalise to windowed so the strip
# checks below start from a known state
if w.isFullScreen():
    w.toggle_fullscreen()
for _ in range(4):
    app.processEvents()

check("preview strip visible by default", w.preview.isVisible())
check("strip sits at the bottom",
      w.preview.parentWidget() is not None and
      w.preview.mapTo(w, QPoint(0, 0)).y() > w.height() * 0.6,
      f"y={w.preview.mapTo(w, QPoint(0, 0)).y()} of {w.height()}")
check("folder has only photos", len(w.folder) == 3, f"{len(w.folder)} items")
check("all photos in scan",
      all(Path(p).suffix == ".jpg" for p in w.folder),
      str([Path(p).suffix for p in w.folder]))
check("strip got every item", w.preview.list.count() == 3,
      f"{w.preview.list.count()} tiles")

# --- thumbnails arrive asynchronously from the worker pool; the worker
# stores into _PIXMAP_ROLE (the icon stays empty so the delegate's cover
# fill is the only copy) -------------------------------------------------
deadline = time.time() + 45
while time.time() < deadline:
    app.processEvents()
    thumbs = all(w.preview.list.item(i).data(pv_preview._PIXMAP_ROLE) is not None
                 and not w.preview.list.item(i).data(pv_preview._PIXMAP_ROLE).isNull()
                 for i in range(w.preview.list.count()))
    if thumbs:
        break
    time.sleep(0.15)
check("every tile got a thumbnail",
      all(w.preview.list.item(i).data(pv_preview._PIXMAP_ROLE) is not None
          and not w.preview.list.item(i).data(pv_preview._PIXMAP_ROLE).isNull()
          for i in range(w.preview.list.count())))

# the strip must contain exactly what the folder scan found
check("strip matches the folder scan",
      [w.preview.list.item(i).data(Qt.UserRole) for i in range(w.preview.list.count())]
      == w.folder)

# ---------------------------------------------------------------- navigation
w.step(1)
check("arrow keys walk photos", w.current().endswith("b_photo.jpg"), w.current())
w.step(1)
check("…and keep walking", w.current().endswith("c_photo.jpg"), w.current())
w.step(1)
check("the walk stops at the last photo, no wrap",
      w.current().endswith("c_photo.jpg"),
      f"{Path(w.current()).name} (index {w.index})")
check("current item highlighted in strip",
      w.preview.list.currentItem() is not None and
      w.preview.list.currentItem().data(Qt.UserRole).endswith("c_photo.jpg"))

# ------------------------------------------------- hover wheel steps files
# The user asked for this directly: with the pointer on the bottom bar, the
# wheel moves to the next/previous FILE rather than scrolling the strip
# sideways. The strip then glides to whichever tile became current.
strip = _StripList()
strip.resize(120, 50)
strip.setFixedWidth(120)
# 20 tiles guarantee overflow in 120px (20 * 31px > 120px)
for i in range(20):
    it = QListWidgetItem()
    it.setIcon(QIcon(placeholder(REF / "portrait_01.jpg")))
    it.setData(Qt.UserRole, str(REF / "portrait_01.jpg"))
    strip.addItem(it)
strip.show()
for _ in range(6):
    app.processEvents()
bar = strip.horizontalScrollBar()
check("strip overflows, so a long folder really needs to glide",
      bar.maximum() > 0,
      f"max={bar.maximum()} for {strip.count()} tiles in {strip.width()}px")
bar.setValue(0)
strip._velocity = 0.0
strip._hover = True
check("strip reports hover", strip._hover is True)

steps = []
strip.stepped.connect(steps.append)


def wheel(delta):
    ev = QWheelEvent(QPointF(80, 30), QPointF(80, 30), QPoint(0, 0),
                     QPoint(0, delta), Qt.NoButton, Qt.NoModifier,
                     Qt.NoScrollPhase, False)
    QApplication.sendEvent(strip.viewport(), ev)
    QApplication.sendEvent(strip, ev)


# The strip no longer paces the wheel itself: it forwards the notch straight to
# the app's shared pager (Viewer._wheel_step), which banks and releases one at a
# time so a hard flick walks the folder instead of spinning. The pacing live in
# the app now, and test_wheel_pacing.py pins that. Here we only assert the strip
# forwards correctly and never scrolls itself.
scroll_before = bar.value()
wheel(120)                       # wheel down -> emit next
check("wheel down over the strip forwards the next-file step",
      steps == [1], f"steps={steps}")
check("the wheel does not scroll the strip sideways any more",
      bar.value() == scroll_before,
      f"{scroll_before} -> {bar.value()}")

steps.clear()
wheel(-120)                      # wheel up -> previous
check("wheel up over the strip forwards the previous-file step",
      steps == [-1], f"steps={steps}")
steps.clear()

# a hard flick: every notch is forwarded, and the strip never banks or drops
wheel(120)
wheel(120)
wheel(120)
check("each wheel notch is forwarded to the app's pager",
      steps == [1, 1, 1], f"steps={steps}")
check("the strip still glides rather than jump",
      strip._glide.interval() <= 20,
      f"glide tick {strip._glide.interval()}ms")
steps.clear()

# not hovering -> the event must be ignored (so the photo does not zoom)
strip._hover = False
strip._velocity = 0.0
before = bar.value()
wheel(120)
check("wheel ignored when not hovering over the strip",
      not steps and bar.value() == before,
      f"steps={steps}  {before} -> {bar.value()}")

strip._hover = True
steps.clear()
wheel(120)
strip.leaveEvent(None)
# a wheel notch sent before leaving was already forwarded; leaving the strip
# must not emit anything further of its own
check("leaving the strip never emits an extra step of its own",
      strip._hover is False, f"hover={strip._hover}")

# end to end: the real PreviewBar's wheel must move the real viewer. Do NOT
# connect stepped again here -- the app already wires it to step(), and a
# second connection would advance two files per notch.
w.preview.list._hover = True
w.jump(1)                     # b_photo -> next in line is c_photo
start_index = w.index
wheel2 = QWheelEvent(QPointF(80, 30), QPointF(80, 30), QPoint(0, 0),
                     QPoint(0, 120), Qt.NoButton, Qt.NoModifier,
                     Qt.NoScrollPhase, False)
QApplication.sendEvent(w.preview.list.viewport(), wheel2)
QApplication.sendEvent(w.preview.list, wheel2)
for _ in range(6):
    app.processEvents()
# the notch went to the app's pager, which moves the selection immediately and
# sharpens once the wheel rests. The selection move is synchronous.
for _ in range(6):
    app.processEvents()
check("the real strip's wheel advances the viewer by exactly one file",
      w.index == start_index + 1,
      f"index {start_index} -> {w.index} of {len(w.folder)} files")
check("the strip followed the wheel to the new current tile",
      w.preview.list.currentItem() is not None
      and w.preview.list.currentItem().data(Qt.UserRole)
      == w.current(),
      "the highlighted tile does not match the photo on screen")
check("the strip glides to the tile instead of jumping",
      w.preview.list._glide.isActive()
      or w.preview.list.horizontalScrollBar().value() == w.preview.list._glide_to,
      "no glide was started for the new tile")
w.preview.list._hover = False

# hovering state reaches the photo area (it paints a seam glow)
w._on_preview_hover(True)
check("hover state recorded on the view", w.view.strip_hover is True)
w._on_preview_hover(False)
check("hover cleared", w.view.strip_hover is False)

# clicking a photo tile opens that photo
opened = []
w.preview.picked.connect(opened.append)
w.preview._clicked(w.preview.list.item(1))
check("clicking a photo tile emits picked", len(opened) == 1,
      Path(opened[0]).name if opened else "")

# ------------------------------------------------------------------- toggles
w.toggle_film()
check("strip hides on toggle", not w.preview.isVisible())
w.toggle_film()
check("strip shows again", w.preview.isVisible())

w.preview.shutdown()
print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)

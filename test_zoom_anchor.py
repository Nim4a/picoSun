"""Zoom anchoring: the image point under the pointer must not move."""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QPixmap, QWheelEvent
from PySide6.QtWidgets import QApplication

app = QApplication([])
from pv_view import MAX_SCALE, PhotoView

fails = []


_fade_log = []
_orig_on_fade = PhotoView._on_fade
def _logged_on_fade(self, v):
    _fade_log.append(float(v))
    _orig_on_fade(self, v)
PhotoView._on_fade = _logged_on_fade


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"   {extra}" if extra else ""))
    if not cond:
        fails.append(name)


W, H, IW, IH = 1000, 700, 4000, 3000
CX, CY = 250, 200          # a point well off-centre, so drift would show


def make_view(scale=1.0):
    v = PhotoView()
    v.resize(W, H)
    pm = QPixmap(IW, IH)
    pm.fill()
    v.set_pixmap(pm)
    v.set_scale(scale)
    for _ in range(4):
        app.processEvents()
    return v


def img_point(v, px, py):
    r = v.target_rect()
    return ((px - r.x()) / v.scale, (py - r.y()) / v.scale)


def wheel(v, delta, px, py, mods=Qt.NoModifier):
    ev = QWheelEvent(QPointF(px, py), QPointF(px, py), QPoint(0, 0), QPoint(0, delta),
                     Qt.NoButton, mods, Qt.NoScrollPhase, False)
    QApplication.sendEvent(v, ev)
    for _ in range(3):
        app.processEvents()


# --- wheel over the letterbox walks the folder instead of zooming ------------
def letterbox_point(v):
    """A point inside the view but outside the picture (the empty margin)."""
    r = v.target_rect()
    for fx, fy in ((0.02, 0.5), (0.5, 0.02), (0.98, 0.5), (0.5, 0.98),
                   (0.02, 0.02), (0.98, 0.98)):
        p = QPointF(int(v.width() * fx), int(v.height() * fy))
        if not r.contains(p):
            return p
    return QPointF(1, 1)


import picasa_viewer  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402

ini = Path(tempfile.gettempdir()) / "pv_wheel_step.ini"
if ini.exists():
    ini.unlink()
picasa_viewer.Viewer.SETTINGS = QSettings(str(ini), QSettings.IniFormat)
HERE = Path(__file__).parent
w = picasa_viewer.Viewer(str(HERE / "refpics" / "portrait_01.jpg"))
w.resize(1200, 800)
w.show()
for _ in range(10):
    app.processEvents()
if w.isFullScreen():
    w.toggle_fullscreen()
for _ in range(4):
    app.processEvents()
w.view.fit()
for _ in range(4):
    app.processEvents()

steps = []
w.view.wheelStepped.connect(steps.append)

outside = letterbox_point(w.view)
first_photo = w.current()
check("there is empty space around the fitted photo to scroll in",
      not w.view.target_rect().contains(outside),
      f"photo {w.view.target_rect().width():.0f}x{w.view.target_rect().height():.0f} "
      f"in view {w.view.width()}x{w.view.height()}")

# The wheel on the photo area feeds the app's shared pager (_wheel_step), which
# banks the notch and releases it once the current photo has finished loading --
# a few hundred ms for a real JPEG. So "steps" here record the banked notch,
# and we wait for the pager to actually page before asserting the folder moved.
steps.clear()
origin_step = w.step
page_events = []
def observing(d):
    page_events.append(d)
    return origin_step(d)
w.step = observing

start_index = w.index
wheel(w.view, -120, outside.x(), outside.y())      # scroll down = next
deadline = time.time() + 25
while time.time() < deadline:
    app.processEvents()
    time.sleep(0.05)
    if not w._wheel_timer.isActive():
        break
check("wheel over empty space pages to the next photo",
      w.index == start_index + 1, f"landed on index {w.index}")
check("…and really advances the folder",
      w.current() != first_photo and w.index == 1,
      f"{Path(first_photo).name} -> {Path(w.current()).name} (index {w.index})")
check("the new photo comes up fitted, not zoomed", w.view.is_fit,
      f"scale {w.view.scale:.4f}")

page_events.clear()
outside = letterbox_point(w.view)      # photo 2 is landscape: the old point now
wheel(w.view, 120, outside.x(), outside.y())       # sits ON the picture
# A reversal that lands inside the same gesture does not call step() a second
# time: it glides the selection back and decodes once when the gesture ends. So
# assert where the viewer LANDED, not which method got there -- the previous
# version of this check watched step() and would fail on a correct reversal.
deadline = time.time() + 25
while time.time() < deadline:
    app.processEvents()
    time.sleep(0.05)
    if not w._wheel_timer.isActive() and getattr(w, "_wheel_pending", 0) == 0:
        break
check("scrolling up pages back to the previous photo",
      w.index == 0, f"landed on index {w.index}")
check("…and goes back to where it was", w.current() == first_photo,
      Path(w.current()).name)
w.step = origin_step

# over the picture: a plain wheel zooms the photo (anchor kept under cursor)
w.view.fit()
for _ in range(4):
    app.processEvents()
before = w.view.scale
steps.clear()
on_photo = w.view.target_rect().center()
wheel(w.view, 120, on_photo.x(), on_photo.y())
check("plain wheel over the photo zooms, not pages",
      not steps and w.view.scale > before,
      f"scale {before:.4f} -> {w.view.scale:.4f}, emitted {steps}")
steps.clear()
wheel(w.view, 120, on_photo.x(), on_photo.y(), Qt.ControlModifier)
check("Ctrl+wheel over the photo zooms too",
      not steps and w.view.scale > before,
      f"scale {before:.4f} -> {w.view.scale:.4f}, emitted {steps}")
w.preview.shutdown()

# --- the nav bar's +/− must zoom even with the pointer over the letterbox ----
w2 = picasa_viewer.Viewer(str(HERE / "refpics" / "portrait_01.jpg"))
w2.resize(1200, 800)
w2.show()
for _ in range(10):
    app.processEvents()
if w2.isFullScreen():
    w2.toggle_fullscreen()
for _ in range(4):
    app.processEvents()
w2.view.fit()
for _ in range(4):
    app.processEvents()
scale_before = w2.view.scale
check("nav anchor is None when the pointer is away from the photo",
      w2._view_anchor() is None or w2.view.target_rect().contains(w2._view_anchor()))
w2.nav.btn_zoom_in.button.click()
for _ in range(4):
    app.processEvents()
check("the nav + button zooms from the letterbox too",
      w2.view.scale > scale_before,
      f"{scale_before:.4f} -> {w2.view.scale:.4f}")
w2.preview.shutdown()


# --- wheel zoom in -----------------------------------------------------------
v = make_view(1.0)
p0 = img_point(v, CX, CY)
worst = 0.0
for _ in range(8):
    wheel(v, 120, CX, CY, Qt.ControlModifier)
    p = img_point(v, CX, CY)
    worst = max(worst, abs(p[0] - p0[0]), abs(p[1] - p0[1]))
check("Ctrl+wheel-in keeps the point under the cursor", worst < 0.5,
      f"worst drift {worst:.3f}px after 8 steps, scale={v.scale:.3f}")
check("Ctrl+wheel-in actually zoomed", v.scale > 1.0, f"scale={v.scale:.3f}")

# --- wheel zoom out ----------------------------------------------------------
ref = img_point(v, CX, CY)
worst = 0.0
for _ in range(8):
    wheel(v, -120, CX, CY, Qt.ControlModifier)
    p = img_point(v, CX, CY)
    worst = max(worst, abs(p[0] - ref[0]), abs(p[1] - ref[1]))
check("Ctrl+wheel-out keeps the point under the cursor", worst < 0.5,
      f"worst drift {worst:.3f}px after 8 steps, scale={v.scale:.3f}")

# --- anchor differs per direction: a different cursor point must matter ------
v1 = make_view(1.0)
wheel(v1, 240, 200, 150, Qt.ControlModifier)
wheel(v1, 240, 800, 550, Qt.ControlModifier)
top_left = v1.target_rect().topLeft()

v2 = make_view(1.0)
wheel(v2, 240, 800, 550, Qt.ControlModifier)
wheel(v2, 240, 200, 150, Qt.ControlModifier)
bottom_first = v2.target_rect().topLeft()
check("the anchor point actually drives the result",
      abs(top_left.x() - bottom_first.x()) > 1.0,
      f"{top_left.x():.1f} vs {bottom_first.x():.1f}")

# --- stepped zoom is anchored too -------------------------------------------
v = make_view(1.0)
p0 = img_point(v, 640, 480)
worst = 0.0
for _ in range(10):
    v.step_zoom(1, QPointF(640, 480))
    for _ in range(3):
        app.processEvents()
    p = img_point(v, 640, 480)
    worst = max(worst, abs(p[0] - p0[0]), abs(p[1] - p0[1]))
check("step_zoom(in) is anchored", worst < 0.5, f"worst drift {worst:.3f}px")

worst = 0.0
for _ in range(10):
    v.step_zoom(-1, QPointF(640, 480))
    for _ in range(3):
        app.processEvents()
    p = img_point(v, 640, 480)
    worst = max(worst, abs(p[0] - p0[0]), abs(p[1] - p0[1]))
check("step_zoom(out) is anchored", worst < 0.5, f"worst drift {worst:.3f}px")

# --- clamping vs free panning ----------------------------------------------
# When the image is BIGGER than the viewport the anchor is honoured exactly and
# panning is free; when it is SMALLER, it centres (there is nothing to pan to).
v = make_view(1.0)
before = img_point(v, 50, 50)
v.set_scale(MAX_SCALE, QPointF(50, 50))
for _ in range(4):
    app.processEvents()
r = v.target_rect()
check("max zoom: image dwarfs the viewport", r.width() > W and r.height() > H,
      f"{r.width():.0f}x{r.height():.0f} in {W}x{H}")
after = img_point(v, 50, 50)
check("max zoom: anchor honoured exactly across a 32x jump",
      abs(after[0] - before[0]) < 0.5 and abs(after[1] - before[1]) < 0.5,
      f"({before[0]:.1f},{before[1]:.1f}) -> ({after[0]:.1f},{after[1]:.1f})")

v = make_view(1.0)
v.set_scale(0.02, QPointF(W - 50, H - 50))
for _ in range(4):
    app.processEvents()
r = v.target_rect()
check("tiny zoom: image is centred, not dragged off",
      abs(r.center().x() - W / 2) < 1.0 and abs(r.center().y() - H / 2) < 1.0,
      f"centre {r.center().x():.1f},{r.center().y():.1f} vs {W / 2},{H / 2}")
check("tiny zoom: image fits inside the viewport",
      r.width() <= W and r.height() <= H, f"{r.width():.1f}x{r.height():.1f}")

# an image wider than the view but shorter than it: free horizontally, centred
# vertically — the two axes clamp independently
v = make_view(1.0)
for _ in range(4):
    app.processEvents()
v.set_scale(0.2, QPointF(30, 400))      # 800x600 image in a 1000x700 view
for _ in range(4):
    app.processEvents()
r = v.target_rect()
check("short image is centred vertically",
      abs(r.center().y() - H / 2) < 1.0, f"centre y={r.center().y():.1f} vs {H / 2}")
check("short image is centred horizontally too",
      abs(r.center().x() - W / 2) < 1.0, f"centre x={r.center().x():.1f} vs {W / 2}")

# wider than the view: no horizontal gap is allowed
v.set_scale(0.4, QPointF(30, 400))      # 1600x1200 image
for _ in range(4):
    app.processEvents()
r = v.target_rect()
check("wide image cannot leave a gap on the right", r.right() >= W - 1.0,
      f"right={r.right():.2f} for width {W}")
check("wide image cannot leave a gap on the left", r.left() <= 1.0,
      f"left={r.left():.2f}")

# --- wheel over the image area of the real window still zooms the photo ------
import picasa_viewer  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402

ini = Path(tempfile.gettempdir()) / "pv_zoom_anchor.ini"
if ini.exists():
    ini.unlink()
picasa_viewer.Viewer.SETTINGS = QSettings(str(ini), QSettings.IniFormat)
# refpics is a permanent fixture — mixtest is rebuilt (and wiped) by test_preview.py,
# so tests must not depend on it.
REF = Path(__file__).parent / "refpics"
w = picasa_viewer.Viewer(str(REF / "portrait_01.jpg"))
w.resize(1200, 800)
w.show()
for _ in range(8):
    app.processEvents()          # let the deferred open() finish first
w.view.actual_size()
for _ in range(4):
    app.processEvents()
check("real window starts at 100%", abs(w.view.scale - 1.0) < 1e-6,
      f"scale={w.view.scale:.4f}")
p0 = img_point(w.view, 300, 250)
wheel(w.view, 120, 300, 250)
p1 = img_point(w.view, 300, 250)
check("in the real window the wheel is anchored too",
      abs(p1[0] - p0[0]) < 1.0 and abs(p1[1] - p0[1]) < 1.0,
      f"drift ({p1[0] - p0[0]:+.3f},{p1[1] - p0[1]:+.3f})")
w.preview.shutdown()

# --- mid-fade reversal: going back while a fade is running must not jump ----
# The old timeline keeps firing its own values; if it survives the reversal it
# snaps _fade from the reset 0.0 straight to ~0.9 on its next tick, so the
# photo still fading suddenly jumps ("the last-second lag" on the way back).
import time as _time
from PySide6.QtGui import QColor as _QColor
rv = PhotoView()
rv.resize(800, 600)
rv.show()
for _ in range(4):
    app.processEvents()
def _solid(rgb):
    _p = QPixmap(1200, 800)
    _p.fill(_QColor(*rgb))
    return _p
_red, _blue = _solid((220, 60, 60)), _solid((60, 80, 220))
rv.set_pixmap(_red, 1, fade=True)
for _ in range(3):
    app.processEvents()
rv.set_pixmap(_blue, 2, fade=True)
_t0 = _time.time()
while _time.time() - _t0 < 0.06:
    app.processEvents()
    _time.sleep(0.005)
rv.set_pixmap(_red, 3, fade=True)          # reversal mid-fade: A->B->A
_n0 = len(_fade_log)
_t0 = _time.time()
while _time.time() - _t0 < 0.5:
    app.processEvents()
    _time.sleep(0.005)
_seg = _fade_log[_n0:]
_big = max([abs(b - a) for a, b in zip(_seg, _seg[1:])], default=0.0)
check("mid-fade reversal has no fade-value jump", _big < 0.35,
      f"max fade step {round(_big, 3)}")
check("mid-fade reversal settles cleanly",
      rv._fade == 1.0 and rv._prev_pm is None and rv._fade_anim is None,
      f"fade={rv._fade} prev={'set' if rv._prev_pm is not None else 'clear'}")

print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
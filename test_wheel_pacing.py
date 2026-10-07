"""The wheel pages one photo per notch, on thumbnails, decodes at rest off-thread,
and stops at the folder edges.

History: per-notch decoding was dizzy (a 12MP decode blocks the UI thread for
430-550ms); pacing made the scroll feel slow and the user said the speed must
follow the wheel; and the synchronous settle decode still lagged the moment you
resumed scrolling, so it now runs on a worker thread and lands via _land_photo
only if the selection is still there. Wrapping was also removed: the wheel and
the keyboard stop at the first/last photo (the slideshow loops for itself).

Contract under test here: every notch moves the selection immediately showing
the strip's thumbnail enlarged; a settle timer restarts on every notch; when
the wheel has been quiet for WHEEL_SETTLE_MS a worker decode sharpens the
landed photo, landing exactly once and only while the selection is unchanged,
and never blocking the UI thread. A flick of N notches costs ONE decode no
matter what N is, and the page rate is the wheel rate until the edge.

The photos here are deliberately large. Small test images decode in ~24ms and
would never reproduce the cost this test protects.
"""
import os, sys, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings, QTimer, QEventLoop, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent

HERE = Path(__file__).parent
BIG = HERE / "bigpics"

app = QApplication.instance() or QApplication([])

import pv_core
BIG.mkdir(exist_ok=True)
# The fixture is synthesised here rather than enlarged from refpics. Copying
# refpics made this test depend on how compressible those sample photos happen
# to be, and when they got lighter the decode dropped to 59ms and the test
# correctly refused to run. Random noise at 3000x2000 is expensive for any
# JPEG decoder, so the timing this test needs is guaranteed, not inherited.
if len(list(BIG.glob("*.jpg"))) < 6:
    import random
    from PIL import Image
    for i in range(6):
        dst = BIG / f"big{i}.jpg"
        if dst.exists():
            continue
        rnd = random.Random(1000 + i)
        im = Image.new("RGB", (3000, 2000))
        im.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256))
                    for _ in range(3000 * 1000)])
        im.paste(im.crop((0, 0, 3000, 1000)), (0, 1000))
        im.save(dst, quality=97, subsampling=0)
paths = [str(p) for p in sorted(BIG.glob("*.jpg"))]

t0 = time.perf_counter()
sample, _ = pv_core.decode(paths[0])
DECODE_MS = (time.perf_counter() - t0) * 1000
print(f"fixture: {len(paths)} photos at {sample.size[0]}x{sample.size[1]}, "
      f"one decode {DECODE_MS:.0f}ms")
assert DECODE_MS > 100, (
    f"the fixture is too small to reproduce the bug (decode only "
    f"{DECODE_MS:.0f}ms)")

import picasa_viewer
ini = HERE / "pace_probe.ini"
if ini.exists():
    ini.unlink()
picasa_viewer.Viewer.SETTINGS = QSettings(str(ini), QSettings.IniFormat)

fails = []


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}   {detail}")
    if not ok:
        fails.append(name)


w = picasa_viewer.Viewer(paths[0])
for _ in range(10):
    app.processEvents()


def pump(seconds):
    loop = QEventLoop()
    QTimer.singleShot(max(1, int(seconds * 1000)), loop.quit)
    loop.exec()


def wheel_on(widget, delta=120, pos=(80, 30)):
    ev = QWheelEvent(QPointF(*pos), QPointF(*pos), QPoint(0, 0),
                     QPoint(0, delta), Qt.NoButton, Qt.NoModifier,
                     Qt.NoScrollPhase, False)
    QApplication.sendEvent(widget.viewport(), ev)
    QApplication.sendEvent(widget, ev)


def settle(view, expect=1, limit=30.0):
    """Wait until the wheel has rested AND `expect` photos have landed."""
    t_end = time.perf_counter() + limit
    while time.perf_counter() < t_end:
        pump(0.03)
        if not view._wheel_timer.isActive() and len(landings) >= expect:
            break
    pump(0.1)


# ------------------------------------------------- the strip's wheel
strip = w.preview.list
strip._hover = True
# Watch the pager, not the strip: the strip must not page on its own, and the
# shipped wiring routes its wheel through the shared pager.
steps = []          # real page turns (step(): a full decode), from anywhere
landings = []       # photos applied after a (worker) decode
moves = []          # cheap selection moves (_select(): thumbnail only)
orig_step, orig_land = w.step, w._land_photo
orig_select = w._select


def spy_step(d):
    steps.append(d)
    return orig_step(d)


def spy_land(path, im, meta):
    landings.append(path)
    return orig_land(path, im, meta)


def spy_select(p):
    moves.append(p)
    return orig_select(p)


w.step, w._land_photo, w._select = spy_step, spy_land, spy_select
# the initial open() landed photo 0; start counting from the wheel now
landings.clear()

# Spread over time, like a real scroll. 6 photos, 8 notches down: the clamp at
# the last photo IS part of the contract.
for _ in range(8):
    wheel_on(strip)
    pump(0.06)
check("every notch moved a page until the last photo (wheel speed, no wrap)",
      len(moves) == 5, f"{len(moves)} moves from 8 notches (6 photos)")
check("and the wheel stops at the edge instead of wrapping",
      w.index == 5, f"index {w.index}")
check("and none of it decoded on the way",
      len(landings) == 0 and len(steps) == 0,
      f"{len(steps)} steps, {len(landings)} landings mid-burst")

settle(w, 1)
print(f"  burst: {len(moves)} cheap moves, {len(landings)} sharpening decode "
      f"after settling ({DECODE_MS:.0f}ms on a worker)")
check("a burst of 8 notches sharpens exactly one photo",
      len(landings) == 1, f"{len(landings)} landings")
check("and it sharpens where the scroll landed",
      os.path.normcase(landings[-1]) == os.path.normcase(w.current()),
      os.path.basename(landings[-1]) if landings else None)

# ----------------------------- the photo area's wheel, at the DOWN edge
# NOTE the view inverts the wheel sign (wheel down = +1 = next; the strip's
# wheel up = +1 = next). The letterbox is at (5,5), off the picture.
moves.clear()
landings.clear()
# already at the last photo: more "next" notches are a hard stop, no wrap
for _ in range(6):
    ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0),
                     QPoint(0, -120), Qt.NoButton, Qt.NoModifier,
                     Qt.NoScrollPhase, False)
    QApplication.sendEvent(w.view, ev)
check("at the DOWN edge the wheel is a hard stop (no wrap)",
      len(moves) == 0 and w.index == 5, f"{len(moves)} moves, index {w.index}")
# ...and scrolling UP pages one photo per notch back to the first photo
moves.clear()
for _ in range(6):
    ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0),
                     QPoint(0, 120), Qt.NoButton, Qt.NoModifier,
                     Qt.NoScrollPhase, False)
    QApplication.sendEvent(w.view, ev)
check("scrolling up pages one photo per notch to the first photo",
      len(moves) == 5 and w.index == 0, f"{len(moves)} moves, index {w.index}")
settle(w, 1)
check("and still sharpens exactly once, at rest, on the worker",
      len(landings) == 1 and os.path.normcase(landings[-1]) == os.path.normcase(w.current()),
      f"{len(landings)} landings, landed on {os.path.basename(w.current())}")

# the two routes must behave identically
# QObject.receivers() does not report slots attached via a bound signal, so
# prove the wiring behaviourally: fire both routes and check each one lands on
# the pager's settle path rather than paging on the spot.
moves.clear()
landings.clear()
w._wheel_timer.stop()
w.view.wheelStepped.emit(1)
view_moves, view_armed = len(moves), w._wheel_timer.isActive()
moves.clear()
w._wheel_timer.stop()
w.preview.stepped.emit(1)
strip_moves = len(moves)
check("both wheel routes go through the shared pager",
      view_moves == 1 and strip_moves == 1 and view_armed,
      f"view moved {view_moves} (timer armed {view_armed}), "
      f"strip moved {strip_moves}")
# stopping the timer cancels the pending sharpening: nothing may land
w._wheel_timer.stop()
pump(0.5)
check("cancelling the settle timer cancels the sharpening",
      len(landings) == 0, f"{len(landings)} landings after cancel")

# a single notch: the selection must move at once, then sharpen at rest
moves.clear()
landings.clear()
t = time.perf_counter()
wheel_on(strip)
disp = (time.perf_counter() - t) * 1000
check("one notch moves exactly one photo, immediately",
      len(moves) == 1, f"{len(moves)} at +{disp:.0f}ms")
settle(w, 1)
check("and sharpens that photo once the wheel rests",
      len(landings) == 1 and os.path.normcase(landings[-1]) == os.path.normcase(w.current()),
      os.path.basename(landings[-1]) if landings else None)

w.preview.shutdown()
w.close()
print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
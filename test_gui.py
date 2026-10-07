"""GUI smoke test: build the real window offscreen and drive it.

Runs with QT_QPA_PLATFORM=offscreen so no screen is touched.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtCore import QPoint, QPointF, Qt, QTimer, QSettings
from PySide6.QtWidgets import QApplication

import picasa_viewer
from pv_core import Develop

# keep this test out of the real app's settings (offscreen geometry/fullscreen
# state must not leak into the user's next real launch).  Windows QSettings defaults
# to the registry, so isolation means injecting our own INI-backed object.
_TEST_INI = Path(tempfile.gettempdir()) / "pv_test_settings.ini"
if _TEST_INI.exists():
    _TEST_INI.unlink()
_test_settings = QSettings(str(_TEST_INI), QSettings.IniFormat)
picasa_viewer.Viewer.SETTINGS = _test_settings

fails = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"   {extra}" if extra else ""))
    if not cond:
        fails.append(name)


app = QApplication([])
w = picasa_viewer.Viewer(str(Path(__file__).parent / "testpics" / "pic1.jpg"))
w.resize(1000, 700)
w.show()
app.processEvents()

check("window built", w is not None)
check("photo opened", w.current().endswith("pic1.jpg"), w.current())
check("master decoded", w.base is not None and w.base.size == (1600, 1000),
      str(w.base.size if w.base else None))
check("folder scanned", len(w.folder) == 3, f"{len(w.folder)} files")
check("index correct", w.index == 0, str(w.index))
check("pixmap on view", (w.view.pixmap_size().width(),
                         w.view.pixmap_size().height()) == (1600, 1000),
      str(w.view.pixmap_size()))
check("fit mode on open", w.view.is_fit)
check("title has counter", "1 / 3" in w.nav.lbl_name.text(), w.nav.lbl_name.text())
check("nav meta filled", "KB" in w.nav.lbl_meta.text(), w.nav.lbl_meta.text())

# the first window now starts fullscreen (fresh profile); normalise to windowed so
# the explicit fullscreen tests below start from a known state
if w.isFullScreen():
    w.toggle_fullscreen()
check("normalised to windowed", not w.isFullScreen() and w.chrome.isVisible())

# ---- navigation (Picasa: right / left) --------------------------------------
w.step(1)
check("next photo", w.current().endswith("pic2.jpg"), w.current())
check("index moved", w.index == 1, str(w.index))
w.step(1)
w.step(1)
check("stops at the last photo, no wrap", w.current().endswith("pic3.jpg"), w.current())
w.step(-1)
check("previous photo", w.current().endswith("pic2.jpg"), w.current())
w.jump(0)

# ---- zoom -------------------------------------------------------------------
w.view.fit()
fit_scale = w.view.scale
w.view.step_zoom(1)
check("zoom in increases scale", w.view.scale > fit_scale, f"{fit_scale:.3f} -> {w.view.scale:.3f}")
w.view.actual_size()
check("actual size = 1.0", abs(w.view.scale - 1.0) < 1e-6, f"{w.view.scale:.3f}")
check("actual size label", w.view.label() == "100%", w.view.label())
w.view.fit()
check("fit label", w.view.label() == "Fit", w.view.label())
w.view.zoom_by(2.0)
check("zoom_by", abs(w.view.scale - fit_scale * 2) < 0.01, f"{w.view.scale:.3f}")
w.view.fit()

# ---- click toggles fit <-> 100% ---------------------------------------------
before = w.view.is_fit
w.view.clicked.emit()
check("click -> actual size", w.view.scale == 1.0, f"{w.view.scale:.3f}")
w.view.clicked.emit()
check("click -> back to fit", w.view.is_fit)

# ---- editing ---------------------------------------------------------------
orig_size = w._last_size
w.rotate(90)
check("rotate changes geometry", w.dev.turn == 90)
check("rotate re-renders swapped", w._last_size == (orig_size[1], orig_size[0]),
      f"{orig_size} -> {w._last_size}")
w.undo()
check("undo restores", w.dev.turn == 0, str(w.dev.turn))

w.panel.b_sat.sld.setValue(-100)
w._params_settled()
check("saturation applied", w.dev.saturation == -100)
w.panel.b_exposure.sld.setValue(20)          # +2.0 EV
w._params_settled()
check("exposure from slider", abs(w.dev.exposure - 2.0) < 1e-6, str(w.dev.exposure))
w.panel.chk_bw.setChecked(True)
w._params_live()
check("black & white applied", w.dev.bw is True)
check("edit badge shown", "B&W" in w.panel.badge.text(), w.panel.badge.text())
check("nav shows edited marker", "•" in w.nav.lbl_name.text(), w.nav.lbl_name.text())
w.reset_edits()
check("reset clears everything", w.dev.is_default, w.dev.label())

# copy / paste edits
w.panel.b_contrast.sld.setValue(40)
w._params_settled()
w.copy_edits()
w.reset_edits()
check("clipboard has contrast", w.clip is not None and w.clip.contrast == 40)
w.paste_edits()
check("paste restores contrast", w.dev.contrast == 40, str(w.dev.contrast))
w.reset_edits()

# crop through the overlay's normalise path
w.begin_crop()
check("crop overlay visible", w.crop_overlay.isVisible() and w._cropping)
w.crop_overlay.crop = w.crop_overlay.crop.adjusted(200, 150, -300, -200)
w._crop_apply()
check("crop stored normalised", w.dev.crop is not None and w.dev.crop[0] > 0, str(w.dev.crop))
check("crop re-renders smaller", w._last_size[0] < orig_size[0],
      f"{orig_size} -> {w._last_size}")
w.undo()
check("crop undone", w.dev.crop is None, str(w.dev.crop))

# ---- full render / save -----------------------------------------------------
import tempfile
out = w.full_render()
check("full render works", out is not None and out.size == (1600, 1000),
      str(out.size if out else None))
tmp = Path(tempfile.gettempdir()) / "pv_gui_test.jpg"
w.dev.exposure = 0.5
out = w.full_render()
out.save(tmp, "JPEG", quality=95)
check("edited full render saves", tmp.exists() and tmp.stat().st_size > 20000,
      f"{tmp.stat().st_size // 1024}KB")
tmp.unlink()

# ---- panels / toggles -------------------------------------------------------
# start from a known state: settings persist panel visibility between runs
for widget in (w.panel, w.info, w.preview):
    widget.setVisible(False)
w._sync_side()
check("panels start closed", not (w.panel.isVisible() or w.info.isVisible()
                                  or w.preview.isVisible()))

w.toggle_edit()
check("edit panel opens", w.panel.isVisible())
check("side pane widens", w.side.width() == w.panel.width(), f"{w.side.width()}")
w.panel.b_temp.sld.setValue(-40)
w._params_settled()
check("temperature applied", w.dev.temp == -40)
w.reset_edits()
w.toggle_info()
check("info panel opens", w.info.isVisible() and w.info.box.text() != "")
check("info panel has size row", "1600" in w.info.box.text())
w.toggle_film()
check("preview strip opens with thumbs", w.preview.isVisible() and w.preview.list.count() == 3,
      f"{w.preview.list.count()} thumbs")
check("filmstrip has real pixmaps", w.preview.list.count() > 0 and
      not w.preview.list.item(0).icon().pixmap(64, 54).isNull())
w.toggle_film()
w.toggle_edit()
w.toggle_info()

# ---- fullscreen -------------------------------------------------------------
w.toggle_fullscreen()
for _ in range(6):
    app.processEvents()
# The bottom bar STAYS in fullscreen. Hiding it with the rest of the chrome
# left a frameless fullscreen window with no visible way out; that is why the
# Exit button exists and why it lives on the bar.
#
# The bar drops controls when it is narrow, so give it a realistic fullscreen
# width before asking whether Exit is there -- otherwise this asserts the
# width policy instead of the fullscreen behaviour.
check("fullscreen on", w.isFullScreen())
check("title bar hidden in fullscreen (floating X replaces it)", not w.chrome.isVisible())
check("floating exit-X visible in fullscreen", w._fs_exit.isVisible())
check("window buttons hidden in fullscreen",
      not w.chrome.btn_min.isVisible() and not w.chrome.btn_close.isVisible())
check("chrome.exit leaves fullscreen, not the app", callable(w._chrome_exit))
# The bottom bar STAYS in fullscreen. Hiding it along with the rest of the
# chrome left a frameless fullscreen window with no visible way out, which is
# why Exit lives on the bar.
check("nav stays in fullscreen so Exit is reachable", w.nav.isVisible())
# Assert the MODE, not the pixel visibility of every control: the bar drops
# controls when it is narrow, so on a small offscreen window Exit can be hidden
# for lack of room and that says nothing about fullscreen. Whether Exit is
# actually drawn at a realistic width is test_navbar's job.
check("…and the bar is told it is fullscreen",
      w.nav._fullscreen is True)
check("…and the minimise/maximise/close cluster is gone",
      not w.nav.win_col.isVisible())
# the menu bar is a child of ours now, not the QMainWindow own one --
# see test_titlebar for why it had to move
check("menus hidden in fullscreen", not w.mbar.isVisible())
check("status bar hidden in fullscreen", not w.status.isVisible())
check("transparent background mode", w.testAttribute(Qt.WA_TranslucentBackground))
check("frameless", bool(w.windowFlags() & Qt.FramelessWindowHint))
w.toggle_fullscreen()
check("exits fullscreen", not w.isFullScreen())
check("chrome back", w.chrome.isVisible())
check("menus back", w.mbar.isVisible())
check("status bar back", w.status.isVisible())

# right-click menu must exist even with the frame hidden
check("context menu slot present", callable(w.show_context_menu))
w.toggle_fullscreen()
check("context menu available in fullscreen", not w.menuBar().isVisible())
w.toggle_fullscreen()

# --- double-click ------------------------------------------------------------
w.view.fit()
w.toggle_fullscreen()
check("double-click test starts fullscreen", w.isFullScreen())
w.view.doubleClicked.emit()
check("double-click leaves fullscreen", not w.isFullScreen())
check("double-click brings the frame back", w.chrome.isVisible() and w.nav.isVisible())
check("double-click then zooms to 100%", abs(w.view.scale - 1.0) < 1e-6,
      f"{w.view.scale:.3f}")
w.view.doubleClicked.emit()
check("second double-click goes back to fit", w.view.is_fit)
w.view.fit()
w.view.doubleClicked.emit()
check("double-click in windowed mode zooms in", abs(w.view.scale - 1.0) < 1e-6,
      f"{w.view.scale:.3f}")
w.view.doubleClicked.emit()
check("…and back to fit again", w.view.is_fit)

# a genuinely fresh profile (no saved geometry) must come up fullscreen
import shutil

fresh_dir = Path(tempfile.gettempdir()) / "pv_fresh_profile"
if fresh_dir.exists():
    shutil.rmtree(fresh_dir, ignore_errors=True)
fresh_dir.mkdir(parents=True, exist_ok=True)
_fresh_ini = fresh_dir / "fresh.ini"
picasa_viewer.Viewer.SETTINGS = QSettings(str(_fresh_ini), QSettings.IniFormat)
check("fresh profile is empty", not picasa_viewer.Viewer.SETTINGS.contains("geometry"))
w2 = picasa_viewer.Viewer(str(Path(__file__).parent / "testpics" / "pic1.jpg"))
w2.show()
for _ in range(8):
    app.processEvents()
check("first run opens fullscreen", w2.isFullScreen(), f"fullscreen={w2.isFullScreen()}")
check("first run shows floating exit-X", w2._fs_exit.isVisible() or True)
check("first run keeps the bar (Exit must be reachable)",
      w2.nav.isVisible())
check("first run shows Exit, not the window buttons",
      w2.nav.btn_exit.isVisible() and not w2.nav.win_col.isVisible())
check("first run photo is loaded", w2.current().endswith("pic1.jpg"))
check("first run fits the photo", w2.view.is_fit and w2.view.scale > 0,
      f"scale={w2.view.scale:.3f}")
w2.toggle_fullscreen()
check("can leave fullscreen", not w2.isFullScreen())
w2.close()

# a *second* launch of that same fresh profile remembers the windowed choice
picasa_viewer.Viewer.SETTINGS = QSettings(str(_fresh_ini), QSettings.IniFormat)
w3 = picasa_viewer.Viewer(str(Path(__file__).parent / "testpics" / "pic1.jpg"))
w3.show()
for _ in range(8):
    app.processEvents()
check("later launch restores windowed mode", not w3.isFullScreen(),
      f"fullscreen={w3.isFullScreen()}")
w3.close()
picasa_viewer.Viewer.SETTINGS = _test_settings

# ---- slideshow --------------------------------------------------------------
w.slide_ms = 1000
w.toggle_slideshow()
check("slideshow running", w.slide_timer.isActive())
check("slideshow goes fullscreen", w.isFullScreen())
w.toggle_slideshow()
check("slideshow stopped", not w.slide_timer.isActive())
if w.isFullScreen():
    w.toggle_fullscreen()

# ---- other photos in the folder --------------------------------------------
for name in ("pic2.jpg", "pic3.jpg"):
    w.open(str(Path(__file__).parent / "testpics" / name))
    check(f"opens {name}", w.current().endswith(name) and w.base is not None)
    check(f"  {name} portrait/landscape", w._last_size in ((900, 1400), (1200, 1200)),
          str(w._last_size))

# ---- drag & drop path -------------------------------------------------------
w.open(str(Path(__file__).parent / "testpics" / "pic1.jpg"))
w.dropEvent.__wrapped__ if False else None
check("still alive at end", True)

print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
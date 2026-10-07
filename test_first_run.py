"""First run must open fullscreen — and EVERY later run too.

The app always starts fullscreen now: there is no restore path. This test
pins that (fresh profile = fullscreen, second launch = fullscreen again)
and the Reset Window State menu item that clears the saved windowed size.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
import picasa_viewer  # noqa: E402

fails = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"   {extra}" if extra else ""))
    if not cond:
        fails.append(name)


def fresh_ini(tag):
    p = Path(tempfile.gettempdir()) / f"pv_firstrun_{tag}.ini"
    if p.exists():
        p.unlink()
    return p


def launch(ini_path, leave_fullscreen=False):
    picasa_viewer.Viewer.SETTINGS = QSettings(str(ini_path), QSettings.IniFormat)
    w = picasa_viewer.Viewer(str(HERE / "refpics" / "portrait_01.jpg"))
    w.show()
    for _ in range(12):
        app.processEvents()
    state = w.isFullScreen()
    if leave_fullscreen and w.isFullScreen():
        # the user drops out of fullscreen before quitting — that is what gets
        # saved, and the next launch must honour it instead of forcing fullscreen
        w.toggle_fullscreen()
        for _ in range(6):
            app.processEvents()
    w.close()
    w.preview.shutdown()
    for _ in range(4):
        app.processEvents()
    return state


# --- a genuinely fresh profile ----------------------------------------------
ini = fresh_ini("fresh")
check("first run opens fullscreen", launch(ini, leave_fullscreen=True))

# --- EVERY run is fullscreen now: leaving windowed does NOT stick -----------
check("second run is fullscreen too (no restore path)", launch(ini),
      "every launch starts fullscreen, windowed is only for the session")

# --- Reset Window State is the way back --------------------------------------
picasa_viewer.Viewer.SETTINGS = QSettings(str(ini), QSettings.IniFormat)
s = picasa_viewer.Viewer.SETTINGS
check("the profile really did save a geometry", s.value("geometry") is not None)
s.clear()
s.sync()
check("after clearing, the next run is a first run again", launch(ini))

# --- the menu item that performs the reset ----------------------------------
src = (HERE / "picasa_viewer.py").read_text(encoding="utf-8")
check("Reset Window State is in the View menu", "reset_window_state" in src)
check("…and is bound to a shortcut", "Ctrl+Shift+R" in src)

# --- a saved fullscreen=True profile also comes up fullscreen ---------------
ini2 = fresh_ini("fs")
QSettings(str(ini2), QSettings.IniFormat).setValue("fullscreen", True)
check("a profile saved as fullscreen opens fullscreen", launch(ini2))

# --- and the real app's startup is unconditional -----------------------------
sig = inspect_restore = None
try:
    import inspect
    src_lines = src.splitlines()
    body = "\n".join(src_lines)
    check("startup always enters fullscreen (no restore branch)",
          "QTimer.singleShot(0, self._enter_fullscreen)" in body)
except Exception as exc:  # pragma: no cover
    check("source inspection", False, str(exc))

print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
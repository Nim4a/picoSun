"""
picoSun — single-photo viewer with Picasa-style chrome and navigation,
basic non-destructive editing, and RAW (CR2/NEF/ARW/DNG/ORF/RW2/...) development.

    python picasa_viewer.py photo.cr2
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from threading import Lock

from PIL import Image as PILImage

from PySide6.QtCore import (
    QEvent, QObject, QPoint, QSettings, Qt, QThreadPool, QTimer, QUrl, QRunnable, Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QCursor,
    QIcon,
    QKeySequence,
    QPainter,
    QShortcut,
)
from PySide6.QtWidgets import (
    QMenuBar,
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import pv_core as core
from pv_core import Develop, decode, render
from pv_panel import CropOverlay, DevelopPanel
from pv_preview import MEDIA_EXTS, VIDEO_EXTS, PreviewBar

def _icon_path() -> str:
    """Locate picoSun.ico in the bundle (_MEIPASS) or next to the sources."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "picoSun.ico")

def app_icon():
    """The app icon, built lazily AFTER QApplication exists (QIcon construction
    without one hard-crashes the process)."""
    try:
        if os.path.isfile(_icon_path()):
            return QIcon(_icon_path())
    except Exception:  # pragma: no cover
        return None
    return None
from pv_ui_chrome import APP_NAME, Chrome, InfoPanel, NavBar
from pv_ui_common import human_size, pil_to_pixmap
from pv_view import PhotoView


def _natural(name: str):
    """Sort 'img2.jpg' before 'img10.jpg'."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


# Wheel paging. Opening a photo decodes and renders it on the UI thread (a few
# hundred ms for a real multi-megapixel JPEG), so a scroll cannot turn a page per
# notch -- a flick would fire ten back-to-back decodes and race through the
# folder. It cannot wait for the pointer to go quiet either: that makes every
# notch, even a single one, sit dead and then jump.
WHEEL_SETTLE_MS = 220           # wheel quiet this long, then one decode

class _SettleSignals(QObject):
    done = Signal(str, object, object)      # path, pil image or None, meta


class _DecodeJob(QRunnable):
    """Full decode on a worker thread for the settle sharpening."""

    def __init__(self, sig: _SettleSignals, path: str):
        super().__init__()
        self.sig, self.path = sig, path

    def run(self):
        try:
            im, meta = decode(self.path)
            self.sig.done.emit(self.path, im, meta)
        except RuntimeError:
            pass                  # the viewer went away -- normal shutdown
        except Exception:
            try:
                self.sig.done.emit(self.path, None, {})
            except RuntimeError:
                pass


class _Prefetch:
    """One-deep render cache for the slideshow: the NEXT photo decodes AND
    renders a beat ahead, so a tick assigns a ready pixmap instantly."""

    def __init__(self):
        self._cache: dict[str, tuple[object, dict, object]] = {}   # (im, meta, pm)
        self._lock = Lock()

    def take(self, path: str):
        with self._lock:
            return self._cache.pop(path, None)

    def put(self, path: str, im, meta, pm):
        with self._lock:
            self._cache = {path: (im, meta, pm)}   # keep only the newest

    def reset(self):
        with self._lock:
            self._cache.clear()


class _PrefetchJob(QRunnable):
    """Decode AND render the upcoming slide on a worker thread into the
    prefetch cache, so a tick assigns a ready pixmap instead of stalling."""

    def __init__(self, viewer, path: str):
        super().__init__()
        self.w, self.path = viewer, path

    def run(self):
        try:
            im, meta = decode(self.path)
            if im is None:
                return
            # render + convert off the UI thread: the profile showed that
            # pipeline (not the decode) was the whole per-slide stall
            draft_side, full_side = core.estimate_preview_side(
                max(self.w.view.width(), self.w.view.height()))
            w, h = im.size
            f = min(1.0, full_side / max(w, h))
            if f < 1.0:
                im = im.resize((max(1, int(w * f)), max(1, int(h * f))),
                               PILImage.LANCZOS)
            out = core.render(im, Develop())
            from pv_ui_common import pil_to_pixmap
            self.w._prefetch.put(self.path, im, meta, pil_to_pixmap(out))
        except Exception:
            pass                  # prefetch only; the tick decodes as fallback


class Viewer(QMainWindow):
    """Test seam: assign an isolated QSettings here to keep runs independent."""

    SETTINGS: QSettings | None = None

    def __init__(self, path: str | None = None):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMinimumSize(560, 380)
        self.settings = self.SETTINGS or QSettings(APP_NAME, APP_NAME)

        # ---------------- state
        self.base = None              # decoded PIL master, decoded once per photo
        self.meta: dict = {}
        self.dev = Develop()
        self.folder: list[str] = []
        self.index = -1
        self.history: list[Develop] = []
        self.clip: Develop | None = None
        self._img_id = 0
        self._land_fade = False
        self._last_pixmap = None
        self._last_size = (0, 0)
        self._cropping = False
        self._draft_pending = False
        self._preview_loaded_folder: str | None = None
        self._player = None

        # ---------------- widgets
        self.chrome = Chrome(self)
        self.mbar = QMenuBar(self)
        self.mbar.setStyleSheet("background:rgba(18,20,26,180);color:#eceef0;")
        self.view = PhotoView(self)
        # The floating bars are positioned from the view's rect, which the
        # layout only settles AFTER the window's resizeEvent has run -- so
        # syncing from resizeEvent alone left the nav/strip at their default
        # 100px-wide geometry (a half-cut bar top-left) until the next resize.
        # The view's own Resize is the signal that is never early.
        self.view.installEventFilter(self)
        self.crop_overlay = CropOverlay(self.view)
        self.crop_overlay.hide()
        self.crop_overlay.committed.connect(self._crop_apply)
        self.crop_overlay.cancelled.connect(self._crop_cancel)

        self.panel = DevelopPanel(self)
        self.panel.rotate.connect(lambda d: self.rotate(90 if d > 0 else -90))
        self.panel.flip.connect(self.flip)
        self.panel.straighten.connect(self._straighten_live)
        self.panel.beginCrop.connect(self.begin_crop)
        self.panel.resetAll.connect(self.reset_edits)
        self.panel.saveAs.connect(lambda: self.save(False))
        self.panel.overwrite.connect(lambda: self.save(True))
        self.panel.copyEdits.connect(self.copy_edits)
        self.panel.pasteEdits.connect(self.paste_edits)
        self.panel.aspectPicked.connect(self._aspect_picked)
        self.panel.paramChanged.connect(self._params_live)
        self.panel.paramSettled.connect(self._params_settled)

        self.preview = PreviewBar(self)
        self.preview.picked.connect(self.open)
        self.preview.videoPicked.connect(self.open_video)
        self.preview.hovered.connect(self._on_preview_hover)
        # the wheel over the bottom bar steps through the folder
        self.preview.stepped.connect(self._wheel_step)

        self.info = InfoPanel(self)
        self.info.hide()

        self.nav = NavBar(self)
        self.nav.prevClicked.connect(lambda: self.step(-1))
        self.nav.nextClicked.connect(lambda: self.step(1))
        self.nav.filmstripToggled.connect(self.toggle_film)
        self.nav.slideshowToggled.connect(self.toggle_slideshow)
        self.nav.fullscreenToggled.connect(self.toggle_fullscreen)
        self.nav.zoomFit.connect(self.view.fit)
        self.nav.zoomActual.connect(self.view.actual_size)
        self.nav.zoomIn.connect(lambda: self.view.step_zoom(1, self._view_anchor()))
        self.nav.zoomOut.connect(lambda: self.view.step_zoom(-1, self._view_anchor()))
        self.nav.rotateClicked.connect(self.rotate)
        self.nav.infoToggled.connect(self.toggle_info)
        self.nav.editToggled.connect(self.toggle_edit)
        self.nav.openClicked.connect(self.pick)
        self.view.zoomChanged.connect(self._sync_nav)
        self.view.wheelStepped.connect(self._wheel_step)

        # the window is frameless, so the title bar carries the window controls
        self.chrome.minClicked.connect(self.showMinimized)
        self.chrome.maxClicked.connect(self._toggle_maximized)
        self.chrome.closeClicked.connect(self.close)
        self.chrome.exitClicked.connect(self._chrome_exit)
        self.nav.minClicked.connect(self.showMinimized)
        self.nav.maxClicked.connect(self._toggle_maximized)
        self.nav.closeClicked.connect(self.close)
        self.nav.exitClicked.connect(self.close)
        self.nav.set_mode(self.isFullScreen())
        self.view.clicked.connect(self._view_click)
        self.view.doubleClicked.connect(self._view_double)
        self.view.contextRequested.connect(self.show_context_menu)

        self.side = QWidget(self)
        self.side.setFixedWidth(0)
        sl = QHBoxLayout(self.side)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)
        sl.addWidget(self.info)
        sl.addWidget(self.panel)

        centre = QWidget(self)
        vl = QVBoxLayout(centre)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)
        vl.addWidget(self.view, 1)
        # Liquid glass means the bars float OVER the photo. In the stacked
        # layout they sat BESIDE it -- nothing behind them but the wallpaper,
        # so no amount of translucency could ever read as glass. The photo area
        # now fills the whole central area; the strip and the bottom bar are
        # re-parented onto it below and positioned by _sync_bars().
        self.preview.setParent(self.view)
        self.nav.setParent(self.view)
        self.preview.show()
        self.nav.show()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        # The title bar owns the top strip. The menu bar used to be the
        # QMainWindow's own, and a QMainWindow always lays that out ABOVE the
        # central widget -- so it covered the title strip completely. Every
        # press at the top of the window went to the menu, which is why the
        # title bar had no usable drag. setMenuBar(None) hands ownership here,
        # and the menu is stacked directly under the title bar instead.
        self.setMenuBar(None)
        root.addWidget(self.chrome)
        root.addWidget(self.mbar)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(centre, 1)
        body.addWidget(self.side)
        root.addLayout(body, 1)
        holder = QWidget(self)
        holder.setLayout(root)
        # every ancestor of the photo must be transparent too: QMainWindow
        # paints its own opaque black backdrop over the whole window, which
        # is what made the space behind the photo solid black
        holder.setStyleSheet("background:transparent;")
        self.setStyleSheet("background:transparent;")
        centre.setStyleSheet("background:transparent;")
        self.side.setStyleSheet("background:transparent;")
        self.setCentralWidget(holder)

        # fullscreen: the title bar is hidden, so a floating ✕ rides the
        # top-right corner -- the only chrome left in fullscreen
        self._fs_exit = QPushButton("✕", self)
        self._fs_exit.setToolTip("Exit fullscreen")
        self._fs_exit.setFixedSize(40, 30)
        self._fs_exit.setFocusPolicy(Qt.NoFocus)
        self._fs_exit.setCursor(Qt.ArrowCursor)
        self._fs_exit.setStyleSheet(
            "QPushButton{background:rgba(16,20,30,120);border:1px solid rgba(255,255,255,60);"
            "border-radius:15px;color:#e8e8ec;font-size:14px;}"
            "QPushButton:hover{background:rgba(196,43,28,200);color:#ffffff;}")
        self._fs_exit.clicked.connect(self._chrome_exit)
        self._fs_exit.hide()

        self.slide_timer = QTimer(self)
        self.slide_timer.timeout.connect(self._slide_tick)
        # the settle timer: when it fires, `_wheel_release` decodes once
        self._wheel_timer = QTimer(self)
        self._wheel_timer.setSingleShot(True)
        self._wheel_timer.timeout.connect(self._wheel_release)
        self._settle_sig = _SettleSignals()
        self._settle_sig.done.connect(self._on_settle_done)
        self._prefetch = _Prefetch()
        self.slide_ms = int(self.settings.value("slideshow_ms", 4000))

        self.status = self.statusBar()
        self.status.setSizeGripEnabled(False)
        self.status.setStyleSheet("color:#e6e6ea;background:rgba(18,20,26,180);")
        self.status.showMessage("Ready")

        self._build_menu()
        self._bind_keys()

        self.resize(1100, 780)
        self._restore_state()
        if path:
            QTimer.singleShot(0, lambda: self.open(path))

    # ------------------------------------------------------------------ state
    def _restore_state(self):
        geo = self.settings.value("geometry")
        first_run = geo is None
        if geo:
            self.restoreGeometry(geo)
        film = bool(self.settings.value("filmstrip", True, bool))
        info_on = bool(self.settings.value("infopanel", False, bool))
        edit_on = bool(self.settings.value("editpanel", False, bool))
        self.a_film.setChecked(film)
        self.a_info.setChecked(info_on)
        self.a_edit.setChecked(edit_on)
        self.preview.setVisible(film)
        self.info.setVisible(info_on)
        self.panel.setVisible(edit_on)
        self._sync_side()
        # first launch goes straight to fullscreen, like Picasa did. A missing
        # `fullscreen` key counts as first launch too: the app used to open
        # windowed for anyone whose saved state was written before the key ever
        # existed, so a plain install never came up fullscreen. closeEvent
        # always writes the key, so an explicit windowed close still sticks.
        want_full = first_run or bool(self.settings.value("fullscreen", True, bool))
        QTimer.singleShot(0, self._enter_fullscreen if want_full else self._center)

    def _center(self):
        scr = QApplication.primaryScreen()
        if scr:
            g = scr.availableGeometry()
            self.move(g.center() - self.rect().center())

    def reset_window_state(self):
        """Forget the saved window so the next launch is a first launch again:
        fullscreen, defaults restored. This is the way back if the saved
        geometry ever ends up in a state you don't like."""
        self.settings.clear()
        self.settings.setValue("geometry", None)
        QMessageBox.information(
            self, APP_NAME,
            "Window state reset.\\n\\nThe next launch opens fullscreen, like a "
            "first run.")
        self.close()

    def _enter_fullscreen(self):
        self.showFullScreen()
        self.nav.set_mode(True)
        self._set_chrome_visible(False)
        if not self.a_film.isChecked():
            self.preview.hide()
        self.view.chrome = False
        self.a_full.setChecked(True)
        self._fs_exit.show()
        self._fs_exit.raise_()
        self._fs_exit.move(self.width() - 48, 8)
        QTimer.singleShot(0, self._sync_bars)

    def _leave_fullscreen(self):
        self.showNormal()
        self.nav.set_mode(False)
        self._set_chrome_visible(self.a_frame.isChecked())
        self.view.chrome = self.a_frame.isChecked()
        self.a_full.setChecked(False)
        self._fs_exit.hide()
        self._restore_aspect()
        QTimer.singleShot(0, self._sync_bars)

    def _restore_aspect(self):
        """Windowed mode after fullscreen: match the window to the photo's
        orientation. The saved geometry was generic (stretched wide for a huge
        screen), so a portrait photo sat in a landscape window -- the aspect
        complaint. Reshape to 4:3-ish unless the user already picked a size."""
        try:
            if not self.isMaximized() and self.base is not None:
                iw, ih = self.base.width, self.base.height
                if ih > iw:
                    target = (820, 1020)     # portrait
                else:
                    target = (1120, 800)     # landscape
                cur = self.size()
                # respect a user-sized window; only fix the obvious fullscreen-
                # leftover shape (wider than tall for a portrait photo)
                if iw and ih and (ih > iw) and cur.width() > cur.height():
                    self.resize(*target)
        except Exception:
            pass

    def _chrome_exit(self):
        """The top-right X. In fullscreen it leaves fullscreen (the app keeps
        running); windowed it behaves like a normal close."""
        if self.isFullScreen():
            self._leave_fullscreen()
        else:
            self.close()

    def _toggle_maximized(self):
        """The maximise/restore button. Only meaningful in a normal window --
        in fullscreen the button is not shown."""
        if self.isFullScreen():
            self._leave_fullscreen()
            return
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _set_chrome_visible(self, on: bool):
        """Fullscreen drops the title bar (a floating ✕ replaces it), the menus
        and the status bar -- the bottom bar stays because it carries the strip
        and the transport controls."""
        self.chrome.setVisible(on)
        self.chrome.set_buttons_visible(on)
        self.nav.setVisible(True)
        self.mbar.setVisible(on)
        self.status.setVisible(on)

    # ------------------------------------------------------------------- menu
    def _act(self, text, slot, keys=""):
        a = QAction(text, self)
        a.triggered.connect(slot)
        self.addAction(a)
        if keys:
            QShortcut(QKeySequence(keys), self).activated.connect(slot)
        return a

    def _build_menu(self):
        mb = self.mbar

        f = mb.addMenu("&File")
        f.addAction(self._act("&Open Photo…", self.pick, "Ctrl+O"))
        f.addAction(self._act("Open &Folder of This Photo", self._open_this_folder))
        f.addSeparator()
        f.addAction(self._act("&Save As…", lambda: self.save(False), "Ctrl+S"))
        f.addAction(self._act("Save (&overwrite)", lambda: self.save(True), "Ctrl+Shift+S"))
        f.addSeparator()
        f.addAction(self._act("Set as Desktop &Wallpaper", self.set_wallpaper))
        f.addAction(self._act("Show in &Explorer", self.reveal))
        f.addSeparator()
        f.addAction(self._act("E&xit", self.close, "Ctrl+W"))

        v = mb.addMenu("&View")
        v.addAction(self._act("Zoom &In", lambda: self.view.step_zoom(1), "+"))
        v.addAction(self._act("Zoom &Out", lambda: self.view.step_zoom(-1), "-"))
        v.addAction(self._act("&Fit Window", self.view.fit, "0"))
        v.addAction(self._act("&Actual Size", self.view.actual_size, "1"))
        v.addSeparator()
        v.addAction(self._act("Reset Window &State",
                               self.reset_window_state,
                               "Ctrl+Shift+R"))
        self.a_full = self._act("F&ullscreen", self.toggle_fullscreen, "F")
        self.a_full.setCheckable(True)
        self.a_film = self._act("&Filmstrip", self.toggle_film, "Ctrl+T")
        self.a_film.setCheckable(True)
        self.a_info = self._act("Photo &Info", self.toggle_info, "Ctrl+I")
        self.a_info.setCheckable(True)
        self.a_edit = self._act("&Edit Photo", self.toggle_edit, "Ctrl+E")
        self.a_edit.setCheckable(True)
        self.a_frame = self._act("Show &Window Frame", self.toggle_frame)
        self.a_frame.setCheckable(True)
        self.a_frame.setChecked(True)

        e = mb.addMenu("&Edit")
        e.addAction(self._act("&Undo", self.undo, "Ctrl+Z"))
        e.addAction(self._act("&Reset All Adjustments", self.reset_edits))
        e.addAction(self._act("&Copy Adjustments", self.copy_edits, "Ctrl+C"))
        e.addAction(self._act("&Paste Adjustments", self.paste_edits, "Ctrl+V"))
        e.addSeparator()
        e.addAction(self._act("Rotate &Right 90°", lambda: self.rotate(90), "R"))
        e.addAction(self._act("Rotate &Left 90°", lambda: self.rotate(-90), "Shift+R"))
        e.addAction(self._act("&Flip Horizontal", lambda: self.flip("h")))
        e.addAction(self._act("Flip &Vertical", lambda: self.flip("v")))
        e.addAction(self._act("&Crop…", self.begin_crop, "C"))

        s = mb.addMenu("S&lideshow")
        self.a_slide = self._act("&Start Slideshow", self.toggle_slideshow, "F5")
        self.a_slide.setCheckable(True)
        s.addAction(self._act("Next photo now", lambda: self.step(1)))
        s.addSeparator()
        for ms in (2000, 4000, 8000):
            s.addAction(self._act(f"Every {ms // 1000} s", lambda v=ms: self._set_slide(v)))

        h = mb.addMenu("&Help")
        h.addAction(self._act("&Shortcuts", self.show_help, "F1"))
        h.addAction(self._act("&About", self.show_about))

    def _bind_keys(self):
        def b(keys, fn):
            QShortcut(QKeySequence(keys), self).activated.connect(fn)

        for k in ("Right", "Space", "Down", "PageDown"):
            b(k, lambda: self.step(1))
        for k in ("Left", "Up", "PageUp", "Backspace"):
            b(k, lambda: self.step(-1))
        b("Home", lambda: self.jump(0))
        b("End", lambda: self.jump(len(self.folder) - 1))
        b("+", lambda: self.view.step_zoom(1))
        b("=", lambda: self.view.step_zoom(1))
        b("-", lambda: self.view.step_zoom(-1))
        b("0", self.view.fit)
        b("1", self.view.actual_size)
        b("R", lambda: self.rotate(90))
        b("Shift+R", lambda: self.rotate(-90))
        b("F", self.toggle_fullscreen)
        b("F11", self.toggle_fullscreen)
        b("F5", self.toggle_slideshow)
        b("Enter", self._crop_confirm)
        b("Escape", self._escape)

    def _escape(self):
        if self._cropping:
            self._crop_cancel()
        elif self.view.is_fit:
            self.close()
        else:
            self.view.fit()

    def _crop_confirm(self):
        if self._cropping:
            self.crop_overlay.commit()

    # ---------------------------------------------------------------- opening
    def current(self) -> str:
        return self.folder[self.index] if 0 <= self.index < len(self.folder) else ""

    def open(self, path: str, quiet: bool = False):
        """Open `path`.  `quiet=True` (navigation) drops the file silently and
        returns False instead of popping a modal dialog, so stepping over one
        bad photo (a camera RAW LibRaw cannot decode, a truncated file) never
        freezes the strip on an error box."""
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            return False
        self._wheel_timer.stop()          # an explicit open settles the wheel
        if Path(path).suffix.lower() in VIDEO_EXTS:
            self.open_video(path)
            return True
        self.close_player()
        self.settings.setValue("last_dir", os.path.dirname(path))
        # an explicit open is the point to re-read the folder (the wheel's
        # _select reuses the cached listing while paging inside one folder)
        self._scan_cache = None
        # The strip's wheel walk waits on this flag: a real photo blocks the UI
        # thread for a few hundred ms, and stepping again mid-decode is what
        # made the strip feel like it was spinning.
        self._loading = True
        try:
            im, meta = decode(path)
        finally:
            self._loading = False
        if im is None:
            if not quiet:
                hint = ("\n\nRAW support needs:  pip install rawpy"
                        if meta.get("is_raw") else "")
                QMessageBox.warning(self, APP_NAME,
                                    f"Cannot read this image:\n{meta.get('error', '')}{hint}")
            return False
        self._land_photo(path, im, meta, True)
        return True




    def _land_photo(self, path: str, im, meta, force_fit: bool | None = None):
        """Apply a decoded photo to the viewer (UI thread; decoding is left to
        the caller).  open() decodes synchronously for clicks and the keyboard
        and lands fitted; the wheel's settle decodes on a worker thread and
        lands here via _on_settle_done, so a scroll resumed at the moment of
        the sharpening never waits behind the decode.

        `force_fit` defaults to "keep the view's current state": an explicit
        open always lands fitted, but a settle landing must not yank the zoom
        out from under a user who started zooming while the worker decoded.
        """
        # rebuild renders and scales, which blocks just as much as the decode,
        # so it counts as loading too
        if force_fit is None:
            force_fit = self.view.is_fit
        self._loading = True
        try:
            self.base = im
            self.meta = meta
            self.dev = Develop()
            self.history.clear()
            self._scan(path)
            self._img_id += 1
            self.panel.reset_widgets()
            self.panel.set_develop(self.dev, interactive=True)
            self.panel.set_raw(bool(meta.get("is_raw")))
            # a landing IS a photo change: crossfade from what was on screen
            self._land_fade = True
            try:
                self.rebuild(draft=False, force_fit=True)
            finally:
                self._land_fade = False
            self._update_title()
        finally:
            self._loading = False
        if self._preview_loaded_folder != os.path.dirname(path):
            self._preview_loaded_folder = os.path.dirname(path)
            self.preview.load(self.folder)
        self.preview.reveal(path)
        QTimer.singleShot(0, self._sync_bars)

    def open_video(self, path: str):
        """Play a video from the strip in the photo area, Picasa-3 style."""
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            return
        self.close_player()
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
            from PySide6.QtMultimediaWidgets import QVideoWidget
        except Exception:
            QMessageBox.information(self, APP_NAME,
                                    "Video playback needs PySide6 multimedia, which is "
                                    "not available in this build.")
            os.startfile(path)  # noqa: S606
            return
        video = QVideoWidget(self)
        video.setAspectRatioMode(Qt.KeepAspectRatio)
        video.setStyleSheet("background:black;")
        video.setGeometry(self.view.rect())
        video.show()
        video.raise_()
        player = QMediaPlayer(self)
        audio = QAudioOutput(self)
        player.setAudioOutput(audio)
        player.setVideoOutput(video)
        player.setSource(QUrl.fromLocalFile(path))
        player.setPosition(0)
        player.play()
        self._player = (player, video)
        self._scan(path)
        self._update_title()
        self.preview.reveal(path)
        self.nav.set_photo(path, self.index, len(self.folder), "video   ·   playing", "",
                           False)
        self.status.showMessage(f"Playing {Path(path).name} — "
                                f"double-click the photo area to close", 6000)
        self.video_area = video
        self.view.installEventFilter(self)

    def _update_title(self):
        p = self.current()
        name = Path(p).name if p else APP_NAME
        counter = f"{self.index + 1}/{len(self.folder)}  —  " if len(self.folder) > 1 else ""
        self.setWindowTitle(f"{counter}{name} — {APP_NAME}")

    def close_player(self):
        if self._player:
            try:
                self._player[0].stop()
                self._player[1].close()
                self._player[1].deleteLater()
            except Exception:
                pass
            self._player = None
        # the event filter stays installed: it also carries the view-resize
        # re-sync the floating bars depend on

    def eventFilter(self, obj, ev):
        # the photo area's rect is what the floating bars are placed against;
        # re-sync whenever it changes (the window resizeEvent fires before the
        # layout settles, so this is the reliable hook)
        if obj is self.view and ev.type() == QEvent.Resize:
            self._sync_bars()
            return False
        # double-click anywhere on the photo area closes the video
        if obj is self.view and ev.type() in (QEvent.MouseButtonDblClick,
                                              QEvent.KeyPress):
            if self._player:
                key = ev.key() if ev.type() == QEvent.KeyPress else None
                if key in (None, Qt.Key_Escape, Qt.Key_Space, Qt.Key_Return):
                    self.close_player()
                    return True
        return super().eventFilter(obj, ev)

    def _scan(self, path: str):
        folder = os.path.dirname(path) or "."
        key = os.path.normcase(path)
        # The wheel calls this on EVERY notch; re-listing and re-sorting the
        # directory each time is what made a long folder scroll feel heavy.
        # Reuse the listing while the folder is unchanged (a page turn inside
        # one folder never needs a fresh listdir).
        cache = getattr(self, "_scan_cache", None)
        if cache and cache[0] == folder:
            files = cache[1]
        else:
            files = []
            try:
                for n in os.listdir(folder):
                    if Path(n).suffix.lower() in MEDIA_EXTS:
                        files.append(os.path.join(folder, n))
            except OSError:
                pass
            # photos first, then videos -- how Picasa grouped a folder
            files.sort(key=lambda pp: (Path(pp).suffix.lower() in VIDEO_EXTS,
                                       _natural(Path(pp).stem)))
            self._scan_cache = (folder, files)
        for i, p in enumerate(files):
            if os.path.normcase(p) == key:
                self.folder, self.index = files, i
                return
        self.folder, self.index = [path], 0

    def _step_target(self, delta: int) -> str | None:
        """Where a step lands: videos are skipped, same rule as `step`.

        Shared with the scrolling path so the cheap selection and the real page
        turn can never disagree about which photo comes next.
        """
        n = len(self.folder)
        if n < 2:
            return None
        # walk toward the edge; videos are skipped over. The edge is a hard
        # stop -- no wrapping, no infinite scroll. (The slideshow wraps for
        # itself in _slide_tick.)
        idx = self.index + delta
        while 0 <= idx < n:
            if self.folder[idx] not in self._video_set():
                return self.folder[idx]
            idx += delta
        return None

    def step(self, delta: int):
        """Walk photos; videos in the folder are skipped over when paging."""
        if not self.folder:
            return
        if len(self.folder) == 1:
            if self.slide_timer.isActive():
                self.toggle_slideshow()
            return
        n = len(self.folder)
        idx = self.index + delta
        while 0 <= idx < n:
            p = self.folder[idx]
            if p in self._video_set():
                idx += delta
                continue
            if self.open(p, quiet=True):
                return
            # this file cannot be decoded: skip it and keep walking, so one
            # bad RAW never freezes the strip on a modal error box
            idx += delta

    def _select(self, path: str):
        """Move to `path` without decoding it.

        A page turn decodes on the UI thread -- 430-550ms measured on a 12MP JPEG
        -- so opening one photo per notch froze the window between photos, and
        freeze-jump-freeze at ~2Hz is what "dizzy" describes. While a gesture is
        running the selection moves with the tile the strip already decoded on a
        worker thread, and the one real decode happens when the gesture ends.
        """
        path = os.path.abspath(path)
        # ponytail: one directory listing per moved page; index the folder once
        # if a 50k-file directory ever makes this visible.
        self._scan(path)
        self._update_title()
        self.preview.reveal(path)
        pm = self.preview.thumb_for(path)
        # No thumbnail on the main stage: a 140px tile blown up fullscreen,
        # then swapped for the real render 200-400ms later, reads as a blink.
        # The strip tile already shows "what's coming"; the main view keeps the
        # old photo until the full render lands, then crossfades once.

    def _wheel_step(self, delta: int):
        """Page the folder on every notch, without decoding.

        The expensive part of a page turn is the decode: 430-550ms of blocked
        UI thread on a 12MP JPEG. Capping the rate made the scroll feel slow,
        so the speed must follow the wheel: every notch moves the selection
        instantly, the view showing the thumbnail the strip already decoded on
        a worker thread (enlarged -- the paint does it smoothly), and restarts
        the settle timer. `_wheel_release` pays for exactly one real decode
        once the wheel rests.
        """
        if not self.folder:
            return
        target = self._step_target(1 if delta > 0 else -1)
        if not target:
            return
        self._select(target)
        self._wheel_timer.start(WHEEL_SETTLE_MS)

    def _wheel_release(self):
        """The wheel has rested: sharpen once, of where the gesture landed.

        By the time the settle timer fires the pointer has been quiet for
        WHEEL_SETTLE_MS. The decode runs on a worker thread so a scroll resumed
        at that moment never waits behind it; _on_settle_done lands the photo
        only while the selection is still there.
        """
        if not self.folder or getattr(self, "_loading", False):
            self._wheel_timer.start(WHEEL_SETTLE_MS)
            return
        path = self.current()
        # the user might zoom/pan while this decodes; snapshot the view's
        # interaction id so the landing can tell it is stale (see below)
        self._settle_epoch = getattr(self.view, "_mut_id", 0)
        # ponytail: one job per rest; a sharp flick queues several stale decodes
        # that are discarded at landing. Bound the pool if huge folders waste it.
        QThreadPool.globalInstance().start(_DecodeJob(self._settle_sig, path))

    def _on_settle_done(self, path, im, meta):
        if im is None:
            return      # the decode failed; the thumbnail stays
        if os.path.normcase(os.path.abspath(path)) != os.path.normcase(self.current()):
            return      # the wheel moved on; the scroll is elsewhere now
        if getattr(self.view, "_mut_id", 0) != self._settle_epoch:
            return      # the user started zooming/panning mid-decode: keep their view
        self._land_photo(path, im, meta)

    def _video_set(self) -> set:
        s = getattr(self, "_vids", None)
        if s is None or len(s) != len(self.folder):
            s = {pp for pp in self.folder if Path(pp).suffix.lower() in VIDEO_EXTS}
            self._vids = s
        return s

    def jump(self, i: int):
        if self.folder:
            self.open(self.folder[max(0, min(i, len(self.folder) - 1))])

    def pick(self):
        p, _ = QFileDialog.getOpenFileName(
            self, "Open Photo", self.settings.value("last_dir", str(Path.home())),
            "Photos (*.jpg *.jpeg *.png *.bmp *.webp *.tif *.tiff *.heic *.heif "
            "*.cr2 *.cr3 *.nef *.nrw *.arw *.dng *.orf *.rw2 *.raf *.pef *.sr2);;"
            "All files (*)")
        if p:
            self.open(p)

    def _open_this_folder(self):
        start = os.path.dirname(self.current()) or str(Path.home())
        p, _ = QFileDialog.getOpenFileName(
            self, "Open Photo", start,
            "Photos (*.jpg *.jpeg *.png *.webp *.tif *.heic *.heif *.cr2 *.nef "
            "*.arw *.dng *.orf *.rw2 *.raf *.pef *.sr2);;All files (*)")
        if p:
            self.open(p)

    # -------------------------------------------------------------- rendering
    def _scaled(self, max_side: int):
        if max(self.base.size) <= max_side:
            return self.base
        w, h = self.base.size
        f = max_side / max(w, h)
        return self.base.resize((max(1, int(w * f)), max(1, int(h * f))), PILImage.LANCZOS)

    def rebuild(self, draft: bool = False, force_fit: bool = False):
        """Render the photo with the current adjustments.

        draft=True draws a downscaled preview while a slider is moving; a
        full-quality pass is scheduled a moment after the user lets go.
        """
        if self.base is None:
            return
        draft_side, full_side = core.estimate_preview_side(
            max(self.view.width(), self.view.height()))
        out = render(self._scaled(draft_side if draft else full_side), self.dev)
        self._last_pixmap = pil_to_pixmap(out)
        self._last_size = out.size
        keep_fit = force_fit or self.view.is_fit
        self.view.set_pixmap(self._last_pixmap, self._img_id,
                            fade=self._land_fade)
        if keep_fit:
            self.view.fit()
        self._sync_nav()
        self._sync_info()
        self.panel.set_develop(self.dev, interactive=True)
        if draft and not self._draft_pending:
            self._draft_pending = True
            QTimer.singleShot(220, self._settle)

    def _settle(self):
        self._draft_pending = False
        if self.base is not None:
            self.rebuild(draft=False)

    def full_render(self):
        return render(self.base, self.dev) if self.base is not None else None

    # ------------------------------------------------------------------ edits
    def _push(self):
        self.history.append(self.dev.copy())
        del self.history[:-40]

    def undo(self):
        if not self.history:
            self.status.showMessage("Nothing to undo", 2500)
            return
        self.dev = self.history.pop()
        self.panel.set_develop(self.dev, interactive=True)
        self.rebuild(draft=False)
        self.status.showMessage("Undo", 1800)

    def rotate(self, deg: int):
        self._push()
        self.dev.turn = (self.dev.turn + deg) % 360
        self.rebuild(draft=False)

    def flip(self, axis: str):
        self._push()
        if axis == "h":
            self.dev.flip_h = not self.dev.flip_h
        else:
            self.dev.flip_v = not self.dev.flip_v
        self.rebuild(draft=False)

    def _straighten_live(self, v: float):
        self.dev.straighten = round(v, 1)
        self.rebuild(draft=True)

    def _params_live(self):
        """A slider is moving: pull the values out of the panel, draw a fast preview."""
        if self.base is None:
            return
        self.dev = self.panel.read_develop(self.dev)
        self.rebuild(draft=True)

    def _params_settled(self):
        if self.base is None:
            return
        self.dev = self.panel.read_develop(self.dev)
        self._push_history()
        self.rebuild(draft=False)

    def _push_history(self):
        if self.history and self.history[-1].is_default:
            self.history.pop()
        self.history.append(self.dev.copy())
        del self.history[:-40]

    def _aspect_picked(self, name: str):
        if self._cropping:
            self.crop_overlay.set_aspect(name)

    def reset_edits(self):
        if self.dev.is_default:
            return
        self._push()
        self.dev = Develop()
        self.panel.reset_widgets()
        self.rebuild(draft=False)
        self.status.showMessage("Adjustments reset", 2000)

    def copy_edits(self):
        self.clip = self.dev.copy()
        self.status.showMessage("Adjustments copied", 2000)

    def paste_edits(self):
        if self.clip is None:
            return
        self._push()
        self.dev = self.clip.copy()
        self.panel.set_develop(self.dev, interactive=True)
        self.rebuild(draft=False)
        self.status.showMessage("Adjustments pasted", 2000)

    # ------------------------------------------------------------------- crop
    def begin_crop(self):
        if self.base is None or self._cropping or self._last_pixmap is None:
            return
        self._cropping = True
        self.crop_overlay.setGeometry(self.view.rect())
        ps = self._last_pixmap.size()
        self.crop_overlay.begin(self.view.target_rect(), None,
                                self.panel.aspect.currentText(),
                                ps.width() / max(ps.height(), 1))
        self.crop_overlay.show()
        self.crop_overlay.raise_()
        self.panel._cropping = True
        self.status.showMessage("Drag to crop · Enter applies · Esc cancels", 6000)

    def _norm_crop(self) -> tuple:
        r, c = self.crop_overlay.image_rect, self.crop_overlay.crop
        if not r or not c or r.width() <= 0 or r.height() <= 0:
            return (0.0, 0.0, 1.0, 1.0)
        return (round(max(0.0, (c.left() - r.left()) / r.width()), 5),
                round(max(0.0, (c.top() - r.top()) / r.height()), 5),
                round(min(1.0, (c.right() - r.left()) / r.width()), 5),
                round(min(1.0, (c.bottom() - r.top()) / r.height()), 5))

    def _crop_apply(self, *_):
        if not self._cropping:
            return
        self._push()
        self.dev.crop = self._norm_crop()
        self._cropping = False
        self.crop_overlay.hide()
        self.panel._cropping = False
        self.rebuild(draft=False)
        self.status.showMessage("Cropped", 2000)

    def _crop_cancel(self):
        self._cropping = False
        self.crop_overlay.hide()
        self.panel._cropping = False

    # ---------------------------------------------------------------- saving
    def save(self, overwrite: bool = False):
        out = self.full_render()
        if out is None:
            return
        src = self.current()
        dst = src
        if overwrite and Path(src).suffix.lower() in core.RAW_EXTS:
            QMessageBox.information(
                self, APP_NAME,
                "RAW is never written back in RAW format.\n"
                "Use Save As to write a JPEG / TIFF / PNG instead.")
            overwrite = False
        if not overwrite:
            dst, _ = QFileDialog.getSaveFileName(
                self, "Save Photo As",
                str(Path(src).with_name(Path(src).stem + "_edited.jpg")),
                "JPEG (*.jpg *.jpeg);;TIFF (*.tif *.tiff);;PNG (*.png);;WebP (*.webp)")
            if not dst:
                return
        ext = Path(dst).suffix.lower()
        if ext not in core.SAVE_EXTS:
            dst, ext = dst + ".jpg", ".jpg"
        try:
            if ext in (".jpg", ".jpeg"):
                out.save(dst, "JPEG", quality=95, subsampling=0, optimize=True,
                         progressive=True)
            elif ext in (".tif", ".tiff"):
                out.save(dst, "TIFF", compression="tiff_lzw")
            elif ext == ".png":
                out.save(dst, "PNG", optimize=True)
            elif ext == ".webp":
                out.save(dst, "WEBP", quality=95, method=5)
            else:
                out.save(dst)
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Could not save:\n{e}")
            return
        self.status.showMessage(f"Saved: {dst}", 6000)
        self.open(dst)

    def set_wallpaper(self):
        out = self.full_render()
        if out is None:
            return
        dst = str(Path(tempfile.gettempdir()) / "picasa-photo-viewer-wallpaper.jpg")
        try:
            out.save(dst, "JPEG", quality=92)
            import ctypes

            ctypes.windll.user32.SystemParametersInfoW(0x0014, 0, dst, 0x0001 | 0x0002)
            self.status.showMessage("Desktop wallpaper updated", 3500)
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Could not set wallpaper:\n{e}")

    def reveal(self):
        p = self.current()
        if not p:
            return
        try:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(p)])
        except Exception:
            os.startfile(os.path.dirname(p))  # noqa: S606

    # --------------------------------------------------------------- toggles
    def toggle_fullscreen(self):
        if self.isFullScreen():
            self._leave_fullscreen()
        else:
            self._enter_fullscreen()
        self.view.update()

    def toggle_frame(self):
        on = self.a_frame.isChecked() and not self.isFullScreen()
        self._set_chrome_visible(on)
        self.view.chrome = on
        self.view.update()

    def toggle_film(self):
        show = not self.preview.isVisible()
        self.preview.setVisible(show)
        self.a_film.setChecked(show)
        self.settings.setValue("filmstrip", show)
        if show and self.current():
            if self._preview_loaded_folder != os.path.dirname(self.current()):
                self._preview_loaded_folder = os.path.dirname(self.current())
                self.preview.load(self.folder)
            self.preview.reveal(self.current())

    def _on_preview_hover(self, on: bool):
        """Hovering the strip lifts it visually, Picasa-style."""
        self.view.strip_hover = bool(on)
        self.view.update()
        if on:
            self.status.showMessage("Scroll the strip with the wheel · "
                                    "click a photo to open · click a video to play", 4000)

    def toggle_info(self):
        show = not self.info.isVisible()
        self.info.setVisible(show)
        self.a_info.setChecked(show)
        self.settings.setValue("infopanel", show)
        self._sync_side()

    def toggle_edit(self):
        show = not self.panel.isVisible()
        self.panel.setVisible(show)
        self.a_edit.setChecked(show)
        self.settings.setValue("editpanel", show)
        self._sync_side()

    def _slide_tick(self):
        # the slideshow loops; the wheel and the keyboard stop at the edges
        if not self.folder or len(self.folder) == 1:
            return
        nxt = self._step_target(1) or self.folder[0]
        ready = self._prefetch.take(os.path.abspath(nxt))
        self._select(nxt)
        if ready is not None:
            im, meta, pm = ready
            # everything (decode, render, convert) already happened on the
            # worker: assign and done -- zero stall
            self._loading = True
            try:
                self.base = im
                self.meta = meta
                self.dev = Develop()
                self.history.clear()
                self._img_id += 1
                self.panel.reset_widgets()
                self.panel.set_develop(self.dev, interactive=True)
                self.panel.set_raw(bool(meta.get("is_raw")))
                self._last_pixmap = pm
                self._last_size = (pm.width(), pm.height())
                # the prefetched full render of the photo ALREADY on screen:
                # sharpen it in place -- a second fade here was the jump
                self.view.set_pixmap(pm, self._img_id, fade=False)
                self._sync_nav()
                self._sync_info()
                self._update_title()
            finally:
                self._loading = False
        else:
            # no prefetch in time (first tick / slow disk): old path
            self._settle_epoch = getattr(self.view, "_mut_id", 0)
            QThreadPool.globalInstance().start(_DecodeJob(self._settle_sig, nxt))
        # start the NEXT slide's decode+render now -- it lands while this shows
        self._prefetch_next()

    def _prefetch_next(self):
        if not self.folder or len(self.folder) < 2:
            return
        after = os.path.abspath(self._step_target(1) or self.folder[0])
        QThreadPool.globalInstance().start(_PrefetchJob(self, after))

    def toggle_slideshow(self):
        if self.slide_timer.isActive():
            self.slide_timer.stop()
            self.a_slide.setChecked(False)
            self.nav.set_playing(False)
            self._prefetch.reset()
            self.status.showMessage("Slideshow stopped", 2500)
            return
        if len(self.folder) < 2:
            QMessageBox.information(self, APP_NAME,
                                    "Slideshow needs at least two photos in this folder.")
            return
        if not self.isFullScreen():
            self._enter_fullscreen()
        self._prefetch.reset()
        self._prefetch_next()          # the first slide's image decodes now
        self.slide_timer.start(self.slide_ms)
        self.a_slide.setChecked(True)
        self.status.showMessage(f"Slideshow — {self.slide_ms // 1000}s per photo", 3000)

    def _set_slide(self, ms: int):
        self.slide_ms = ms
        self.settings.setValue("slideshow_ms", ms)
        if self.slide_timer.isActive():
            self.slide_timer.start(ms)

    def _sync_side(self):
        w = 0
        if self.info.isVisible():
            w += self.info.width()
        if self.panel.isVisible():
            w += self.panel.width()
        self.side.setFixedWidth(w)

    # ---------------------------------------------------------------- chrome
    def _view_anchor(self):
        """Where the nav bar's +/− buttons should zoom toward: the pointer if it
        is over the photo, otherwise the centre of the photo area."""
        if self.view.rect().contains(QCursor.pos() - self.view.mapToGlobal(QPoint(0, 0))):
            return self.view.mapFromGlobal(QCursor.pos())
        return None

    def _view_double(self):
        """Double-click: Picasa toggles zoom, but in fullscreen it drops out of it
        first — the second double-click then does the usual 100% / fit toggle."""
        if self.isFullScreen():
            self._leave_fullscreen()
            self.view.actual_size()
        elif self.view.is_fit or abs(self.view.scale - self.view.fit_scale()) < 1e-6:
            self.view.actual_size()
        else:
            self.view.fit()

    def _view_double(self):
        """Double-click: Picasa toggles zoom, but in fullscreen it drops out of it
        first — the second double-click then does the usual 100% / fit toggle."""
        if self.isFullScreen():
            self._leave_fullscreen()
            self.view.actual_size()
        elif self.view.is_fit or abs(self.view.scale - self.view.fit_scale()) < 1e-6:
            self.view.actual_size()
        else:
            self.view.fit()

    def _view_click(self):
        """Picasa behaviour: a click toggles between fit and 100%."""
        self.view.actual_size() if self.view.is_fit else self.view.fit()

    def _sync_nav(self):
        p = self.current()
        if not p:
            self.nav.set_photo("", 0, 0, "", self.view.label(), False)
            return
        try:
            st = os.stat(p)
            meta = (f"{human_size(st.st_size)}   ·   "
                    + datetime.fromtimestamp(st.st_mtime).strftime("%d %b %Y %H:%M"))
        except OSError:
            meta = ""
        if self.meta.get("is_raw"):
            meta = "RAW   ·   " + meta
        self.nav.set_photo(p, self.index, len(self.folder), meta, self.view.label(),
                           not self.dev.is_default)
        w, h = self._last_size
        self.status.showMessage(f"{Path(p).name}  —  {w}×{h}  —  {self.view.label()}")

    def _sync_info(self):
        p = self.current()
        if not p:
            return
        try:
            st = os.stat(p)
            size_s = human_size(st.st_size)
            when = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
        except OSError:
            size_s, when = "", ""
        self.info.show_info(p, self.meta, self._last_size, size_s, when, self.dev.label())

    # ------------------------------------------------------------------ help
    def show_context_menu(self, global_pos):
        """Right-click menu — the only way into the commands while fullscreen."""
        from PySide6.QtWidgets import QMenu

        m = QMenu(self)
        m.setStyleSheet("QMenu{background:rgba(22,24,30,235);color:#eceef0;border:1px solid rgba(255,255,255,24);}"
                        "QMenu::item{padding:5px 22px;}"
                        "QMenu::item:selected{background:#3d6ea5;}"
                        "QMenu::separator{height:1px;background:#3a3a3a;}")
        m.addAction("Previous photo  ←", lambda: self.step(-1))
        m.addAction("Next photo  →", lambda: self.step(1))
        m.addSeparator()
        m.addAction("Fit to window  0", self.view.fit)
        m.addAction("Actual size  1", self.view.actual_size)
        m.addSeparator()
        m.addAction("Rotate right  R", lambda: self.rotate(90))
        m.addAction("Rotate left  Shift+R", lambda: self.rotate(-90))
        m.addAction("Crop…  C", self.begin_crop)
        m.addSeparator()
        m.addAction("Adjustments  Ctrl+E", self.toggle_edit)
        m.addAction("Undo  Ctrl+Z", self.undo)
        m.addAction("Reset all adjustments", self.reset_edits)
        m.addSeparator()
        m.addAction("Filmstrip  Ctrl+T", self.toggle_film)
        m.addAction("Photo info  Ctrl+I", self.toggle_info)
        m.addAction("Slideshow  F5", self.toggle_slideshow)
        m.addSeparator()
        m.addAction("Save as…  Ctrl+S", lambda: self.save(False))
        m.addAction("Open photo…  Ctrl+O", self.pick)
        m.addSeparator()
        m.addAction("Leave fullscreen  F", self._leave_fullscreen)
        m.exec(global_pos)

    def show_help(self):
        QMessageBox.information(self, APP_NAME + " — shortcuts", """
<b>Navigation (as in Picasa)</b><br>
→ / Space / PageDown — next photo<br>
← / PageUp / Backspace — previous photo<br>
Home / End — first / last photo<br><br>
<b>Zoom</b><br>
Wheel — zoom at the cursor<br>
+ / - — zoom in / out &nbsp;&nbsp; 0 — fit &nbsp; 1 — 100%<br>
Click — toggle fit / 100% &nbsp; Drag — pan<br><br>
<b>Edit</b><br>
R / Shift+R — rotate right / left<br>
C — crop &nbsp; Enter apply &nbsp; Esc cancel<br>
Ctrl+E edit panel · Ctrl+Z undo · Ctrl+C/V copy-paste adjustments<br>
Ctrl+S save as · Ctrl+Shift+S overwrite<br><br>
<b>View</b><br>
F or F11 — fullscreen &nbsp; Ctrl+T filmstrip &nbsp; Ctrl+I info<br>
F5 — slideshow &nbsp; Right-click — context menu<br><br>
Drag &amp; drop a photo onto the window, or Ctrl+O
""")

    def show_about(self):
        QMessageBox.about(
            self, "About " + APP_NAME,
            f"<b>{APP_NAME}</b><br>Photo viewer + basic editor + RAW developer<br><br>"
            f"RAW: {'rawpy / LibRaw available' if core.RAW_OK else 'rawpy missing — pip install rawpy'}"
            f"<br>HEIC: {'pillow-heif' if core.HEIF_OK else 'not available'}")

    # ------------------------------------------------------------- lifecycle
    def paintEvent(self, ev):
        """Claim every pixel of the window for hit-testing.

        A layered window is hit-tested by its alpha, so a pixel with alpha 0
        belongs to whatever is behind the app. Only the photo, the bars and the
        thumbnail tiles get painted, which left the letterbox and the gaps
        between thumbnails see-through to the mouse: the wheel over the strip
        went to the browser underneath instead of scrolling it.

        Alpha 1 is invisible over any wallpaper and children still paint on top,
        so this costs nothing visually and the whole window is the app's.
        """
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 1))

    def closeEvent(self, ev):
        self.close_player()
        try:
            self.preview.shutdown()
        except Exception:
            pass
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("fullscreen", self.isFullScreen())
        self.settings.setValue("last_dir", os.path.dirname(self.current())
                               if self.current() else str(Path.home()))
        super().closeEvent(ev)

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            u = ev.mimeData().urls()[0].toLocalFile()
            if u and (Path(u).suffix.lower() in MEDIA_EXTS or os.path.isdir(u)):
                ev.acceptProposedAction()

    def dropEvent(self, ev):
        for u in ev.mimeData().urls():
            f = u.toLocalFile()
            if not f:
                continue
            target = resolve_target(f)
            if target:
                self.open(target)
                return

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.crop_overlay.setGeometry(self.view.rect())
        self._sync_side()
        self._sync_bars()

    def _sync_bars(self):
        """The floating chrome: preview strip rides the bottom edge, the control
        bar sits on top of it -- both over the photo, both 12px in from the
        edges. The photo area keeps full ownership of its whole rect.

        Deferred timers (singleShot → _enter_fullscreen) and restoreGeometry can
        both land after the last resizeEvent, so every state change that touches
        geometry re-syncs here explicitly too."""
        vw = self.view.width()
        nav_h = self.nav.height() or self.nav.sizeHint().height()
        strip_h = self.preview.height() or self.preview.sizeHint().height()
        # the strip sits just above the control bar
        self.nav.setGeometry(12, self.view.height() - nav_h - 12,
                             vw - 24, nav_h)
        self.preview.setGeometry(12, self.view.height() - nav_h - strip_h - 20,
                                 vw - 24, strip_h)
        self.nav.raise_()
        self.preview.raise_()


def first_media_in(folder: str) -> str | None:
    """The first media file in `folder`, in the order `_scan` groups them."""

    try:
        names = [n for n in os.listdir(folder)
                 if Path(n).suffix.lower() in MEDIA_EXTS]
    except OSError:
        return None
    if not names:
        return None
    names.sort(key=lambda n: (Path(n).suffix.lower() in VIDEO_EXTS,
                              _natural(Path(n).stem)))
    return os.path.join(folder, names[0])


def resolve_target(arg: str | None) -> str | None:
    """Turn a command-line or dropped path into a media file to open.

    A directory resolves to its first media file, so `picoSun.exe
    D:\\pics` opens that folder. A non-media file resolves to None and the
    window simply opens empty.
    """

    if not arg:
        return None
    if os.path.isdir(arg):
        return first_media_in(arg)
    if Path(arg).suffix.lower() in MEDIA_EXTS:
        return arg
    return None


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    # Every QMessageBox must be readable no matter what palette Qt inherits
    # (a translucent-glass app otherwise renders dialog text black-on-black).
    app.setStyleSheet(
        "QMessageBox{background:rgba(34,38,50,244);}"
        "QMessageBox QLabel{color:#eceef0;font-size:12px;}"
        "QMessageBox QPushButton{background:rgba(88,96,120,255);color:#eceef0;"
        "border:1px solid rgba(255,255,255,46);border-radius:6px;"
        "padding:5px 22px;}"
        "QMessageBox QPushButton:hover{background:rgba(64,70,92,255);}")
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "picoSun.picoSun.1")
    except Exception:
        pass

    # one non-flag argument, and it may be a file *or* a folder
    target = next((a for a in sys.argv[1:] if not a.startswith("-")), None)
    path = resolve_target(target)
    w = Viewer(path)
    try:
        w.setWindowIcon(app_icon())
    except Exception:
        pass
    w.show()
    try:
        from pv_glass import enable_acrylic
        enable_acrylic(int(w.winId()))
    except Exception:
        pass
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
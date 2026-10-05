"""Frameless window chrome: title strip, bottom nav bar, filmstrip, info panel."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from PIL import Image as _PILImage

from pv_core import camera_line as pv_core_clean
from pv_ui_common import human_size, pil_to_pixmap

Image_LANCZOS = _PILImage.LANCZOS

APP_NAME = "picoSun"

# both side columns are this wide, which keeps the play button centred
COL_W = 386

# Measured off the Windows-Photos reference screenshot:
#   bar background   (2,6,14)  -- essentially black, not Picasa's slate
#   controls         a glyph with a small text label UNDERNEATH it, no button
#                    box, sitting straight on the bar
#   whole bar        ~32px tall in a 1183px window (2.7% of the width)
# a modern control: a circular icon button, hover lifts it, no caption text --
# tooltips carry the name. One row, every control the same size, everything
# vertically centred: the old glyph+caption cells were the alignment trouble.
_ICON = "#e8e8ec"          # glyph colour on the resting bar
_ICON_HOVER = "#ffffff"
BAR_H = 52                 # one row of 34px circles, 9px breathing room

_UI_FONT = "Segoe UI"

_NAV_QSS = """
QPushButton{background:rgba(255,255,255,26);border:none;color:%(icon)s;
 font-size:15px;font-family:"%(font)s";border-radius:17px;}
QPushButton:hover{background:rgba(255,255,255,58);color:%(hover)s;}
QPushButton:pressed{background:rgba(255,255,255,84);}
QLabel{background:transparent;color:#a6a6ae;font-size:10px;
 font-family:"%(font)s";}
""" % {"icon": _ICON, "hover": _ICON_HOVER, "font": _UI_FONT}

# the slideshow disc stays Picasa's signature round filled control, brightened
_PLAY_QSS = """
QPushButton{background:rgba(255,255,255,120);border:none;color:#16181d;
 border-radius:22px;font-size:18px;font-family:"%s";}
QPushButton:hover{background:rgba(255,255,255,165);color:#000000;}
QPushButton:pressed{background:rgba(255,255,255,95);}
""" % _UI_FONT

# Title-bar style buttons: no box until hovered, like Windows itself.
_WIN_QSS = """
QPushButton{background:transparent;border:none;color:#eceef0;
 border-radius:4px;font-size:14px;font-family:"%s";}
QPushButton:hover{background:rgba(255,255,255,38);}
QPushButton:pressed{background:rgba(255,255,255,70);}
""" % _UI_FONT

# The close button is the one control that reads as destructive, so it gets the
# usual red hover -- otherwise "close" is indistinguishable from the rest.
_CLOSE_QSS = """
QPushButton{background:transparent;border:none;color:#2c2c30;
 border-radius:5px;font-size:15px;font-family:"%s";}
QPushButton:hover{background:#c42b1c;color:#ffffff;}
QPushButton:pressed{background:#a02418;color:#ffffff;}
""" % _UI_FONT


class Chrome(QWidget):
    """The title bar.

    This used to be a bare QLabel strip with the text on it, sitting *inside*
    the central widget -- which put the QMainWindow's own menu bar directly on
    top of it. Two things broke as a result: the strip had no window buttons,
    and dragging it did nothing, because the press never reached it. The menu
    bar had swallowed every click at the top of the window.

    So the title bar is now a real widget that OWNS the top strip: the app name
    on the left, minimise / maximise / close on the right, and the whole thing
    is the drag handle except where a button is. The menu bar is moved out of
    the QMainWindow and stacked directly underneath it, so nothing overlaps
    anything and the top of the window is the title bar, as it should be.
    """

    minClicked = Signal()
    maxClicked = Signal()
    closeClicked = Signal()
    exitClicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag = None
        self._origin = None
        self.setFixedHeight(32)
        self.setObjectName("titleBar")
        # A plain QWidget subclass does NOT paint a stylesheet background. Qt
        # only honours `background:` on it when WA_StyledBackground is set, so
        # without this the title bar had the right geometry and the right
        # buttons and painted nothing at all -- it read as "the title bar has
        # no buttons and nothing there is clickable".
        self.setAttribute(Qt.WA_StyledBackground, True)
        # the title bar background comes from paint_glass, not from here: a
        # stylesheet background paints on top of the glass tint
        self.setStyleSheet(
            f"QPushButton{{background:transparent;border:none;color:#eceef0;"
            f" font-size:14px;font-family:{_UI_FONT};}}"
            "QPushButton:hover{background:rgba(255,255,255,46);}"
            f"QPushButton#titleClose:hover{{background:#c42b1c;color:#ffffff;}}"
            f"QPushButton#titleExit:hover{{background:#c42b1c;color:#ffffff;}}")

        self.lbl = QLabel(APP_NAME, self)
        self.lbl.setStyleSheet(
            "color:#eceef0;background:transparent;font-size:12px;padding-left:12px;")

        self.btn_min = QPushButton("–", self)
        self.btn_max = QPushButton("□", self)
        self.btn_close = QPushButton("✕", self)
        # Permanent Exit at the top-right. It used to live only in the bottom
        # bar, which is hidden in fullscreen; the title bar is the place a user
        # looks for "get me out", so it lives here now.
        self.btn_exit = QPushButton("⎋", self)
        for b in (self.btn_min, self.btn_max, self.btn_close, self.btn_exit):
            b.setAttribute(Qt.WA_StyledBackground, True)
        self.btn_close.setObjectName("titleClose")
        self.btn_exit.setObjectName("titleExit")
        self.btn_exit.setToolTip("Exit picoSun  (Alt+F4)")
        self.btn_exit.setFixedSize(42, 30)
        self.btn_exit.setFocusPolicy(Qt.NoFocus)
        self.btn_exit.setCursor(Qt.ArrowCursor)
        self.btn_exit.clicked.connect(self.exitClicked)
        for b, sig, tip in (
                (self.btn_min, self.minClicked, "Minimise"),
                (self.btn_max, self.maxClicked, "Maximise / restore"),
                (self.btn_close, self.closeClicked, "Close  (Alt+F4)")):
            b.setToolTip(tip)
            b.setFixedSize(42, 30)
            b.setFocusPolicy(Qt.NoFocus)
            b.setCursor(Qt.ArrowCursor)
            b.clicked.connect(sig)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 2, 2, 2)
        row.setSpacing(0)
        row.addWidget(self.lbl, 1)
        row.addWidget(self.btn_exit)
        row.addWidget(self.btn_min)
        row.addWidget(self.btn_max)
        row.addWidget(self.btn_close)
        self.setLayout(row)

    # the title label is the drag handle; the buttons are not
    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton \
                and not self.window().isFullScreen():
            self._drag = ev.position().toPoint()
            self._origin = self.window().frameGeometry().topLeft()
            self.setCursor(Qt.ClosedHandCursor)
        ev.accept()

    def mouseMoveEvent(self, ev):
        if self._drag is not None and (ev.buttons() & Qt.LeftButton):
            delta = ev.position().toPoint() - self._drag
            self.window().move(self._origin + delta)
        ev.accept()

    def mouseReleaseEvent(self, ev):
        self._drag = None
        self.setCursor(Qt.ArrowCursor)

    def mouseDoubleClickEvent(self, ev):
        # double-clicking the empty part of the title bar toggles fullscreen,
        # but not when the double click was on one of the buttons
        if self.childAt(ev.position().toPoint()) is self.lbl:
            self.window().toggle_fullscreen()

    def set_caption(self, text: str):
        self.lbl.setText(text)

    def set_buttons_visible(self, on: bool):
        """Fullscreen has no title bar, so the buttons go with it -- except
        Exit, which must always be reachable from the top-right."""
        for b in (self.btn_min, self.btn_max, self.btn_close):
            b.setVisible(bool(on))
        self.btn_exit.setVisible(True)



    def paintEvent(self, ev):
        from pv_glass import paint_glass
        p = QPainter(self)
        # windowed bars: frosted but airy -- the wallpaper glows through
        paint_glass(self, p, scrim=QColor(16, 18, 24, 60), sheen=25)
        p.end()


class NavBar(QFrame):
    """Bottom control bar in the Windows-Photos style the reference shows: a
    glyph with a small caption underneath it, utilities on the left, the
    prev / play / next group in the centre, zoom on the right.

    Picasa's round translucent play disc is kept in the middle of that layout.
    Both side columns are pinned to the same width so the centre group really is
    centred, and that width shrinks on narrow windows so nothing ever overlaps.
    """

    prevClicked = Signal()
    nextClicked = Signal()
    filmstripToggled = Signal()
    slideshowToggled = Signal()
    fullscreenToggled = Signal()
    zoomFit = Signal()
    zoomActual = Signal()
    zoomIn = Signal()
    zoomOut = Signal()
    infoToggled = Signal()
    editToggled = Signal()
    openClicked = Signal()
    rotateClicked = Signal()
    # window management: the app is frameless, so the bar must supply these
    minClicked = Signal()
    maxClicked = Signal()
    closeClicked = Signal()
    exitClicked = Signal()

    # the centre group never needs more room than this
    MID_W = 210

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(BAR_H)
        # NOTE: a bare "background:..." in a parent's stylesheet cascades into
        # every child widget in Qt, which paints a box behind each button.
        # The bar's own background must be scoped to the bar by object name.
        self.setObjectName("navBar")
        # no background: here -- paint_glass draws the bar, and a stylesheet
        # background would paint over it (that is why the bar kept coming out
        # light gray no matter what the glass tint was)
        self.setStyleSheet(_NAV_QSS)

        self.lbl_name = QLabel("")
        self.lbl_name.setStyleSheet(
            f"color:#eceef0;background:transparent;font-size:11px;")
        self.lbl_meta = QLabel("")
        self.lbl_meta.setStyleSheet(
            f"color:#a6a6ae;background:transparent;font-size:10px;")
        self.lbl_zoom = QLabel("Fit")
        self.lbl_zoom.setAlignment(Qt.AlignCenter)
        # fixed width: the zoom text changes ("Fit" / "100%" / "" when no photo),
        # and a label that widens after _refit measured the row is what pushed
        # the last window button past the bar's right edge at ~900px.
        self.lbl_zoom.setFixedWidth(46)
        self.lbl_zoom.setStyleSheet(
            f"color:#6a6a72;background:transparent;font-size:10px;")

        # ---------------- left column: name on top, the utility cluster below
        self.btn_edit = self._labbtn("✎", "Edit", "Edit photo  (Ctrl+E)",
                                     self.editToggled, 34, 34)
        self.btn_info = self._labbtn("ⓘ", "Info", "Photo info  (Ctrl+I)",
                                     self.infoToggled, 34, 34)
        self.btn_rotate = self._labbtn("⟳", "Rotate", "Rotate  (R)",
                                       self.rotateClicked, 34, 34)

        utilrow = QHBoxLayout()
        utilrow.setSpacing(6)
        utilrow.setContentsMargins(0, 0, 0, 0)
        utilrow.setAlignment(Qt.AlignVCenter)
        for b in (self.btn_edit, self.btn_info, self.btn_rotate):
            utilrow.addWidget(b, 0, Qt.AlignVCenter)

        # The filename and the resolution share ONE line. Stacking them, as this
        # bar used to, left the glyph+caption cells squeezed so the caption
        # overlapped the glyph -- the reference keeps the caption legible, so
        # the two labels go side by side instead.
        left = QHBoxLayout()
        left.setSpacing(10)
        left.setContentsMargins(0, 0, 0, 0)
        left.addWidget(self.lbl_name, 0, Qt.AlignVCenter)
        left.addWidget(self.lbl_meta, 0, Qt.AlignVCenter)
        left.addSpacing(10)
        left.addLayout(utilrow)
        left.addStretch(1)
        self.left_col = QWidget()
        self.left_col.setLayout(left)

        # ---------------- centre: chevrons around a big round play button
        mid = QHBoxLayout()
        mid.setSpacing(8)
        mid.setContentsMargins(0, 0, 0, 0)
        mid.addStretch(1)
        mid.addWidget(self._labbtn("❮", "Prev", "Previous photo  (←)",
                                   self.prevClicked, 34, 34), 0, Qt.AlignVCenter)
        self.play_btn = self._labbtn("▶", "Slideshow", "Slideshow  (F5)",
                                     self.slideshowToggled, 44, 44)
        self.play_btn.button.setStyleSheet(_PLAY_QSS)
        mid.addWidget(self.play_btn, 0, Qt.AlignVCenter)
        mid.addWidget(self._labbtn("❯", "Next", "Next photo  (→)",
                                   self.nextClicked, 34, 34), 0, Qt.AlignVCenter)
        mid.addStretch(1)

        # ---------------- right column: the zoom cluster, pushed right
        self.btn_zoom_in = self._labbtn("+", "Zoom in", "Zoom in",
                                        self.zoomIn, 34, 34)
        self.btn_zoom_out = self._labbtn("−", "Zoom out", "Zoom out",
                                         self.zoomOut, 34, 34)
        self.btn_strip = self._labbtn("▤", "Strip", "Preview strip  (Ctrl+T)",
                                      self.filmstripToggled, 34, 34)
        self.btn_full = self._labbtn("⛶", "Full", "Fullscreen  (F)",
                                     self.fullscreenToggled, 34, 34)
        self.btn_open = self._labbtn("⊞", "Open", "Open photo  (Ctrl+O)",
                                     self.openClicked, 34, 34)

        right = QHBoxLayout()
        right.setSpacing(6)
        right.setContentsMargins(0, 0, 0, 0)
        right.addStretch(1)
        for b in (self.btn_zoom_out, self.lbl_zoom, self.btn_zoom_in,
                  self.btn_strip, self.btn_full, self.btn_open):
            right.addWidget(b, 0, Qt.AlignVCenter)

        # The window is frameless, so there is no title bar to click. These are
        # the controls the user would otherwise expect: in a normal window they
        # minimise / maximise / close it, and in fullscreen the whole cluster is
        # swapped for a single Exit, because there is nothing to minimise.
        self.btn_exit = self._winbtn("✕", "Exit picoSun  (Alt+F4)",
                                     self.exitClicked)
        self.btn_min = self._winbtn("–", "Minimise", self.minClicked)
        self.btn_max = self._winbtn("□", "Maximise", self.maxClicked)
        self.btn_close = self._winbtn("✕", "Close picoSun  (Alt+F4)",
                                      self.closeClicked)
        self.btn_close.setStyleSheet(_CLOSE_QSS)

        self.winrow = QHBoxLayout()
        self.winrow.setSpacing(2)
        self.winrow.setContentsMargins(0, 0, 0, 0)
        for b in (self.btn_min, self.btn_max, self.btn_close):
            self.winrow.addWidget(b)
        self.win_col = QWidget()
        self.win_col.setLayout(self.winrow)
        # Without a hard width the cluster was squeezed by ~6px per button and
        # the three drew on top of each other. It is all-or-nothing anyway, so
        # pin it and let _refit decide whether it gets shown at all.
        self.win_col.setFixedWidth(self.COST_WINBTN * 3 + self.winrow.spacing() * 2)

        right.addWidget(self.btn_exit)
        right.addWidget(self.win_col)
        self.right_col = QWidget()
        self.right_col.setLayout(right)

        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(10, 3, 10, 3)
        self._lay.setSpacing(8)
        self._lay.addWidget(self.left_col)
        self._lay.addLayout(mid, 1)
        self._lay.addWidget(self.right_col)

        self._fullscreen = False
        self.setFixedHeight(BAR_H)
        self._refit()

    # ------------------------------------------------------------------ layout
    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._refit()

    def set_mode(self, fullscreen: bool):
        """Fullscreen has no window to minimise, so the right-hand corner swaps
        between the three window buttons and a single Exit.

        set_mode records the mode and lets _refit do the drawing, so the two can
        never disagree -- an earlier version had _refit forcing the Exit on at
        narrow widths with nothing ever turning it off again.
        """
        self._fullscreen = bool(fullscreen)
        self._refit()

    # Measured widths, not guesses: a caption cell is glyph + padding, a window
    # button is glyph only. Guessing is what made this bar overlap itself.
    COST_CELL = 42
    COST_WINBTN = 30

    def _win_room(self) -> bool:
        """Is the right-hand column wide enough for the full set of controls?"""
        gap = self.right_col.layout().spacing() or 2
        need = (self.btn_zoom_out.sizeHint().width()
                + self.lbl_zoom.sizeHint().width()
                + self.btn_zoom_in.sizeHint().width()
                + self.btn_full.sizeHint().width()
                + self.win_col.sizeHint().width()
                + self.btn_open.sizeHint().width()
                + self.btn_strip.sizeHint().width()
                + gap * 6 + 14)
        chrome = (2 * 10 + 2 * self._lay.spacing() + self.MID_W)
        col = max(120, min(COL_W, (self.width() - chrome) // 2))
        return need <= col

    def _refit(self):
        """Equal side columns = a centred play button; both shrink so the bar
        survives a narrow window instead of overlapping itself."""
        w = self.width()
        chrome = (2 * 10                       # outer margins
                  + 2 * self._lay.spacing()   # column gaps
                  + self.MID_W)
        col = max(120, min(COL_W, (w - chrome) // 2))
        self.left_col.setFixedWidth(col)
        self.right_col.setFixedWidth(col)

        # ---- left column: drop optional controls until the row fits; every
        # button is a fixed 34px circle now, so 40px per control + label is the
        # arithmetic (measured sizeHint cannot see hidden siblings).
        left_budget = col - 10                 # the addSpacing(10) before utilrow
        self.lbl_meta.setVisible(left_budget >= 260)
        self.btn_edit.setVisible(left_budget >= 160)
        self.btn_info.setVisible(left_budget >= 210)
        self.btn_rotate.setVisible(left_budget >= 280)

        # ---- right column: add the optional controls in order of usefulness and
        # stop at the first one that does not fit. Measuring the whole row and
        # dropping from the end is what makes overlap impossible here; a
        # per-button cutoff cannot know what else is currently shown, which is
        # why the bar collided at every width when the window buttons landed.
        gap = self.right_col.layout().spacing() or 2
        # Measured, not assumed. Hand-kept width constants ran ~12px optimistic
        # and the row still overlapped; Qt reports what a widget really needs.
        pad = 14                 # rounding between sizeHint and the layout
        base = [self.btn_zoom_out.sizeHint().width(),
                self.lbl_zoom.sizeHint().width(),
                self.btn_zoom_in.sizeHint().width(),
                self.btn_full.sizeHint().width()]

        optional = []
        if self._fullscreen:
            optional.append((self.btn_exit, self.btn_exit.sizeHint().width()))
        elif self._win_room():
            optional.append((self.win_col, self.win_col.sizeHint().width()))
        else:
            # no room for three window buttons: Exit is the one that must live,
            # because it is the only way out of a frameless window
            optional.append((self.btn_exit, self.btn_exit.sizeHint().width()))
        optional.append((self.btn_open, self.btn_open.sizeHint().width()))
        optional.append((self.btn_strip, self.btn_strip.sizeHint().width()))

        kept = []
        for widget, cost in optional:
            trial = base + [c for _, c in kept] + [cost]
            if sum(trial) + gap * (len(trial) - 1) + pad <= col:
                kept.append((widget, cost))
            else:
                break

        shown = {id(wd) for wd, _ in kept}
        self.win_col.setVisible(id(self.win_col) in shown)
        self.btn_exit.setVisible(id(self.btn_exit) in shown)
        self.btn_open.setVisible(id(self.btn_open) in shown)
        self.btn_strip.setVisible(id(self.btn_strip) in shown)

        # The sizeHint arithmetic above runs a few px optimistic, which at some
        # widths pushed the last window button past the bar's right edge. Measure
        # what the row really needs and drop the least essential control until
        # it fits, ending on Exit (the only way out of a frameless window).
        rlay = self.right_col.layout()
        for _ in range(4):
            rlay.activate()
            if rlay.minimumSize().width() <= col:
                break
            for wd in (self.btn_strip, self.btn_open, self.win_col):
                if wd.isVisible():
                    wd.setVisible(False)
                    if wd is self.win_col:
                        self.btn_exit.setVisible(True)
                    break
            else:
                break
        self.right_col.setFixedWidth(col)

    def _winbtn(self, glyph, tip, sig, w=30, h=26):
        """A caption-less square button, the way a title bar draws them.

        The media controls above carry a caption because they are a row of
        equals; these three are window management, so they read better -- and
        cost 96px less -- without one.
        """
        b = QPushButton(glyph)
        b.setToolTip(tip)
        b.setFixedSize(w, h)
        b.setCursor(Qt.PointingHandCursor)
        b.setFocusPolicy(Qt.NoFocus)
        b.setStyleSheet(_WIN_QSS)
        b.clicked.connect(sig)
        return b

    def _labbtn(self, glyph, caption, tip, sig, w=34, h=34):
        """A circular icon button. `caption` is kept in the signature (callers
        and tests read `.caption.text()`), but it lives only in the tooltip --
        the modern bar has no text under its icons."""
        b = QPushButton(glyph)
        b.setToolTip(tip)
        b.setFixedSize(w, h)
        b.setCursor(Qt.PointingHandCursor)
        b.setFocusPolicy(Qt.NoFocus)
        b.setStyleSheet(_NAV_QSS)
        b.clicked.connect(sig)
        # a flat wrapper exposing the old .button/.caption API so callers and
        # tests keep working; the caption is the tooltip's job now
        cell = QWidget()
        cell.setFixedSize(w, h)
        lay = QVBoxLayout(cell)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(b)
        cell.button = b
        cell.caption = QLabel(caption)
        return cell

    def _btn(self, text, tip, sig, w=28, h=26):
        b = QPushButton(text)
        b.setToolTip(tip)
        b.setFixedSize(w, h)
        b.setCursor(Qt.PointingHandCursor)
        b.setFocusPolicy(Qt.NoFocus)
        b.setStyleSheet(_NAV_QSS)
        b.clicked.connect(sig)
        return b

    # ------------------------------------------------------------------- state
    def set_playing(self, on: bool):
        self.play_btn.button.setText("❚❚" if on else "▶")
        self.play_btn.button.setToolTip(
            "Stop slideshow  (F5)" if on else "Slideshow  (F5)")

    def set_photo(self, path: str, index: int, total: int, meta: str, zoom: str,
                  edited: bool):
        if not path:
            self.lbl_name.setText(APP_NAME)
            self.lbl_meta.setText("")
            self.lbl_zoom.setText("")
            return
        star = "  •" if edited else ""
        cnt = f"   {index + 1} / {total}" if total > 1 else ""
        self.lbl_name.setText(f"{Path(path).name}{star}{cnt}")
        self.lbl_meta.setText(meta)
        self.lbl_zoom.setText(zoom)


    def paintEvent(self, ev):
        from pv_glass import paint_glass
        p = QPainter(self)
        # the control bar is the frosted pane: airy, wallpaper glows through
        paint_glass(self, p, scrim=QColor(16, 18, 24, 60), sheen=25)
        p.end()


class Filmstrip(QFrame):
    picked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(84)
        self.setStyleSheet(
            "background:rgba(250,250,252,190);border-top:1px solid rgba(0,0,0,14);")
        self.list = QListWidget(self)
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setFlow(QListWidget.LeftToRight)
        self.list.setWrapping(False)
        self.list.setFixedHeight(80)
        self.list.setIconSize(QSize(64, 54))
        self.list.setSpacing(2)
        self.list.setStyleSheet(
            "QListWidget{background:transparent;border:none;}"
            "QListWidget::item{border:2px solid transparent;}"
            "QListWidget::item:hover{border:2px solid #6a6a6a;}"
            "QListWidget::item:selected{border:2px solid #4a90d9;}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.addWidget(self.list)
        self.list.itemClicked.connect(lambda it: self.picked.emit(it.data(Qt.UserRole)))

    def load(self, paths, current, decode_fn):
        self.list.clear()
        for p in paths:
            pm = QPixmap()
            try:
                im, _ = decode_fn(p)
                if im is not None:
                    im.thumbnail((64, 54), Image_LANCZOS)
                    pm = pil_to_pixmap(im)
            except Exception:
                pass
            it = QListWidgetItem(pm, "")
            it.setData(Qt.UserRole, p)
            it.setToolTip(Path(p).name)
            if os.path.normcase(p) == os.path.normcase(current):
                it.setSelected(True)
            self.list.addItem(it)
        self.reveal(current)

    def reveal(self, path: str):
        if not path:
            return
        for i in range(self.list.count()):
            it = self.list.item(i)
            if os.path.normcase(it.data(Qt.UserRole)) == os.path.normcase(path):
                self.list.setCurrentItem(it)
                self.list.scrollToItem(it, QListWidget.EnsureVisible)
                return


class InfoPanel(QFrame):
    """Picasa-style photo details, right side."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(238)
        self.setStyleSheet(
            "background:transparent;")
        self.box = QLabel("")
        self.box.setWordWrap(True)
        self.box.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.box.setStyleSheet("color:#eceef0;background:transparent;padding:10px;"
                               "font-size:11px;")
        self.box.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.box)

    def show_info(self, path: str, meta: dict, size, bytes_: str, when: str, extra: str):
        if not path:
            self.box.setText("")
            return
        w, h = size
        rows = [("File", Path(path).name),
                ("Folder", str(Path(path).parent)),
                ("Type", "RAW" if meta.get("is_raw") else
                 (meta.get("format") or Path(path).suffix.lstrip(".").upper())),
                ("Size", f"{w} × {h} px"),
                ("File size", bytes_),
                ("Modified", when)]
        cam = pv_core_clean(meta)
        if cam:
            rows.append(("Camera", cam))
        for k, lab in (("iso", "ISO"), ("shutter", "Shutter"), ("fnum", "Aperture"),
                       ("focal", "Focal"), ("lens", "Lens"), ("stamp", "Taken")):
            if meta.get(k):
                rows.append((lab, str(meta[k])))
        if extra:
            rows.append(("Adjustments", extra))
        html = f"<div style='margin-bottom:10px'><b>{Path(path).name}</b></div>"
        for k, v in rows:
            html += (f"<div style='color:#787878'>{k}</div>"
                     f"<div style='margin-bottom:6px'>{v}</div>")
        self.box.setText(html)



    def paintEvent(self, ev):
        from pv_glass import paint_glass
        p = QPainter(self)
        # info panel: same airy frost as the bars
        paint_glass(self, p, scrim=QColor(16, 18, 24, 60), sheen=25)
        p.end()

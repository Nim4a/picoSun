"""
The image surface: zoom, pan, transparent letterbox, and a soft drop shadow behind
the picture (that is what makes the background read as "transparent" in
picoSun).
"""

from __future__ import annotations

import os
import time

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPixmap,
    QTransform,
)
from PySide6.QtWidgets import QWidget

MIN_SCALE, MAX_SCALE = 0.01, 32.0
ZOOM_STEPS = [0.02, 0.05, 0.08, 0.1, 0.15, 0.2, 0.25, 1 / 3, 0.4, 0.5, 0.67,
              0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0,
              10.0, 12.0, 16.0, 20.0, 24.0, 32.0]


class PhotoView(QWidget):
    zoomChanged = Signal()
    wheelStepped = Signal(int)     # +1 next photo, -1 previous, from the letterbox
    clicked = Signal()
    doubleClicked = Signal()
    sizeChanged = Signal()
    cursorMoved = Signal(float, float)      # image-space coords under cursor
    contextRequested = Signal(QPoint)      # position in widget coords

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pm: QPixmap | None = None
        self._scale = 1.0
        self._fit = True
        self._offset = QPointF(0.0, 0.0)
        self._drag_from: QPoint | None = None
        self._dragged = False
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.timeout.connect(self._click_fire)
        self._pending_pos: QPoint | None = None
        self.shadow = True
        self.chrome = True                    # letterbox + shadow (off = pure transparent)
        self.strip_hover = False              # set while the pointer is on the strip
        self._mut_id = 0
        self._prev_pm: QPixmap | None = None   # outgoing photo for the crossfade
        self._prev_rect: QRectF | None = None  # its on-screen rect
        self._fade = 1.0                       # incoming photo's opacity
        self._fade_anim = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(64, 64)
        # NOTE: no WA_TranslucentBackground -- same Win32 layered-window
        # reason as the main window (alpha composites against black).
        # The view paints nothing outside the photo; the window's opaque
        # dark backdrop shows there instead.
        self.setCursor(Qt.OpenHandCursor)
        self._img_id = 0

    # ------------------------------------------------------------------ state
    def set_pixmap(self, pm: QPixmap | None, img_id: int = 0, fade: bool = True):
        # Crossfade ONLY for a genuinely new photo. The viewer passes
        # fade=False when it is SHARPENING the selection already on screen
        # (thumbnail -> full render): starting a second fade there was the
        # jump -- the half-faded previous photo vanished in one frame.
        new_key = pm.cacheKey() if pm is not None and not pm.isNull() else 0
        old_key = self._pm.cacheKey() if self._pm is not None and not self._pm.isNull() else 0
        swapping = bool(new_key) and bool(old_key) and new_key != old_key

        if not fade:
            # sharpening the shown photo: if a fade is running it keeps its
            # underlay and phase and only the target upgrades; otherwise the
            # swap is instant -- no new fade, nothing jumps
            if self._fade_anim is None:
                self._prev_pm = None
                self._prev_rect = None
                self._fade = 1.0
        elif not swapping:
            # same photo re-set (a rebuild) or an empty view: no transition
            self._prev_pm = None
            self._prev_rect = None
            self._fade = 1.0
        elif self._fade_anim is not None:
            # reversing mid-fade: what is on screen is a HALF-BLENDED pair.
            # Starting a fresh fade from either photo alone makes that blend
            # vanish in one frame -- the "ghost jumps away" the user saw.
            # Snapshot the actual composite and fade from THAT with a FRESH
            # 180ms animation. The old animation must be stopped first: it
            # keeps its own timeline, so keeping it snaps _fade from the
            # reset 0.0 straight to the old timeline's ~0.9 on the next tick
            # -- the "still fading then suddenly jumps" on the way back.
            old_anim, self._fade_anim = self._fade_anim, None
            try:
                old_anim.valueChanged.disconnect(self._on_fade)
            except Exception:
                pass
            try:
                old_anim.finished.disconnect(self._end_fade)
            except Exception:
                pass
            old_anim.stop()
            old_anim.deleteLater()
            self._prev_pm = self.grab()
            self._prev_rect = QRectF(self.rect())
            self._fade = 0.0
        else:
            self._prev_pm = self._pm
            self._prev_rect = self.target_rect()
            self._fade = 0.0
        self._pm = pm
        self._img_id = img_id
        if self._fit:
            self.fit()
        else:
            self._clamp()
        if swapping and self._fade_anim is None:
            self._start_fade()
        self._cache_fade_pixmap()   # incoming photo pre-scaled for fade frames
        self.update()
        self.sizeChanged.emit()

    def _start_fade(self):
        if self._fade_anim is not None:
            self._fade_anim.stop()
        # pre-scale BOTH photos ONCE to their on-screen size: the paint then
        # blits two ready pixmaps every frame. Scaling either full-res photo
        # per frame with SmoothPixmapTransform cost ~15ms/frame -- the stutter
        # at the tail of the fade (where both layers draw) came from the
        # incoming one, the outgoing was already cached.
        if self._prev_pm is not None and self._prev_rect is not None \
                and self._prev_rect.width() > 0:
            scaled = self._prev_pm.scaled(
                int(self._prev_rect.width()), int(self._prev_rect.height()),
                Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            if not scaled.isNull():
                self._prev_pm = scaled
        self._fade_pm = None                # set after fit() in set_pixmap
        from PySide6.QtCore import QVariantAnimation
        anim = QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(180)
        anim.valueChanged.connect(self._on_fade)
        anim.finished.connect(self._end_fade)
        anim.start()
        self._fade_anim = anim

    def _cache_fade_pixmap(self):
        """The incoming photo at its display size, for cheap fade frames."""
        self._fade_pm = None
        r = self.target_rect()
        if self._pm is not None and not self._pm.isNull() \
                and self._fade < 1.0 and r.width() > 1:
            pm = self._pm.scaled(int(r.width()), int(r.height()),
                                 Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            if not pm.isNull():
                self._fade_pm = pm

    def _on_fade(self, v):
        self._fade = float(v)
        self.update()

    def _end_fade(self):
        self._fade = 1.0
        self._prev_pm = None
        self._fade_anim = None
        self.update()

    def pixmap_size(self) -> QSize:
        return self._pm.size() if self._pm else QSize()

    @property
    def has_image(self) -> bool:
        return self._pm is not None and not self._pm.isNull()

    @property
    def scale(self) -> float:
        return self._scale

    @property
    def is_fit(self) -> bool:
        return self._fit

    def fit_scale(self) -> float:
        sz = self.pixmap_size()
        if sz.isEmpty() or self.width() <= 0 or self.height() <= 0:
            return 1.0
        m = 0 if self.chrome else 0
        return max(0.001, min((self.width() - m) / sz.width(), (self.height() - m) / sz.height()))

    def label(self) -> str:
        if self._fit and abs(self.fit_scale() - self._scale) < 1e-6:
            return "Fit"
        return f"{self._scale * 100:.0f}%"

    # ------------------------------------------------------------- geometry
    def target_rect(self) -> QRectF:
        sz = self.pixmap_size()
        if sz.isEmpty():
            return QRectF()
        return QRectF(self._offset.x(), self._offset.y(),
                      sz.width() * self._scale, sz.height() * self._scale)

    def _clamp(self):
        sz = self.pixmap_size()
        if sz.isEmpty():
            self._offset = QPointF(0, 0)
            return
        dw, dh = sz.width() * self._scale, sz.height() * self._scale
        ow, oh = self.width(), self.height()
        self._offset.setX((ow - dw) / 2.0 if dw <= ow
                          else min(0.0, max(ow - dw, self._offset.x())))
        self._offset.setY((oh - dh) / 2.0 if dh <= oh
                          else min(0.0, max(oh - dh, self._offset.y())))

    # ----------------------------------------------------------------- zoom
    def fit(self):
        self._fit = True
        self._scale = self.fit_scale()
        self._clamp()
        self.zoomChanged.emit()
        self.update()

    def actual_size(self):
        self._fit = False
        self._scale = 1.0
        self._clamp()
        self.zoomChanged.emit()
        self.update()

    def set_scale(self, value: float, anchor: QPointF | None = None):
        self._mut_id += 1        # user zoom: the settle must not stomp it
        value = max(MIN_SCALE, min(MAX_SCALE, value))
        self._fit = False
        anchor = anchor or QPointF(self.width() / 2.0, self.height() / 2.0)
        before = self.target_rect()
        ix = (anchor.x() - before.x()) / max(self._scale, 1e-9)
        iy = (anchor.y() - before.y()) / max(self._scale, 1e-9)
        self._scale = value
        self._offset = QPointF(anchor.x() - ix * value, anchor.y() - iy * value)
        self._clamp()
        self.zoomChanged.emit()
        self.update()

    def step_zoom(self, direction: int, anchor: QPointF | None = None):
        cur = self._scale
        if direction > 0:
            nxt = [s for s in ZOOM_STEPS if s > cur * 1.002]
            target = nxt[0] if nxt else MAX_SCALE
        else:
            prv = [s for s in ZOOM_STEPS if s < cur * 0.998]
            target = prv[-1] if prv else MIN_SCALE
        self.set_scale(target, anchor)

    def zoom_by(self, factor: float, anchor: QPointF | None = None):
        self.set_scale(self._scale * factor, anchor)

    def nudge(self, dx: float, dy: float):
        self._mut_id += 1        # user pan: same guard
        self._offset += QPointF(dx, dy)
        self._clamp()
        self.update()

    # --------------------------------------------------------------- painting
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        # the photo floats on nothing: no canvas fill, the desktop shows
        # straight through around it (empty state included)
        if self._pm is None or self._pm.isNull():
            p.setPen(QColor(226, 229, 236))
            f = p.font()
            f.setPointSize(max(11, f.pointSize() + 3))
            p.setFont(f)
            p.drawText(self.rect(), Qt.AlignCenter,
                       "No image  —  drop a photo here  ·  Ctrl+O")
            return
        if self._prev_pm is not None and self._fade < 1.0:
            # crossfade, jump-free: the NEW photo draws full-strength first;
            # the OLD one sits ON TOP fading OUT (opacity 1-fade). Fading the
            # old photo out above means nothing is ever yanked: where the two
            # rects differ (portrait vs landscape fit), the leftover sliver of
            # the old photo dissolves instead of vanishing in one frame.
            r = self.target_rect()
            src = self._fade_pm if self._fade_pm is not None else self._pm
            p.drawPixmap(r, src, QRectF(src.rect()))
            p.setOpacity(1.0 - self._fade)
            p.drawPixmap(self._prev_rect, self._prev_pm,
                         QRectF(self._prev_pm.rect()))
            p.setOpacity(1.0)
            if self.strip_hover:
                band = QRectF(0, self.height() - 26, self.width(), 26)
                grad = QLinearGradient(band.topLeft(), band.bottomLeft())
                grad.setColorAt(0.0, QColor(90, 140, 200, 0))
                grad.setColorAt(1.0, QColor(90, 140, 200, 90))
                p.fillRect(band, grad)
            return
        r = self.target_rect()
        p.drawPixmap(r, self._pm, QRectF(self._pm.rect()))
        if self.strip_hover:
            # the pointer is on the preview strip: a soft glow along the seam so the
            # strip reads as the live control it is right now
            band = QRectF(0, self.height() - 26, self.width(), 26)
            grad = QLinearGradient(band.topLeft(), band.bottomLeft())
            grad.setColorAt(0.0, QColor(90, 140, 200, 0))
            grad.setColorAt(1.0, QColor(90, 140, 200, 90))
            p.fillRect(band, grad)
        if self.chrome:
            p.setPen(QColor(0, 0, 0, 120))
            p.drawRect(r.adjusted(0, 0, -1, -1))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self._fit:
            self._scale = self.fit_scale()
        self._clamp()
        self.zoomChanged.emit()

    # ------------------------------------------------------------------ input
    def wheelEvent(self, ev):
        d = ev.angleDelta().y() or ev.angleDelta().x()
        if d == 0:
            return
        if self._over_photo(ev.position()):
            # on the picture: zoom, keeping the pixel under the pointer still
            self.step_zoom(1 if d > 0 else -1, ev.position())
        else:
            # on the empty letterbox around it: walk through the folder
            self.wheelStepped.emit(1 if d < 0 else -1)
        ev.accept()

    def _over_photo(self, pos) -> bool:
        return self.has_image and self.target_rect().contains(QPointF(pos))

    def mousePressEvent(self, ev):
        if ev.button() in (Qt.LeftButton, Qt.MiddleButton):
            p = ev.position().toPoint()
            self._drag_from = p
            self._pending_pos = p
            self._dragged = False
            self._click_timer.start(280)
            self.setCursor(Qt.ClosedHandCursor)
            ev.accept()

    def mouseMoveEvent(self, ev):
        if self._drag_from is not None and (ev.buttons() & (Qt.LeftButton | Qt.MiddleButton)):
            p = ev.position().toPoint()
            d = p - self._drag_from
            if d.manhattanLength() > 3:
                self._dragged = True
                self._click_timer.stop()
                self.nudge(d.x(), d.y())
            self._drag_from = p
            ev.accept()
            return
        r = self.target_rect()
        if not r.isEmpty() and r.contains(ev.position()):
            self.cursorMoved.emit((ev.position().x() - r.x()) / max(self._scale, 1e-9),
                                  (ev.position().y() - r.y()) / max(self._scale, 1e-9))

    def mouseReleaseEvent(self, ev):
        self.setCursor(Qt.OpenHandCursor)
        self._drag_from = None
        self._dragged = False
        ev.accept()

    def mouseDoubleClickEvent(self, ev):
        self._click_timer.stop()
        self.doubleClicked.emit()
        ev.accept()

    def _click_fire(self):
        self.clicked.emit()

    def contextMenuEvent(self, ev):
        self.contextRequested.emit(ev.globalPos())
        ev.accept()

    def keyPressEvent(self, ev):
        step = 70
        key = ev.key()
        if key == Qt.Key_Left:
            self.nudge(step, 0)
        elif key == Qt.Key_Right:
            self.nudge(-step, 0)
        elif key == Qt.Key_Up:
            self.nudge(0, step)
        elif key == Qt.Key_Down:
            self.nudge(0, -step)
        elif key == Qt.Key_Escape:
            self.fit()
        else:
            super().keyPressEvent(ev)
            return
        ev.accept()
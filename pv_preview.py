"""Bottom preview strip: thumbnails of every photo *and* video in the folder.

Hovering the strip makes it scroll with the wheel (and it follows the currently
shown item).  Video thumbnails are real frames grabbed with ffmpeg, extracted off
the GUI thread so a large folder never blocks the window.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QSizePolicy, QStyledItemDelegate,
                               QStyle, QWidget)

import pv_core as core
from pv_ui_common import pil_to_pixmap

# Video support removed (photos only). MEDIA_EXTS covers just stills, so
# only photos enter the folder scan, the strip, and the wheel.
VIDEO_EXTS: set[str] = set()
MEDIA_EXTS = core.IMAGE_EXTS

# Picasa measurements: strip ~50px tall, tiles 30x49 on a 31px pitch with a
# 1px black gutter, thin blue selection frame. Scrollbar hidden -- the strip
# glides to the current tile instead.
THUMB_W, THUMB_H = 30, 44          # icon box; delegate paints cover below


# --------------------------------------------------------------------- loaders

def image_thumbnail(path: str, box: int = 260) -> QPixmap | None:
    """Cheap thumbnail for the strip — never the full-res master.

    master_for() decodes the WHOLE photo (60MP RAW, huge JPEG) and arms the
    master-LRU with it; a big folder then decodes every photo at full
    resolution, which is why a large folder floods. Thumbnails only need a
    small box, so decode small directly (PIL draft rescues JPEG to ~1/8
    scale, our RAW/EXR path needs the full file but runs on the worker).
    """
    ext = Path(path).suffix.lower()
    try:
        if ext in core.RAW_EXTS or ext == ".exr":
            im, _ = core.master_for(path)
            if im is None:
                return None
            im = im.copy()
            im.thumbnail((box, box))
            return pil_to_pixmap(im)
        from PIL import Image, ImageOps
        with Image.open(path) as im:
            try:
                im.draft("RGB", (box * 2, box * 2))   # JPEG partial decode
            except Exception:
                pass                                   # non-JPEG: full small read
            im.load()
            try:
                im = ImageOps.exif_transpose(im)
            except Exception:
                pass
            im = im.convert("RGB")
            im.thumbnail((box, box))
            return pil_to_pixmap(im)
    except Exception:
        return None


def placeholder(path: str) -> QPixmap:
    """Tile for a file we could not read: ext badge on a dark plate."""
    pm = QPixmap(THUMB_W * 2, THUMB_H * 2)
    pm.fill(QColor(38, 38, 40))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    ext = Path(path).suffix.lstrip(".").upper()[:5] or "?"
    f = QFont()
    f.setPointSize(11)
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor(150, 150, 155))
    p.drawText(pm.rect(), Qt.AlignCenter, ext)
    p.setPen(QColor(70, 70, 74))
    p.drawRect(pm.rect().adjusted(0, 0, -1, -1))
    p.end()
    return pm


class _Signals(QObject):
    done = Signal(str, object)          # path, QPixmap


class _Job(QRunnable):
    """Thumbnail extraction on a worker thread."""

    def __init__(self, sig: _Signals, path: str):
        super().__init__()
        self.sig, self.path = sig, path

    def run(self):
        # the strip can be closed (or a new folder loaded) while this worker is
        # still decoding; the signal object then dies under us and emitting
        # raises RuntimeError.  That is a normal shutdown, not a failure.
        try:
            pm = image_thumbnail(self.path) or placeholder(self.path)
            self.sig.done.emit(self.path, pm)
        except RuntimeError:
            pass                      # the strip went away — nothing to do
        except Exception:
            try:
                self.sig.done.emit(self.path, placeholder(self.path))
            except RuntimeError:
                pass


# ---------------------------------------------------------------------- widget

class _StripList(QListWidget):
    """Wheel-over-strip steps through the folder instead of zooming the photo.

    The user asked for this explicitly: with the pointer resting on the bottom
    bar, one wheel notch should move to the next/previous file, not scroll the
    strip sideways. Scrolling sideways is what the selection follow is for, so
    the strip now glides to whichever tile the wheel landed on.
    """

    hovered = Signal(bool)
    stepped = Signal(int)        # +1 next file, -1 previous file

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFlow(QListWidget.LeftToRight)
        self.setWrapping(False)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setFrameShape(QListWidget.NoFrame)
        self._hover = False
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.timeout.connect(self._scroll_idle)
        self._velocity = 0.0
        # optional callable: the app sets this to report whether a photo is
        # still loading. The app owns the pacing; the strip only follows.
        self.busy = None
        # the strip glides to the current tile instead of jumping to it
        self._glide_to = 0
        self._glide = QTimer(self)
        self._glide.setInterval(16)
        self._glide.timeout.connect(self._glide_tick)
        self.setMouseTracking(True)
        # NOTE: no WA_TranslucentBackground -- the strip is opaque near-black
        # by design (Picasa ticker); translucency only washed it gray.
        self.setIconSize(QSize(THUMB_W, THUMB_H))
        self.setGridSize(QSize(31, 49))
        self.setUniformItemSizes(True)
        self.setSpacing(0)
        self.setItemDelegate(TileDelegate(self))

    # ------------------------------------------------------------------ hover
    def enterEvent(self, ev):
        self._hover = True
        self._velocity = 0.0
        self.hovered.emit(True)
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._hover = False
        self._velocity = 0.0
        self.hovered.emit(False)
        super().leaveEvent(ev)

    # ------------------------------------------------------------------- wheel
    def wheelEvent(self, ev):
        if not self._hover:
            ev.ignore()
            return
        delta = ev.angleDelta().y() or ev.angleDelta().x()
        if not delta:
            return
        ev.accept()
        # The app owns the pacing (see Viewer._wheel_step): a real photo blocks
        # the UI thread for a few hundred ms, and stepping again during that
        # window is what made the strip feel like it was spinning. The strip
        # only forwards the notch and follows the current tile.
        self.stepped.emit(1 if delta > 0 else -1)

    def _scroll_idle(self):
        bar = self.horizontalScrollBar()
        if abs(self._velocity) < 1:
            self._velocity = 0.0
            return
        before = bar.value()
        bar.setValue(before + int(self._velocity))
        if bar.value() == before:
            self._velocity = 0.0
            return
        self._velocity *= 0.78
        self._idle.start(24)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._keep_selected_visible()

    # ------------------------------------------------------------------ painting
    def paintEvent(self, ev):
        super().paintEvent(ev)
        # nothing extra to draw: the TileDelegate paints play badge + duration

    def _keep_selected_visible(self):
        """Glide the strip to the current tile.

        scrollToItem jumps the bar instantly, which read as a jolt every time
        the wheel moved. This asks Qt where the tile *would* put the bar, then
        eases toward that value instead of snapping to it.

        The scrollbar's own range is far smaller than the content width (a
        QListView in IconMode with uniformItemSizes reports ~20 units for
        ~2300px of tiles), so the target cannot be worked out from
        visualItemRect(). Letting scrollToItem place the bar, reading the
        result, and putting it back is the only reliable way to get the
        number the bar actually uses.
        """
        it = self.currentItem()
        if it is None:
            return
        bar = self.horizontalScrollBar()
        if bar.maximum() - bar.minimum() <= 0:
            return
        before = bar.value()
        self.scrollToItem(it, QAbstractItemView.PositionAtCenter)
        self._glide_to = bar.value()
        bar.setValue(before)               # put it back; the glide does the rest
        if not self._glide.isActive():
            self._glide.start()

    def _glide_tick(self):
        """One eased step toward the target scroll position.

        The bar's range here is only ~10-20 units, so a percentage-of-the-gap
        step rounds to zero and the strip stalls short of the tile. The step
        therefore has a floor of one unit until the target is actually reached.
        """
        bar = self.horizontalScrollBar()
        target = self._glide_to
        cur = bar.value()
        gap = target - cur
        if abs(gap) <= 1:
            bar.setValue(target)
            self._glide.stop()
            return
        # ease in, but never round down to nothing
        step = int(gap * 0.35) or (1 if gap > 0 else -1)
        step = max(-5, min(5, step))
        bar.setValue(cur + step)
        self._glide.start()


class PreviewBar(QWidget):
    """The bottom strip. Photos, live thumbnails; the wheel steps
    from one file to the next while the pointer rests on it."""

    picked = Signal(str)          # a photo was clicked -> open it
    hovered = Signal(bool)
    stepped = Signal(int)         # wheel over the strip -> next/previous file
    statusText = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        # Picasa: strip rides the bottom edge, ~50px tall, near-black
        self.setFixedHeight(50)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.paths: list[str] = []
        self._pool = ThreadPoolExecutor(max_workers=max(2, (os.cpu_count() or 4) - 1),
                                        thread_name_prefix="pvthumb")
        self._sig = _Signals(self)
        self._sig.done.connect(self._on_thumb)
        self._pending: dict[str, QListWidgetItem] = {}
        self._paths_to_load: list[str] = []

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.list = _StripList(self)
        lay.addWidget(self.list)
        self.list.itemClicked.connect(self._clicked)
        self.list.stepped.connect(self.stepped)
        self.list.setStyleSheet(_STRIP_QSS)

        self.caption = QLabel("", self)
        self.caption.setStyleSheet("color:#c6c6cc; background:transparent; font-size:10px;")
        self.caption.hide()

    # ------------------------------------------------------------------ loading
    def _store_thumb(self, item: QListWidgetItem, pm):
        # cover painting lives in the delegate (_PIXMAP_ROLE); the icon must
        # stay EMPTY or QListWidget paints a second contained copy on top
        item.setData(_PIXMAP_ROLE, pm)
        item.setIcon(QIcon())

    def load(self, paths: list[str]):
        self.paths = list(paths)
        self.list.clear()
        self._pending.clear()
        empty = QPixmap()
        for p in self.paths:
            item = QListWidgetItem()               # thumbnail only, no filename text
            item.setData(Qt.UserRole, p)
            item.setData(_PIXMAP_ROLE, empty)
            item.setIcon(QIcon())
            item.setToolTip(Path(p).name)
            self.list.addItem(item)
            self._pending[p] = item
        # queued so the window is already interactive
        self._paths_to_load = list(self.paths)
        QTimer.singleShot(60, self._pump)

    def _pump(self):
        """Keep at most a few extractions queued; the rest wait for the pool."""
        while self._paths_to_load:
            path = self._paths_to_load.pop(0)
            job = _Job(self._sig, path)
            job.setAutoDelete(True)
            QThreadPool.globalInstance().start(job)

    def _on_thumb(self, path: str, pm):
        item = self._pending.get(path)
        if item is None:
            return
        self._store_thumb(item, pm)

    def _clicked(self, item: QListWidgetItem):
        path = item.data(Qt.UserRole)
        self.picked.emit(path)

    # ------------------------------------------------------------------ display
    def thumb_for(self, path: str) -> QPixmap | None:
        """The tile already decoded for `path`, if the worker got to it.

        Scrolling uses this: the strip decodes every photo at thumbnail size on a
        worker thread, so a page can be shown the moment the wheel moves without
        decoding anything on the UI thread.
        """
        for i in range(self.list.count()):
            it = self.list.item(i)
            if os.path.normcase(it.data(Qt.UserRole)) == os.path.normcase(path):
                pm = it.data(_PIXMAP_ROLE)
                return pm if isinstance(pm, QPixmap) and not pm.isNull() else None
        return None

    def reveal(self, path: str):
        row = -1
        for i in range(self.list.count()):
            it = self.list.item(i)
            if os.path.normcase(it.data(Qt.UserRole)) == os.path.normcase(path):
                # setCurrentItem scrolls the view to the item all by itself,
                # which is a hard jump on every single photo change. Hold the
                # scrollbar still across the selection change and let the
                # glide below carry the strip there instead.
                bar = self.list.horizontalScrollBar()
                held = bar.value()
                self.list.setCurrentItem(it)
                bar.setValue(held)
                self.list._keep_selected_visible()
                row = i
                break
        self.caption.setText(f"{row + 1} / {self.list.count()}" if row >= 0 else "")

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.list._keep_selected_visible()

    def set_busy_probe(self, fn):
        """Let the app report whether a photo is still loading.

        The strip's wheel walk waits on this instead of guessing with a timer:
        opening a real photo blocks the UI thread for a few hundred ms, and
        stepping again during that window is what made it feel like it spun.
        """
        self.list.busy = fn

    def shutdown(self):
        self._pool.shutdown(wait=False, cancel_futures=True)


_PIXMAP_ROLE = Qt.UserRole + 3


class TileDelegate(QStyledItemDelegate):
    """Draws each tile: cover-fill thumbnail, play badge, duration.

    Cover, not contain: the tile is a window onto the photo, so the
    thumbnail is scaled to FILL the tile rect and centre-cropped -- the
    continuous-ticker look. QListWidget's own icon painting stays OFF
    (return an empty pixmap); leaving it on draws a second, contained copy
    on top of the cover fill.
    """

    def paint(self, painter: QPainter, option, index):
        r = option.rect
        painter.save()
        painter.setClipRect(r)
        store = index.data(_PIXMAP_ROLE)
        pm = store if isinstance(store, QPixmap) and not store.isNull() else None
        if pm is not None:
            s = max(r.width() / max(pm.width(), 1),
                    r.height() / max(pm.height(), 1))
            dw, dh = int(pm.width() * s), int(pm.height() * s)
            dx = r.x() + (r.width() - dw) // 2
            dy = r.y() + (r.height() - dh) // 2
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.drawPixmap(dx, dy, dw, dh, pm)
        else:
            painter.fillRect(r, QColor(38, 38, 40))
        if option.state & QStyle.State_Selected:
            painter.setPen(QPen(QColor(0x2f, 0x7f, 0xc4), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(r.adjusted(1, 1, -1, -1))
        painter.restore()

    def sizeHint(self, option, index):
        # fixed tile: the filename under the thumbnail must not stretch the strip
        return QSize(31, 49)

_STRIP_QSS = """
QListWidget{background:#08090c;border:none;outline:none;}
QListWidget::item{border:1px solid #000;border-radius:0px;margin:0px;
 background:#08090c;}
QListWidget::item:hover{border:1px solid #7a7a80;}
QListWidget::item:selected{border:2px solid #2f7fc4;background:#08090c;}
QScrollBar:horizontal{height:0px;background:transparent;margin:0;}
QScrollBar::handle:horizontal{background:transparent;}
QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{width:0;height:0;}
QScrollBar::add-page:horizontal,QScrollBar::sub-page:horizontal{background:transparent;}
"""

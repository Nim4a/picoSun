"""Crop / straighten overlay drawn over the photo, and the develop (edit) panel."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from pv_core import Develop

ASPECTS = {
    "Free": None,
    "1:1": 1.0,
    "4:3": 4 / 3,
    "3:2": 3 / 2,
    "16:9": 16 / 9,
    "3:4": 3 / 4,
    "2:3": 2 / 3,
    "9:16": 9 / 16,
    "Original": "orig",
}


# --------------------------------------------------------------------- crop

class CropOverlay(QWidget):
    """Transparent full-area widget; the crop rect is kept in *view* coordinates
    and converted to normalised image coordinates on commit."""
    committed = Signal()
    cancelled = Signal()
    aspectChanged = Signal(str)

    HANDLE = 12

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.image_rect: QRectF | None = None   # where the photo is drawn
        self.crop: QRectF | None = None         # crop rect, view coordinates
        self._mode = "move"
        self._grab: QPointF | None = None
        self._start: QRectF | None = None
        self._aspect: float | None = None
        self._orig_aspect = 1.0
        self._painter_font = QFont()
        self.setCursor(Qt.CrossCursor)

    # ------------------------------------------------------------- lifecycle
    def begin(self, image_rect: QRectF, crop_norm, aspect_name: str, orig_aspect: float):
        self.image_rect = image_rect
        self._orig_aspect = max(orig_aspect, 1e-6)
        self.set_aspect(aspect_name)
        if crop_norm:
            x0, y0, x1, y1 = crop_norm
            r = image_rect
            self.crop = QRectF(r.x() + x0 * r.width(), r.y() + y0 * r.height(),
                               (x1 - x0) * r.width(), (y1 - y0) * r.height())
        else:
            self.crop = QRectF(image_rect.x() + image_rect.width() * 0.06,
                               image_rect.y() + image_rect.height() * 0.06,
                               image_rect.width() * 0.88,
                               image_rect.height() * 0.88)
        self._fit_aspect()
        self._clamp()
        self.show()
        self.raise_()
        self.setFocus()
        self.update()

    def set_aspect(self, name: str):
        key = ASPECTS.get(name, None)
        self._aspect = (self._orig_aspect if key == "orig"
                        else (key if isinstance(key, float) else None))
        if self.crop is not None:
            self._fit_aspect()
            self._clamp()
        self.update()
        self.aspectChanged.emit(name)

    def normalised(self) -> tuple:
        r, c = self.image_rect, self.crop
        if r is None or c is None or r.width() <= 0 or r.height() <= 0:
            return (0.0, 0.0, 1.0, 1.0)
        return (round(max(0.0, (c.left() - r.left()) / r.width()), 5),
                round(max(0.0, (c.top() - r.top()) / r.height()), 5),
                round(min(1.0, (c.right() - r.left()) / r.width()), 5),
                round(min(1.0, (c.bottom() - r.top()) / r.height()), 5))

    def commit(self):
        if self.crop is not None:
            self.committed.emit()

    # ----------------------------------------------------------------- maths
    def _fit_aspect(self):
        if not self.crop or not self._aspect:
            return
        cx, cy = self.crop.center().x(), self.crop.center().y()
        w, h = self.crop.width(), self.crop.height()
        if w / h > self._aspect:
            w = h * self._aspect
        else:
            h = w / self._aspect
        self.crop = QRectF(cx - w / 2, cy - h / 2, w, h)

    def _clamp(self):
        r = self.crop and self.image_rect
        if not self.crop or not r:
            return
        w, h = self.crop.width(), self.crop.height()
        w, h = min(w, r.width()), min(h, r.height())
        if self._aspect:
            if w / h > self._aspect:
                w = h * self._aspect
            else:
                h = w / self._aspect
        self.crop = QRectF(min(max(self.crop.x(), r.x()), r.right() - w),
                           min(max(self.crop.y(), r.y()), r.bottom() - h), w, h)

    def _hit(self, pos: QPointF) -> str:
        c = self.crop
        if c is None:
            return "new"
        tol = self.HANDLE * 1.6
        if abs(pos.x() - c.left()) < tol and abs(pos.y() - c.top()) < tol:
            return "nw"
        if abs(pos.x() - c.right()) < tol and abs(pos.y() - c.top()) < tol:
            return "ne"
        if abs(pos.x() - c.left()) < tol and abs(pos.y() - c.bottom()) < tol:
            return "sw"
        if abs(pos.x() - c.right()) < tol and abs(pos.y() - c.bottom()) < tol:
            return "se"
        return "move" if c.contains(pos) else "new"

    # -------------------------------------------------------------- painting
    def paintEvent(self, ev):
        if not self.crop or not self.image_rect:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        c = QRectF(self.crop)
        dim = QPainterPath()
        dim.addRect(QRectF(self.rect()))
        dim.addRect(c)
        p.fillPath(dim, QColor(0, 0, 0, 150))
        p.setPen(QPen(QColor(255, 255, 255, 240), 1.4))
        p.drawRect(c)
        p.setPen(QPen(QColor(255, 255, 255, 85), 1.0, Qt.DashLine))
        for i in (1, 2):
            p.drawLine(QPointF(c.left() + c.width() * i / 3, c.top()),
                       QPointF(c.left() + c.width() * i / 3, c.bottom()))
            p.drawLine(QPointF(c.left(), c.top() + c.height() * i / 3),
                       QPointF(c.right(), c.top() + c.height() * i / 3))
        h = self.HANDLE / 2.0
        p.setBrush(QColor(255, 255, 255))
        p.setPen(QPen(QColor(0, 0, 0, 170), 1.2))
        for pt in (c.topLeft(), c.topRight(), c.bottomLeft(), c.bottomRight()):
            p.drawRect(QRectF(pt.x() - h, pt.y() - h, self.HANDLE, self.HANDLE))
        f = self._painter_font
        f.setPointSize(9)
        p.setFont(f)
        label = f"{int(c.width())} × {int(c.height())}"
        box = QRectF(c.left(), c.top() - 23, 104, 21)
        p.fillRect(box, QColor(0, 0, 0, 180))
        p.setPen(QColor(255, 255, 255))
        p.drawText(box, Qt.AlignCenter, label)

    # ---------------------------------------------------------------- events
    def mousePressEvent(self, ev):
        if not self.crop:
            return
        pos = ev.position()
        self._mode = self._hit(pos)
        self._grab = pos
        self._start = QRectF(self.crop)
        if self._mode == "new":
            self.crop = QRectF(pos, pos)
            self._aspect = None
            self._mode = "se"
        ev.accept()

    def mouseMoveEvent(self, ev):
        if not self.crop or self._grab is None or not self._start:
            return
        pos = ev.position()
        d = pos - self._grab
        s = self._start
        if self._mode == "move":
            self.crop = QRectF(s.translated(d))
        else:
            x0, y0, x1, y1 = s.left(), s.top(), s.right(), s.bottom()
            if self._mode in ("nw", "new"):
                x0, y0 = s.left() + d.x(), s.top() + d.y()
            if self._mode == "ne":
                x1, y1 = s.right() + d.x(), s.bottom() + d.y()
            if self._mode == "sw":
                x0, y1 = s.left() + d.x(), s.bottom() + d.y()
            if self._mode == "se":
                x1, y1 = s.right() + d.x(), s.bottom() + d.y()
            if self._mode != "new" and self._aspect:
                if abs(d.x()) >= abs(d.y()):
                    y1 = y0 + (x1 - x0) / self._aspect
                else:
                    x1 = x0 + (y1 - y0) * self._aspect
            self.crop = QRectF(QPointF(min(x0, x1), min(y0, y1)),
                               QPointF(max(x0, x1), max(y0, y1)))
        self._clamp()
        self.update()
        ev.accept()

    def mouseReleaseEvent(self, ev):
        if self.crop and (self.crop.width() < 14 or self.crop.height() < 14):
            self.crop = self._start
        self._grab = self._start = None
        self.update()
        ev.accept()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            self.cancelled.emit()
            ev.accept()
        elif ev.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.commit()
            ev.accept()
        else:
            super().keyPressEvent(ev)


# ---------------------------------------------------------------------- panel

class SliderRow(QWidget):
    """Label + value readout + slider.  `scale` divides the raw slider value when
    displaying it (exposure works in tenths of a stop)."""
    changed = Signal(float)
    settled = Signal()

    def __init__(self, label, lo, hi, value=0, suffix="", bipolar=False, scale=1.0):
        super().__init__()
        self.lo, self.hi, self.scale, self.suffix = lo, hi, scale, suffix
        lay = QGridLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setHorizontalSpacing(8)
        lay.setVerticalSpacing(1)
        self.name = QLabel(label)
        self.name.setStyleSheet("color:#e4e6ea; font-size:11px;")
        self.val = QLabel()
        self.val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.val.setMinimumWidth(52)
        self.val.setStyleSheet("color:#84b6ea; font-size:11px;")
        self.sld = QSlider(Qt.Horizontal)
        self.sld.setRange(int(lo), int(hi))
        self.sld.setValue(int(value))
        self.sld.setStyleSheet(_SLIDER_QSS)
        self.sld.valueChanged.connect(self._live)
        self.sld.sliderReleased.connect(self.settled.emit)
        lay.addWidget(self.name, 0, 0)
        lay.addWidget(self.val, 0, 1)
        lay.addWidget(self.sld, 1, 0, 1, 2)
        self._fmt()

    def _fmt(self):
        v = self.sld.value() / self.scale
        self.val.setText(f"{v:+g}{self.suffix}" if self.lo < 0 else f"{v:g}{self.suffix}")

    def _live(self, _v):
        self._fmt()
        self.changed.emit(float(self.sld.value()))

    def set_value(self, raw: float):
        self.sld.blockSignals(True)
        self.sld.setValue(int(round(raw)))
        self.sld.blockSignals(False)
        self._fmt()


_SLIDER_QSS = """
QSlider::groove:horizontal{height:3px;background:#3a3a3a;border-radius:1px;}
QSlider::sub-page:horizontal{background:#5a8cc0;border-radius:1px;}
QSlider::handle:horizontal{width:11px;height:11px;margin:-5px 0;background:#dcdcdc;
 border-radius:6px;border:1px solid #888;}
QSlider::handle:horizontal:hover{background:#ffffff;}
"""

_BTN_QSS = """
QPushButton{background:#2f2f2f;color:#dcdcdc;border:1px solid #454545;border-radius:3px;
 padding:4px 6px;font-size:11px;}
QPushButton:hover{background:#3a3a3a;border-color:#5f5f5f;}
QPushButton:pressed{background:#222;}
QPushButton:disabled{color:#666;border-color:#333;}
"""

_COMBO_QSS = """
QComboBox{background:#2f2f2f;color:#dcdcdc;border:1px solid #454545;border-radius:3px;
 padding:3px;font-size:11px;}
QComboBox QAbstractItemView{background:#2a2a2a;color:#ddd;selection-background-color:#4a7ab0;}
"""


class DevelopPanel(QFrame):
    paramChanged = Signal()
    paramSettled = Signal()
    rotate = Signal(int)
    flip = Signal(str)
    straighten = Signal(float)
    beginCrop = Signal()
    aspectPicked = Signal(str)
    resetAll = Signal()
    saveAs = Signal()
    overwrite = Signal()
    copyEdits = Signal()
    pasteEdits = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self.setFixedWidth(292)
        self.setStyleSheet("background:transparent;")
        self._cropping = False
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(7)

        head = QLabel("ADJUSTMENTS")
        head.setStyleSheet("color:#e4e6ea; font-size:11px; font-weight:bold;")
        root.addWidget(head)
        self.badge = QLabel("no adjustments")
        self.badge.setWordWrap(True)
        self.badge.setStyleSheet("color:#a6a6ae; font-size:10px;")
        root.addWidget(self.badge)

        root.addLayout(self._section("Geometry"))
        grid = QGridLayout()
        grid.setSpacing(4)
        for i, (text, slot) in enumerate((
                ("⟲ Left", lambda: self.rotate.emit(-90)),
                ("Right ⟳", lambda: self.rotate.emit(90)),
                ("Flip H", lambda: self.flip.emit("h")),
                ("Flip V", lambda: self.flip.emit("v")))):
            grid.addWidget(self._btn(text, slot), i // 2, i % 2)
        self.s_straighten = SliderRow("Straighten", -45, 45, 0, "°", True)
        self.s_straighten.changed.connect(self._straighten)
        self.s_straighten.settled.connect(self.paramSettled.emit)
        grid.addWidget(self.s_straighten, 2, 0, 1, 2)
        grid.addWidget(self._btn("Crop  ✂", self.beginCrop.emit), 3, 0)
        self.aspect = QComboBox()
        self.aspect.addItems(list(ASPECTS))
        self.aspect.setStyleSheet(_COMBO_QSS)
        self.aspect.currentTextChanged.connect(self.aspectPicked.emit)
        grid.addWidget(self.aspect, 3, 1)
        root.addLayout(grid)

        root.addLayout(self._section("Light"))
        for row in (self._mk("b_exposure", "Exposure", -50, 50, " EV", True, 10.0),
                    self._mk("b_highlights", "Highlights", -100, 100, "", True),
                    self._mk("b_shadows", "Shadows", -100, 100, "", True),
                    self._mk("b_contrast", "Contrast", -100, 100, "", True)):
            root.addWidget(row)

        root.addLayout(self._section("Colour"))
        for row in (self._mk("b_temp", "Temperature", -100, 100, "", True),
                    self._mk("b_tint", "Tint", -100, 100, "", True),
                    self._mk("b_sat", "Saturation", -100, 100, "", True),
                    self._mk("b_vig", "Vignette", 0, 100, "")):
            root.addWidget(row)
        self.chk_bw = QCheckBox("Black & white")
        self.chk_bw.setStyleSheet("color:#e4e6ea; font-size:11px;")
        self.chk_bw.toggled.connect(self._bw_toggled)
        root.addWidget(self.chk_bw)

        root.addLayout(self._section("Detail"))
        self._mk("b_sharp", "Sharpen", 0, 100, "")
        root.addWidget(self.b_sharp)

        root.addStretch(1)
        row = QHBoxLayout()
        row.setSpacing(4)
        row.addWidget(self._btn("Reset all", self.resetAll.emit))
        row.addWidget(self._btn("Copy", self.copyEdits.emit))
        row.addWidget(self._btn("Paste", self.pasteEdits.emit))
        root.addLayout(row)
        row = QHBoxLayout()
        row.setSpacing(4)
        row.addWidget(self._btn("Save as…", self.saveAs.emit))
        self.btn_over = self._btn("Overwrite", self.overwrite.emit)
        row.addWidget(self.btn_over)
        root.addLayout(row)
        hint = QLabel("Ctrl+S save · Ctrl+Shift+S overwrite\nC crop · Enter apply · Esc cancel")
        hint.setStyleSheet("color:#6e6e6e; font-size:9px;")
        root.addWidget(hint)

    # ----------------------------------------------------------------- build
    def _section(self, title):
        lab = QLabel(title.upper())
        lab.setStyleSheet("color:#7f7f7f; font-size:9px;")
        lay = QVBoxLayout()
        lay.setSpacing(3)
        lay.addWidget(lab)
        return lay

    def _btn(self, text, slot):
        b = QPushButton(text)
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(_BTN_QSS)
        b.clicked.connect(slot)
        return b

    def _mk(self, attr, label, lo, hi, suffix="", bipolar=False, scale=1.0):
        row = SliderRow(label, lo, hi, 0, suffix, bipolar, scale)
        row.changed.connect(lambda _v=0.0: self.paramChanged.emit())
        row.settled.connect(self.paramSettled.emit)
        setattr(self, attr, row)
        return row

    def _straighten(self, raw):
        self.straighten.emit(float(raw))

    def _bw_toggled(self, on: bool):
        self.paramChanged.emit()
        if on:
            self.paramSettled.emit()

    # ------------------------------------------------------------------ sync
    def set_develop(self, d: Develop, interactive: bool = False):
        self.badge.setText(d.label() or "no adjustments")
        if not interactive:
            return
        widgets = [self.b_exposure.sld, self.b_highlights.sld, self.b_shadows.sld,
                   self.b_contrast.sld, self.b_temp.sld, self.b_tint.sld,
                   self.b_sat.sld, self.b_sharp.sld, self.b_vig.sld,
                   self.s_straighten.sld, self.chk_bw]
        for w in widgets:
            w.blockSignals(True)
        self.b_exposure.sld.setValue(int(round(d.exposure * 10)))
        self.b_highlights.sld.setValue(int(round(d.highlights)))
        self.b_shadows.sld.setValue(int(round(d.shadows)))
        self.b_contrast.sld.setValue(int(round(d.contrast)))
        self.b_temp.sld.setValue(int(round(d.temp)))
        self.b_tint.sld.setValue(int(round(d.tint)))
        self.b_sat.sld.setValue(int(round(d.saturation)))
        self.b_sharp.sld.setValue(int(round(d.sharpen)))
        self.b_vig.sld.setValue(int(round(d.vignette)))
        self.s_straighten.sld.setValue(int(round(d.straighten)))
        self.chk_bw.setChecked(d.bw)
        for w in widgets:
            w.blockSignals(False)
        for r in (self.b_exposure, self.b_highlights, self.b_shadows, self.b_contrast,
                  self.b_temp, self.b_tint, self.b_sat, self.b_sharp, self.b_vig,
                  self.s_straighten):
            r._fmt()

    def read_develop(self, base: Develop) -> Develop:
        """Panel -> Develop (used when the user drives the sliders)."""
        d = base.copy()
        d.exposure = self.b_exposure.sld.value() / 10.0
        d.highlights = float(self.b_highlights.sld.value())
        d.shadows = float(self.b_shadows.sld.value())
        d.contrast = float(self.b_contrast.sld.value())
        d.temp = float(self.b_temp.sld.value())
        d.tint = float(self.b_tint.sld.value())
        d.saturation = float(self.b_sat.sld.value())
        d.sharpen = float(self.b_sharp.sld.value())
        d.vignette = float(self.b_vig.sld.value())
        d.straighten = float(self.s_straighten.sld.value())
        d.bw = self.chk_bw.isChecked()
        return d

    def set_raw(self, is_raw: bool):
        self.badge.setToolTip("RAW: developed from 16-bit sensor data"
                              if is_raw else "")

    def reset_widgets(self):
        self.set_develop(Develop(), interactive=True)
        self.aspect.blockSignals(True)
        self.aspect.setCurrentIndex(0)
        self.aspect.blockSignals(False)



    def paintEvent(self, ev):
        from pv_glass import paint_glass
        p = QPainter(self)
        paint_glass(self, p)
        p.end()

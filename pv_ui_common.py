"""Small shared helpers."""

from __future__ import annotations

from PySide6.QtGui import QImage, QPixmap


def pil_to_pixmap(im) -> QPixmap:
    """PIL image -> QPixmap via raw bytes (no ImageQt dependency)."""
    im = im.convert("RGB")
    qimg = QImage(im.tobytes("raw", "RGB"), im.width, im.height, im.width * 3,
                  QImage.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())


def human_size(n: int) -> str:
    f = float(n)
    for u in ("B", "KB", "MB", "GB"):
        if f < 1024 or u == "GB":
            return f"{int(f)} {u}" if u == "B" else f"{f:.1f} {u}"
        f /= 1024.0
    return f"{f:.1f} GB"
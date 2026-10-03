"""Regenerate the synthetic HEIC/HEIF fixtures used to verify HEIC support.

Deliberately unmistakable: a hard red|blue split with a yellow disc dead centre,
so a screenshot or a pixel probe can tell "the HEIC decoded" from "some other
image is on screen" or "the viewer fell back to an empty frame". Both extensions
are written because `.heic` and `.heif` are separate entries in IMAGE_EXTS.

    .venv\\Scripts\\python.exe mksample_heic.py
"""
import shutil
from pathlib import Path

import numpy as np
import pillow_heif
from PIL import Image, ImageDraw

OUT = Path(__file__).parent / "heictest"
OUT.mkdir(parents=True, exist_ok=True)

W, H = 1600, 1000
a = np.zeros((H, W, 3), np.uint8)
a[:, : W // 2] = (200, 40, 40)      # left half red
a[:, W // 2 :] = (30, 90, 210)      # right half blue
im = Image.fromarray(a, "RGB")
d = ImageDraw.Draw(im)
d.ellipse((W // 2 - 180, H // 2 - 180, W // 2 + 180, H // 2 + 180),
          fill=(250, 240, 40))      # yellow disc, centred
d.rectangle((20, 20, 520, 120), fill=(10, 10, 10))
d.text((40, 55), "HEIC FIXTURE", fill=(255, 255, 255))

pillow_heif.register_heif_opener()

heic = OUT / "sample.heic"
im.save(heic, format="HEIF", quality=90)
shutil.copy(heic, OUT / "sample.heif")
print("wrote", heic, heic.stat().st_size, "bytes and sample.heif")
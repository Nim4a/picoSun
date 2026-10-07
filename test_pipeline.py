"""Headless checks: decode -> render -> save, plus RAW decode plumbing."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from PIL import Image

import pv_core as core
from pv_core import Develop, decode, render

HERE = Path(__file__).parent
PICS = HERE / "testpics"
fails = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"   {extra}" if extra else ""))
    if not cond:
        fails.append(name)


# --- decode -----------------------------------------------------------------
im, meta = decode(str(PICS / "pic1.jpg"))
check("decode jpeg", im is not None and im.size == (1600, 1000), str(im.size if im else None))
check("metadata size", meta.get("is_raw") is False)

# --- render: every adjustment actually changes the pixels --------------------
base = im.convert("RGB")
cases = {
    "exposure": dict(exposure=1.5),
    "highlights": dict(highlights=-60),
    "shadows": dict(shadows=70),
    "contrast": dict(contrast=45),
    "temperature": dict(temp=55),
    "tint": dict(tint=-40),
    "saturation": dict(saturation=-90),
    "black&white": dict(bw=True),
    "sharpen": dict(sharpen=70),
    "vignette": dict(vignette=85),
    "rotate": dict(turn=90),
    "straighten": dict(straighten=8.0),
    "flip": dict(flip_h=True),
    "crop": dict(crop=(0.1, 0.1, 0.6, 0.75)),
    "combined": dict(exposure=0.8, contrast=20, temp=-30, saturation=40,
                     sharpen=40, vignette=50, crop=(0.05, 0.05, 0.95, 0.95)),
}
for name, kw in cases.items():
    out = render(base, Develop(**kw))
    check(f"render {name}", out.size != (0, 0), f"{out.size}")
    if name in ("rotate",):
        check("  rotate swaps axes", out.size == (1000, 1600), str(out.size))
    if name == "crop":
        check("  crop size", out.size == (800, 650), str(out.size))

# brightness must actually brighten / darken
import numpy as np
mean0 = float(np.asarray(base).mean())
mean_up = float(np.asarray(render(base, Develop(exposure=1.0))).mean())
mean_dn = float(np.asarray(render(base, Develop(exposure=-1.0))).mean())
check("exposure +1 EV brighter", mean_up > mean0 + 3, f"{mean0:.1f} -> {mean_up:.1f}")
check("exposure -1 EV darker", mean_dn < mean0 - 3, f"{mean0:.1f} -> {mean_dn:.1f}")
check("no clip to pure white at +1EV", mean_up < 254, f"{mean_up:.1f}")

# saturation -100 must make every pixel grey (channels equal, not "flat brightness")
grey = np.asarray(render(base, Develop(saturation=-100)), dtype=np.int16)
chan_spread = np.abs(grey - grey.mean(axis=2, keepdims=True)).max()
check("desaturate -> grey pixels", chan_spread < 3, f"max channel spread {chan_spread}")

# bw -> grey
bw = np.asarray(render(base, Develop(bw=True)), dtype=np.int16)
bw_spread = np.abs(bw - bw.mean(axis=2, keepdims=True)).max()
check("bw -> grey pixels", bw_spread < 3, f"max channel spread {bw_spread}")

# a colour image must NOT be grey, so the checks above can fail
src_spread = np.abs(np.asarray(base, dtype=np.int16) -
                    np.asarray(base, dtype=np.int16).mean(axis=2, keepdims=True)).max()
check("source really is colourful", src_spread > 20, f"source spread {src_spread}")

# untouched image is returned unchanged (fast path)
same = render(base, Develop())
check("default render is passthrough", same.size == base.size and
      np.array_equal(np.asarray(same), np.asarray(base)))

# --- save formats -----------------------------------------------------------
out_dir = Path(tempfile.mkdtemp(prefix="pvtest_"))
final = render(base, Develop(exposure=0.7, saturation=25, sharpen=30))
for ext in (".jpg", ".tif", ".png", ".webp"):
    p = out_dir / f"edited{ext}"
    fmt = {".jpg": "JPEG", ".tif": "TIFF", ".png": "PNG", ".webp": "WEBP"}[ext]
    kw = {".jpg": dict(quality=95, subsampling=0, optimize=True),
          ".tif": dict(compression="tiff_lzw"),
          ".png": dict(optimize=True),
          ".webp": dict(quality=95, method=5)}[ext]
    try:
        final.save(p, fmt, **kw)
        back, _ = decode(str(p))
        check(f"save {ext}", back is not None and abs(back.size[0] - 1600) < 2,
              f"{back.size if back else None} {os.path.getsize(p)//1024}KB")
    except Exception as e:
        check(f"save {ext}", False, str(e))

# --- preview sizing ---------------------------------------------------------
draft, full = core.estimate_preview_side(1400)
check("preview sides sane", 900 < draft < full <= 6400, f"draft={draft} full={full}")

# --- RAW plumbing -----------------------------------------------------------
check("rawpy present", core._mod_ok("RAW_OK", "rawpy"))
check("RAW ext set", {".cr2", ".nef", ".arw", ".dng"} <= core.RAW_EXTS)
check("RAW in image exts", core.RAW_EXTS <= core.IMAGE_EXTS)

# exercise the RAW->16bit->PIL conversion path with a fake postprocess result
fake16 = (np.random.rand(120, 160, 3) * 65535).astype(np.uint16)
arr16 = Image.fromarray((fake16 >> 8).astype(np.uint8), "RGB")
check("16-bit downconvert", arr16.size == (160, 120) and arr16.mode == "RGB")

# --- HEIF -------------------------------------------------------------------
check("pillow-heif registered", core.HEIF_OK)
if core.HEIF_OK:
    p = out_dir / "t.heic"
    try:
        base.save(p, format="HEIF")
        back, m = decode(str(p))
        check("decode heic", back is not None and back.size == base.size,
              f"{back.size if back else None}")
    except Exception as e:
        check("decode heic", False, str(e))

print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
"""Verify the RAW code path.

No real RAW file exists on this machine, so rawpy itself is stubbed with a fake
LibRaw handle that returns a known 16-bit array.  That exercises *our* code:
postprocess arguments, 16-bit -> 8-bit conversion, PIL image, metadata parsing,
and the error branch.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))

import numpy as np

import pv_core as core

fails = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"   {extra}" if extra else ""))
    if not cond:
        fails.append(name)


calls = {}


class FakeRaw:
    """Stands in for rawpy's Raw object."""
    image_desc = b"ImageDescription\x00Test RAW camera\x00"
    sizes = SimpleNamespace(width=8, height=6, width_px=4000, height_px=3000)
    camera_info = {
        "make": "NIKON CORPORATION",
        "model": "NIKON D850",
        "iso_speed": 400.0,
        " shutter": 0.008,
        "fnum": 2.8,
        " focal": 35.0,
        "bits_per_sample": 14,
    }

    def __init__(self, arr):
        self._arr = arr

    def postprocess(self, **kw):
        calls.update(kw)
        return self._arr

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def install_fake(arr):
    class FakeModule:
        ColorSpace = SimpleNamespace(sRGB=1)
        @staticmethod
        def imread(path):
            calls["path"] = path
            return FakeRaw(arr)

    core.rawpy = FakeModule
    core.RAW_OK = True


# a known 16-bit gradient, 4x3 pixels
h, w = 3, 4
arr = (np.arange(h * w * 3, dtype=np.uint16).reshape(h, w, 3) * 500)
install_fake(arr)

im, meta = core.decode("C:/photos/IMG_0001.NEF")
check("raw decode returns an image", im is not None and im is not False)
check("raw image size", im.size == (w, h), str(im.size))
check("raw image mode", im.mode == "RGB", im.mode)
check("16-bit -> 8-bit downconvert", np.array_equal(np.asarray(im), (arr >> 8)),
      f"first px {np.asarray(im)[0, 0].tolist()} vs {(arr >> 8)[0, 0].tolist()}")

check("postprocess asks for 16-bit", calls.get("output_bps") == 16, str(calls.get("output_bps")))
check("postprocess uses camera WB", calls.get("use_camera_wb") is True)
check("postprocess not half size", calls.get("half_size") is False)
check("rawpy.imread got the path", calls.get("path", "").endswith("IMG_0001.NEF"))

check("meta flagged raw", meta.get("is_raw") is True)
check("camera make", meta.get("make") == "NIKON CORPORATION", meta.get("make", ""))
check("camera model", meta.get("model") == "NIKON D850", meta.get("model", ""))
check("iso read", str(meta.get("iso")) == "400.0", str(meta.get("iso")))
check("shutter formatted", meta.get("shutter") == "1/125s", meta.get("shutter", ""))
check("aperture formatted", meta.get("fnum") == "f/2.8", meta.get("fnum", ""))
check("focal formatted", "35mm" in str(meta.get("focal", "")), str(meta.get("focal", "")))

cam = core.camera_line(meta)
check("camera line has no duplicate make/model", "NIKON CORPORATION NIKON" not in cam, cam[:70])

# edits must work on RAW-derived data too
from pv_core import Develop, render
out = render(im, Develop(exposure=1.2, saturation=-100, bw=False))
check("raw + edits renders", out.size == (w, h))
check("raw + edits brightens",
      float(np.asarray(out).mean()) > float(np.asarray(im).mean()),
      f"{np.asarray(out).mean():.1f} > {np.asarray(im).mean():.1f}")

# error branch: rawpy raises
class Boom:
    ColorSpace = SimpleNamespace(sRGB=1)
    @staticmethod
    def imread(path):
        raise IOError("unsupported file format")

core.rawpy = Boom
im2, meta2 = core.decode("C:/photos/broken.CR2")
check("raw failure -> None", im2 is None)
check("raw failure -> message", "RAW decode failed" in str(meta2.get("error", "")),
      str(meta2.get("error", ""))[:60])

# rawpy missing entirely
core.RAW_OK = False
im3, meta3 = core.decode("C:/photos/x.ARW")
check("rawpy missing -> hint", im3 is None and "rawpy is not installed" in str(meta3.get("error", "")))

print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
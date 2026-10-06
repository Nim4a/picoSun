"""
Decoding + non-destructive edit pipeline for the photo viewer.

Base image is decoded once into a PIL RGB image (RAW goes through rawpy/LibRaw and
is developed from 16-bit data).  All edits are parameter values only; rendering is
a pure function of (base, params) so a preview can be re-rendered cheaply and the
full-resolution master is rebuilt only for 1:1 zoom or for saving.

Geometry (turn / straighten / flip / crop) is done with PIL, tone and colour with
numpy.  Order: geometry -> exposure -> white balance -> highlight/shadow ->
contrast -> saturation -> B&W -> sharpen -> vignette.
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIF_OK = True
except Exception:  # pragma: no cover
    HEIF_OK = False

try:
    from pillow_jxl import JpegXLImagePlugin  # registers the .jxl opener with Pillow

    JXL_OK = True
except Exception:  # pragma: no cover
    JXL_OK = False

try:
    import qoi                 # registers the .qoi opener with Pillow

    QOI_OK = True
except Exception:  # pragma: no cover
    QOI_OK = False

try:
    import rawpy

    RAW_OK = True
except Exception:  # pragma: no cover
    RAW_OK = False


RAW_EXTS = {
    ".cr2", ".cr3", ".crw", ".nef", ".nrw", ".arw", ".arq", ".srf", ".sr2",
    ".dng", ".orf", ".rw2", ".raf", ".pef", ".ptx", ".erf", ".mrw", ".mos",
    ".iiq", ".kdc", ".dcr", ".k25", ".x3f", ".rwl", ".rwz", ".srw", ".gpr",
    ".3fr", ".ari", ".bay", ".cap", ".dcs", ".drf", ".eip", ".fff", ".mdc",
    ".mef", ".obm", ".pxn", ".r3d", ".raw",
}

# ImageGlass's format list: everything it recognises. Decoders: Pillow covers
# the common raster set; Qt covers svg/jxl/dds/psd via plugins where present --
# files the decoders cannot open still resolve in the folder scan and show a
# clear error instead of silently vanishing from the filmstrip.
IMAGE_EXTS = {
    ".jpg", ".jpeg", ".jpe", ".jfif", ".png", ".apng", ".bmp", ".gif", ".gifv",
    ".webp", ".tif", ".tiff", ".heic", ".heif", ".hif", ".avif", ".ico", ".cur",
    ".ani", ".ppm", ".pgm", ".pbm", ".pnm", ".tga", ".dib", ".pcx", ".cut",
    ".dds", ".exr", ".hdr", ".fits", ".flif", ".jxl", ".jp2", ".j2k", ".pfm",
    ".psd", ".psb", ".qoi", ".svg", ".svgz", ".xpm", ".xbm", ".xv", ".viff",
    ".wbm", ".wmf", ".emf", ".jxr", ".wdp", ".hdp", ".fax", ".exif", ".mjpeg",
    ".wpg",
} | RAW_EXTS

# formats Qt/Pillow can save
SAVE_EXTS = [".jpg", ".jpeg", ".tif", ".tiff", ".png", ".webp"]


# --------------------------------------------------------------------------- params

@dataclass
class Develop:
    """Every field is a plain value; nothing is baked into the base image."""
    turn: int = 0                 # 0/90/180/270
    straighten: float = 0.0       # -45..45 degrees, canvas kept
    flip_h: bool = False
    flip_v: bool = False
    crop: tuple[float, float, float, float] | None = None   # normalised x0,y0,x1,y1
    exposure: float = 0.0         # EV, -5..5
    temp: float = 0.0             # -100..100
    tint: float = 0.0             # -100..100
    highlights: float = 0.0       # -100..100 (recovery)
    shadows: float = 0.0          # -100..100 (lift)
    contrast: float = 0.0         # -100..100
    saturation: float = 0.0       # -100..100
    bw: bool = False
    sharpen: float = 0.0          # 0..100
    vignette: float = 0.0         # 0..100
    crop_aspect: str = "Free"

    def copy(self) -> "Develop":
        return replace(self)

    @property
    def is_default(self) -> bool:
        return self == Develop()

    def geometry_only(self) -> bool:
        d = Develop()
        return (self.turn, self.straighten, self.flip_h, self.flip_v, self.crop) == (
            d.turn, d.straighten, d.flip_h, d.flip_v, d.crop)

    def tone_is_default(self) -> bool:
        d = Develop()
        return (self.exposure, self.temp, self.tint, self.highlights, self.shadows,
                self.contrast, self.saturation, self.bw, self.sharpen,
                self.vignette) == (
            d.exposure, d.temp, d.tint, d.highlights, d.shadows, d.contrast,
            d.saturation, d.bw, d.sharpen, d.vignette)

    def label(self) -> str:
        if self.is_default:
            return ""
        bits = []
        if self.bw:
            bits.append("B&W")
        if self.turn:
            bits.append(f"{self.turn}°")
        if abs(self.straighten) > 0.1:
            bits.append(f"straighten {self.straighten:+.1f}°")
        if self.flip_h:
            bits.append("flip H")
        if self.flip_v:
            bits.append("flip V")
        if self.crop:
            bits.append("crop")
        for name in ("exposure", "temp", "tint", "highlights", "shadows",
                     "contrast", "saturation"):
            v = getattr(self, name)
            if abs(v) > 0.5:
                bits.append(f"{name} {v:+g}")
        for name in ("sharpen", "vignette"):
            v = getattr(self, name)
            if v > 0.5:
                bits.append(f"{name} {v:g}")
        return ", ".join(bits)


# --------------------------------------------------------------------------- decode

def is_raw(path: str) -> bool:
    return Path(path).suffix.lower() in RAW_EXTS


# A viewer pages back and forth over the same files. The decode was the whole
# per-page stall (~500ms for 12MP), and the strip decoded every tile AGAIN
# from disk: one folder open decoded N photos twice. Cache the master by
# (mtime, size, path) so a revisit costs nothing. Bounded (LRU, 12 masters)
# and on RAW_CACHE_MISS nothing changes -- the first decode still pays full.
_MASTER_CACHE_MAX = 12
_master_cache: dict[tuple, tuple] = {}
_master_order: list = []


def _master_key(path: str):
    try:
        st = os.stat(path)
        return (os.path.normcase(os.path.abspath(path)), st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def master_for(path: str):
    """Decoded master, cached. Returns None on failure (same as decode)."""
    key = _master_key(path)
    if key is not None and key in _master_cache:
        _master_order.remove(key)
        _master_order.append(key)
        return _master_cache[key]
    im, meta = decode(path)
    if im is not None and key is not None:
        _master_cache[key] = (im, meta)
        _master_order.append(key)
        while len(_master_order) > _MASTER_CACHE_MAX:
            _master_cache.pop(_master_order.pop(0), None)
    return (im, meta) if im is not None else (None, meta)


def decode(path: str) -> tuple[Image.Image | None, dict]:
    """Return (PIL RGB image, metadata dict).  image is None on failure."""
    path = os.path.abspath(path)
    ext = Path(path).suffix.lower()
    meta = {"is_raw": ext in RAW_EXTS}

    if ext in RAW_EXTS:
        if not RAW_OK:
            return None, {**meta, "error": "rawpy is not installed"}
        try:
            return _decode_raw(path, meta)
        except Exception as e:  # pragma: no cover
            return None, {**meta, "error": f"RAW decode failed: {e}"}

    try:
        with Image.open(path) as im:
            im.load()
            try:
                im = ImageOps.exif_transpose(im)
            except Exception:
                pass
            info = {k: im.info.get(k) for k in ("exif", "icc_profile")}
            meta["exif"] = info.get("exif")
            meta["icc"] = info.get("icc_profile")
            im = im.convert("RGB")
            meta.update(_exif_from(im, meta["exif"]))
            return im, meta
    except Exception as e:
        return None, {**meta, "error": str(e)}


def _decode_raw(path: str, meta: dict) -> tuple[Image.Image, dict]:
    with rawpy.imread(path) as raw:
        # 16-bit sRGB output keeps tone edits clean; size/iso come from LibRaw
        arr = raw.postprocess(
            use_camera_wb=True,
            no_auto_bright=False,
            output_color=rawpy.ColorSpace.sRGB,
            half_size=False,
            use_raw_decoder=False,
            output_bps=16,
        )
        ci = getattr(raw, "camera_info", None) or {}
        desc = getattr(raw, "image_desc", None)
        meta.update({
            "make": ci.get("make", "").strip(),
            "model": (ci.get("model") or "").strip(),
            "iso": ci.get("iso_speed", ""),
            "shutter": _fmt_shutter(ci.get(" shutter", "") or ci.get("shutter", "")),
            "fnum": f"f/{ci.get('fnum'):g}" if isinstance(ci.get("fnum"), float) else "",
            "focal": _fmt_focal(ci.get(" focal") or ci.get("focal")),
            "raw_desc": desc.decode(errors="replace")[:400] if isinstance(desc, bytes) else str(desc or "")[:400],
            "raw_size": getattr(raw, "sizes", None) and (
                raw.sizes.width, raw.sizes.height, raw.sizes.width_px, raw.sizes.height_px),
            "bit_depth": ci.get("bits_per_sample", ""),
        })
    a16 = arr.astype(np.uint16)
    im = Image.fromarray((a16 >> 8).astype(np.uint8), "RGB")
    return im, meta


def _fmt_shutter(v) -> str:
    if not v:
        return ""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if f <= 0:
        return ""
    if f < 1:
        return f"1/{round(1 / f)}s"
    return f"{f:g}s"


def _fmt_focal(v) -> str:
    """Focal length in mm; LibRaw keys are inconsistently spaced."""
    if not v:
        return ""
    try:
        return f"{float(v):g}mm"
    except (TypeError, ValueError):
        return str(v)


_CORP_SUFFIX = {"corporation", "corp", "inc", "inc.", "co", "co.", "company",
                "camera", "optical", "optical co", "imaging", "corp.", "ltd"}


def _clean_make_model(make: str, model: str) -> str:
    """'NIKON CORPORATION' + 'NIKON D850' -> 'NIKON D850'."""
    make, model = (make or "").strip(), (model or "").strip()
    if not make:
        return model
    if not model:
        return make
    if model.lower().startswith(make.lower()) or make.lower().startswith(model.lower()):
        return model if len(model) >= len(make) else make
    # drop the corporate tail, then check whether make is redundant inside model
    words = [w.strip(".,") for w in make.split()]
    brand = " ".join(w for w in words if w and w.lower() not in _CORP_SUFFIX)
    if brand and brand.lower() in model.lower():
        return model
    return " ".join(x for x in (make, model) if x)


def _exif_from(im: Image.Image, exif_bytes) -> dict:
    out: dict = {}
    try:
        from PIL import ExifTags

        tags = im.getexif()
        if not tags:
            return out
        name = {v: k for k, v in ExifTags.TAGS.items()}

        def g(n, default=""):
            v = tags.get(name.get(n, -1))
            return default if v in (None, "") else v

        out["make"] = str(g("Make", "")).strip()
        out["model"] = str(g("Model", "")).strip()
        out["iso"] = g("ISOSpeedRatings", "")
        out["shutter"] = _fmt_shutter(g("ExposureTime", ""))
        fno = g("FNumber", "")
        out["fnum"] = f"f/{float(fno):g}" if fno else ""
        fl = g("FocalLength", "")
        out["focal"] = f"{float(fl):g}mm" if fl else ""
        out["lens"] = str(g("LensModel", "") or "")
        out["stamp"] = str(g("DateTimeOriginal", "") or g("DateTime", "") or "")
    except Exception:
        pass
    return {k: v for k, v in out.items() if v}


def camera_line(meta: dict) -> str:
    cam = _clean_make_model(meta.get("make", ""), meta.get("model", ""))
    if not cam and not meta.get("raw_desc"):
        return ""
    tail = [meta.get("iso") and f"ISO {meta['iso']}", meta.get("shutter"),
            meta.get("fnum"), meta.get("focal"), meta.get("lens")]
    parts = ([cam] if cam else []) + [str(t) for t in tail if t]
    return "  |  ".join([p for p in parts if p])


# ---------------------------------------------------------------------- render

def _geometry(im: Image.Image, d: Develop) -> Image.Image:
    if d.turn:
        im = im.rotate(-d.turn, expand=True, resample=Image.BICUBIC)
    if d.straighten:
        im = im.rotate(d.straighten, expand=False, resample=Image.BICUBIC,
                       fillcolor=(0, 0, 0))
    if d.flip_h:
        im = im.transpose(Image.FLIP_LEFT_RIGHT)
    if d.flip_v:
        im = im.transpose(Image.FLIP_TOP_BOTTOM)
    if d.crop:
        W, H = im.size
        x0, y0, x1, y1 = d.crop
        box = (max(0, int(x0 * W)), max(0, int(y0 * H)),
               min(W, int(x1 * W)), min(H, int(y1 * H)))
        if box[2] - box[0] > 8 and box[3] - box[1] > 8:
            im = im.crop(box)
    return im


def _tone(im: Image.Image, d: Develop) -> Image.Image:
    a = np.asarray(im, dtype=np.float32) / 255.0
    lum_w = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)

    if abs(d.exposure) > 1e-3:
        a *= (2.0 ** d.exposure)
    if abs(d.temp) > 0.5 or abs(d.tint) > 0.5:
        t, ti = d.temp / 100.0, d.tint / 100.0
        a[..., 0] *= (1.0 + 0.30 * t)
        a[..., 2] *= (1.0 - 0.30 * t)
        a[..., 1] *= (1.0 + 0.20 * ti)

    lum = a @ lum_w
    if d.highlights or d.shadows:
        hi = (np.clip(lum, 0.0, 1.0) ** 2)[..., None]
        sh = (np.clip(1.0 - lum, 0.0, 1.0) ** 2)[..., None]
        if d.highlights:
            a *= (1.0 + (d.highlights / 100.0) * 0.85 * hi)
        if d.shadows:
            a *= (1.0 + (d.shadows / 100.0) * 0.95 * sh)
    if abs(d.contrast) > 0.5:
        k = 1.0 + d.contrast / 100.0
        a = np.clip((a - 0.5) * k + 0.5, 0.0, 1.0)
    if abs(d.saturation) > 0.5 or d.bw:
        lum = a @ lum_w
        s = 1.0 + d.saturation / 100.0
        if d.bw:
            # a touch of a film curve so B&W is not flat grey
            g = np.clip(lum, 0, 1) ** 0.95
            a = np.repeat((g * 1.02 - 0.01)[..., None], 3, axis=2)
        else:
            a = lum[..., None] + (a - lum[..., None]) * s
    np.clip(a, 0.0, 1.0, out=a)
    return Image.fromarray((a * 255.0 + 0.5).astype(np.uint8), "RGB")


def _finish(im: Image.Image, d: Develop) -> Image.Image:
    if d.sharpen > 0.5:
        radius = 1.0 + 2.0 * (d.sharpen / 100.0)
        percent = int(40 + 130 * (d.sharpen / 100.0))
        im = im.filter(ImageFilter.UnsharpMask(radius=radius, percent=percent, threshold=3))
    if d.vignette > 0.5:
        a = np.asarray(im, dtype=np.float32) / 255.0
        H, W = a.shape[:2]
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        cy, cx = (H - 1) / 2.0, (W - 1) / 2.0
        r = np.sqrt(((yy - cy) / max(cy, 1)) ** 2 + ((xx - cx) / max(cx, 1)) ** 2) / 1.4142
        mask = 1.0 - (d.vignette / 100.0) * np.clip(r - 0.35, 0.0, 1.0) ** 1.6 * 1.6
        a *= mask[..., None]
        np.clip(a, 0.0, 1.0, out=a)
        im = Image.fromarray((a * 255.0 + 0.5).astype(np.uint8), "RGB")
    return im


def render(base: Image.Image, d: Develop, max_side: int | None = None) -> Image.Image:
    """Full edit pipeline.  max_side caps the long edge (preview rendering).

    Order is geometry -> tone -> finish.  Steps whose parameters are all at their
    defaults are skipped so an unedited photo is returned untouched.
    """
    im = base
    if not d.geometry_only():
        im = _geometry(base, d)
    if max_side and max(im.size) > max_side:
        f = max_side / max(im.size)
        im = im.resize((max(1, int(im.width * f)), max(1, int(im.height * f))),
                       Image.LANCZOS)
    if not d.tone_is_default():
        im = _tone(im, d)
    if d.sharpen > 0.5 or d.vignette > 0.5:
        im = _finish(im, d)
    return im


def estimate_preview_side(view_px: int) -> tuple[int, int]:
    """(draft, full) long-edge sizes for interactive slider dragging vs settled.

    full is deliberately SMALLER than the raw photo: the view only ever
    shows fit-to-window, so rendering above ~2x the window is wasted work
    (a 24MP photo down to a 1080p window throws away 90% of the pixels on
    every page turn). RAW masters still decode full-size; this only caps
    what gets rendered for display.
    """
    draft = int(max(900, min(4000, view_px * 1.4)))
    full = int(max(1600, min(2800, view_px * 2.0)))
    return draft, full


def encode_jpeg_bytes(im: Image.Image, quality: int = 95, subsampling: int = 0) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=int(quality), subsampling=subsampling,
            optimize=True, progressive=True)
    return buf.getvalue()


def encode_tiff16(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "TIFF", compression="tiff_lzw")
    return buf.getvalue()
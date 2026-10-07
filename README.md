# picoSun

A standalone Windows photo viewer in the spirit of Google's picoSun:
frameless, opens fullscreen on first run, transparent letterbox with a soft drop
shadow behind the photo, and navigation with the arrow keys. No gallery, no
database, no face recognition — just the photo.

Plus a small non-destructive editor and RAW development (CR2 / NEF / ARW / DNG /
ORF / RW2 / RAF / PEF / SR2 and friends).

## Run it

```
run.bat                       # launches fullscreen, then Ctrl+O or drop a photo
run.bat "D:\Photos\IMG_0042.CR2"
run.bat "D:\Photos\Holiday"   # a folder: opens on its first photo
```

The single argument may be a photo **or a folder**. A folder opens on its first
photo and the whole folder becomes the bottom strip.

The app used to take its argument only when the extension was a photo extension,
so a directory — no extension — was filtered out and the window opened empty
with no error at all. That was the app's main use case, and it looked like a
crash rather than a bad argument. The command line and drag-and-drop now share
one resolver, so they accept the same things: a photo, a video, or a folder
containing either.

`dist\picoSun\picoSun.exe` is the launcher for the
standalone build — no Python needed. The `dist\picoSun\` folder next to
it is required too (it is a onedir build, which starts in about two seconds
instead of the six a single-file build spent unpacking itself every launch).
Double-clicking a photo after you set it as the default handler opens it here.

From source:

```
.venv\Scripts\python.exe picasa_viewer.py testpics\pic1.jpg
```

## The title bar

The window is frameless, so the title bar is drawn by the app:

```
[ picoSun                                 –  □  ✕ ]
[ File  View  Edit  Slideshow  Help                                 ]
[                            the photo                             ]
[                    the bottom control bar                        ]
```

- **Drag it anywhere along the left of the buttons** to move the window;
  double-click the empty part to toggle fullscreen.
- The three buttons on the right are minimise, maximise/restore and close
  (close hovers red). They are hidden in fullscreen, where there is no window
  to manage.

The title bar owns the top strip of the window, and the menu bar is stacked
directly underneath it. It used to be the other way round: the menu bar was the
`QMainWindow`'s own, and a `QMainWindow` always lays that out *above* its
central widget — so it covered the title strip. That is why the title bar had
no buttons and why dragging it did nothing: every press at the top of the window
was going to the menu. `setMenuBar(None)` and an explicit `QMenuBar` child fixed
both at once.

## Window controls on the bottom bar

In fullscreen the title bar is gone, so the bottom bar carries the way out:

| State | Right-hand corner of the bottom bar |
|---|---|
| normal window | Minimise, Maximise/restore, Close (close hovers red) |
| fullscreen | Exit |
| narrow window | Exit only — the window buttons are dropped before they can overlap |

The bar drops controls from the least useful end (Open, then the preview strip,
then the window buttons) until the row measurably fits, so it never overlaps
itself. Fullscreen keeps the bottom bar visible for exactly this reason; the
title bar, menus and status bar still hide.

## Wheel behaviour

- **over the photo** — zoom, anchored so the pixel under the pointer stays put
- **over the empty margin, or over the thumbnail strip** — page the folder

The expensive part of a page turn is the decode: a 12MP JPEG blocks the UI
thread for 430-550ms. Instrumenting the pain — *"when I scroll fast it gets
dizzy"* — showed six photos in 1.44s, the window frozen half a second between
each: freeze, jump, freeze, jump at ~2Hz. Pacing the turns made it feel slow
instead (*"the speed must follow the wheel"*).

So the wheel pages on the thumbnail the strip already decoded on a worker
thread, and nothing else:

- **every notch moves a page, at once** — the view shows the enlarged
  thumbnail (drawn with smooth scaling, so it reads as a soft photo, not a
  pixelated one). The page rate IS the wheel rate;
- a settle timer (`WHEEL_SETTLE_MS` = 220ms) restarts on every notch, and
  **when the wheel rests, exactly one real decode happens**, of wherever the
  gesture landed — the thumbnail sharpens into the full photo.

A flick of any length therefore costs ONE decode, with the window never
blocking while it runs. Measured live on the shipped exe (24 real notches every
35ms while sampling the UI thread's response to a `WM_NULL` message, which only
returns when the queue is pumped):

| | before | now |
|---|---|---|
| UI-thread response during the flick | blocked most of the time | **0ms median, 11ms max** |
| pages moved | 6 in 1.44s | **24 = one per notch** |
| decodes | 6 | **1** (at rest, ~250ms — the sharpening decode) |

The single settle decode is the synchronous decode itself; a threaded decode
would remove even that, and is a larger change than this needed.

The thumbnail strip ignores the wheel until the pointer has actually entered it
— not to be clever, but because an unhovered wheel over the strip is almost
always a wheel meant for the photo behind it.

## Navigation (same as Picasa)

| Key | Action |
|---|---|
| → / Space / PageDown | next photo in the folder |
| ← / PageUp / Backspace | previous photo |
| Home / End | first / last photo |
| wheel, + / - | zoom at the cursor (the pixel under the pointer stays put) |
| 0 / 1 | fit window / actual size |
| click | toggle fit ↔ 100% |
| double-click | leave fullscreen first, then toggle fit ↔ 100% |
| drag | pan |
| F or F11 | fullscreen; first launch always starts fullscreen |
| wheel off the photo, or over the bottom bar | next / previous photo — one flick moves one photo |
| Esc | leave fullscreen, or close when already fitted |
| Ctrl+T / Ctrl+I / Ctrl+E | bottom preview strip / photo info / adjustments panel |
| F5 | slideshow |
| right-click | context menu (the only menu while fullscreen) |
| Ctrl+O, drag & drop | open a photo or a folder |

## Editing

Adjustments are parameters, never destructive: the decoded master is kept and the
photo is re-rendered from it, so nothing is baked in until you save.

Geometry — rotate 90° (R / Shift+R), flip H/V, straighten ±45°, crop with a
draggable rect and an aspect lock (1:1, 4:3, 3:2, 16:9, 9:16, original).

Light — exposure ±5 EV, highlight recovery, shadow lift, contrast.

Colour — temperature, tint, saturation, vignette, black & white.

Detail — unsharp-mask sharpening.

Ctrl+Z undoes, Ctrl+C / Ctrl+V copies the whole adjustment set between photos,
Ctrl+S saves a copy, Ctrl+Shift+S overwrites in place. RAW files are never written
back as RAW — Save As writes JPEG / TIFF / PNG / WebP instead.

## RAW

`rawpy` (LibRaw) decodes the sensor data at 16 bits with the camera's own white
balance, then the same tone pipeline runs on that — so exposure and shadow
recovery work on RAW with real headroom, not on an already-compressed JPEG.
Camera, lens, ISO, shutter, aperture and focal length come from LibRaw's metadata
and show in the info panel.

## HEIC / HEIF and AVIF

`pillow-heif` registers a Pillow opener for HEIC, HEIF and AVIF, so phone photos
decode like any other file — master, thumbnails, zoom and the edit pipeline all
work on them, and they can be saved out as JPEG/TIFF/PNG/WebP.

The plugin and the libraries it needs (`libheif`, `libde265`, `libx265`) are
bundled into the standalone build, so HEIC works in the exe with no extra
install. No PyInstaller hook exists for `pillow_heif` and none is needed — the
default analysis puts the package in the archive and picks up the shared
libraries through the extension module. `Help ▸ About` reports whether the plugin
loaded, which separates "this file is unsupported" from "the plugin is missing".

## The window owns the mouse everywhere

The window is translucent, and Windows hit-tests a *layered* window by its alpha:
a pixel with alpha 0 belongs to whatever is behind the app. Only the photo, the
bars and the thumbnail tiles were painted, so the letterbox and the gaps between
the thumbnails were holes. Measured over the real window with `WindowFromPoint`,
**64% of it belonged to the browser underneath** — the wheel over the bottom
strip went to that browser instead of scrolling the strip, because the strip
never even got a hover.

The fix is one fill of the top-level rect with alpha 1/255: invisible over any
wallpaper, children still paint on top, and the whole window becomes the app's.
Re-measured: **100%**.

```
def paintEvent(self, ev):
    QPainter(self).fillRect(self.rect(), QColor(0, 0, 0, 1))
```

`test_titlebar.py` samples the grabbed window for alpha-0 pixels, so a new
transparent widget cannot silently reopen a hole.

## The bottom preview strip

Every photo **and video** in the folder appears as a thumbnail along the bottom
edge. Video thumbnails are real frames grabbed with `ffmpeg` (not a generic
icon), each video tile carries a play badge and its duration, and photo tiles
carry nothing but the picture.

- only the current photo is highlighted, and it stays scrolled into view
- hover the strip and the mouse wheel scrolls it, with a short glide
- the wheel is ignored over the strip until you actually hover it
- click a photo to open it, click a video to play it in place
- `Ctrl+T` hides and shows the strip
- arrow-key navigation only ever lands on photos — videos are skipped

## Files

| File | What it holds |
|---|---|
| `picasa_viewer.py` | window, navigation, menus, shortcuts, video playback, save/RAW policy |
| `pv_core.py` | decode (Pillow / rawpy / pillow-heif), `Develop` params, render pipeline |
| `pv_view.py` | the zoom/pan canvas: fit maths, anchoring, drop shadow |
| `pv_panel.py` | crop overlay + the adjustments panel |
| `pv_preview.py` | the bottom preview strip: thumbnails, ffmpeg frames, wheel scroll |
| `pv_ui_chrome.py` | title strip, nav bar, info panel |
| `pv_ui_common.py` | PIL↔QPixmap, byte formatting |

Render order: geometry → exposure → white balance → highlights/shadows →
contrast → saturation/B&W → sharpen → vignette. Steps whose parameters are all at
their defaults are skipped, so an unedited photo comes back untouched.

While a slider is being dragged the photo is re-rendered downscaled, then a
full-quality pass follows ~220 ms after you let go, so dragging stays smooth on
large files.

## Tests

```
run_tests.bat
```

* `test_pipeline.py` — decode, every adjustment changes the right pixels, save to
  jpg/tiff/png/webp, HEIC round-trip.
* `test_raw.py` — the RAW branch with a stubbed LibRaw (16-bit downconvert, EXIF
  formatting, error paths). There is no RAW sample on this machine, so LibRaw's own
  decode is not exercised here.
* `test_gui.py` — the real window under `QT_QPA_PLATFORM=offscreen`: navigation,
  zoom, rotate, crop, edit panel, preview strip, fullscreen, double-click leaving
  fullscreen, first-run behaviour, save.
* `test_zoom_anchor.py` — zooming is anchored: the image point under the cursor
  does not move across wheel and stepped zoom, and the two axes clamp
  independently (free while pannable, centred once the image fits).
* `test_preview.py` — the strip against a folder of 3 real photos and 2 real
  ffmpeg-made videos: thumbnails, duration badges, wheel-on-hover scrolling,
  click routing and the toggle.
* `test_titlebar.py` — the title bar owns the top strip, carries the window
  buttons and moves the window when dragged. It also checks the *pixels*: the
  bar and each glyph must really be painted, not merely visible, because
  geometry and `isVisible()` both looked correct while the bar drew nothing.
* `test_target.py` — what the app opens when handed a path: a folder resolves to
  its first media file (photos before videos, natural order), a media file to
  itself, a text file to nothing — plus one check that the window really loads
  the whole folder rather than a single file.

`heictest/` holds a synthetic HEIC fixture — a red|blue split with a yellow disc,
chosen so a screenshot or a pixel probe can tell it apart from any other image
and from an error placeholder. It is how HEIC decoding was verified in the
standalone exe; `mkheic.py` regenerates it.

`test_gui.py` and `test_zoom_anchor.py` inject an INI-backed `QSettings`
(`Viewer.SETTINGS`) so offscreen runs never overwrite the real app's saved window
state.

Note when adding tests here: a `QPixmap` built before a `QGuiApplication` exists
kills the process outright with no traceback, so create the app instance first.
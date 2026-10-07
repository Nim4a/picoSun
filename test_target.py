"""What the app opens when you hand it a path.

A directory is the main use case -- "open this folder of photos" -- and it used
to be silently ignored, because the argument was accepted only when its
extension was in IMAGE_EXTS and a directory has no extension. The window then
opened empty with no error at all, which reads as "the app is broken".

These pin the resolver that the command line and drag-and-drop now share.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtCore import QEventLoop, QSettings, QTimer
from PySide6.QtWidgets import QApplication

HERE = Path(__file__).parent

app = QApplication.instance() or QApplication([])

import picasa_viewer as pv  # noqa: E402

fails = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + (("   " + str(extra)) if extra and not cond else ""))
    if not cond:
        fails.append(name)


work = Path(tempfile.mkdtemp(prefix="pv_target_"))

# a folder with the natural-order trap and a video in it
folder = work / "album"
folder.mkdir()
for name in ("pic1.jpg", "pic2.JPG", "pic10.jpg", "clip.mp4", "notes.txt",
             "shot.heic"):
    (folder / name).write_bytes(b"x")

empty = work / "empty"
empty.mkdir()

print("--- resolve_target: directories ------------------------------------")
first = pv.resolve_target(str(folder))
check("a directory resolves to a media file",
      first is not None and os.path.isfile(first), first)
check("it is a photo, not the video", first and first.endswith("pic1.jpg"), first)
check("non-media files are never chosen",
      first is not None and not first.endswith(("notes.txt",)), first)
check("an empty directory resolves to None", pv.resolve_target(str(empty)) is None,
      pv.resolve_target(str(empty)))
check("a missing path resolves to None",
      pv.resolve_target(str(work / "nope")) is None)

print()
print("--- resolve_target: files ------------------------------------------")
jpg = folder / "pic1.jpg"
check("a media file resolves to itself",
      pv.resolve_target(str(jpg)) == str(jpg), pv.resolve_target(str(jpg)))
check("a HEIC file resolves to itself",
      pv.resolve_target(str(folder / "shot.heic")) == str(folder / "shot.heic"))
check("a video file is NOT media any more (video removed)",
      pv.resolve_target(str(folder / "clip.mp4")) is None)
check("a text file resolves to None",
      pv.resolve_target(str(folder / "notes.txt")) is None)
check("no argument resolves to None", pv.resolve_target(None) is None)
check("an empty string resolves to None", pv.resolve_target("") is None)

print()
print("--- natural ordering, not lexicographic ----------------------------")
# pic10 must not sort before pic2; the video must not win over any photo
check("first pick is pic1, not pic10",
      os.path.basename(first) == "pic1.jpg", os.path.basename(first))

vids = work / "vids"
vids.mkdir()
for name in ("a.mp4", "b.mkv"):
    (vids / name).write_bytes(b"x")
check("a video-only folder resolves to None (video removed)",
      pv.resolve_target(str(vids)) is None)

mixed = work / "mixed"
mixed.mkdir()
for name in ("z_last.jpg", "a_first.txt"):
    (mixed / name).write_bytes(b"x")
check("photos outrank non-media files even when they sort first",
      os.path.basename(pv.resolve_target(str(mixed)) or "") == "z_last.jpg")

print()
print("--- the app really opens the folder --------------------------------")
ini = Path(tempfile.gettempdir()) / "pv_target.ini"
if ini.exists():
    ini.unlink()
pv.Viewer.SETTINGS = QSettings(str(ini), QSettings.IniFormat)

# resolve from the real fixture folder so the decode path is exercised too
real = HERE / "testpics"
target = pv.resolve_target(str(real))
check("testpics resolves to a photo",
      target is not None and Path(target).parent == real, target)

w = pv.Viewer(target)
# __init__ defers the open through QTimer.singleShot(0, ...), so the folder is
# not scanned until the event loop turns. Spin it before asserting on state.
loop = QEventLoop()
QTimer.singleShot(400, loop.quit)
loop.exec()
check("the whole folder is loaded, not just the one file",
      len(w.folder) == 3, f"{len(w.folder)} items: {[Path(p).name for p in w.folder]}")
check("the current photo is the one asked for",
      os.path.normcase(w.current()) == os.path.normcase(target), w.current())
check("it starts on a photo (video support removed)",
      Path(w.current()).suffix.lower() in __import__("pv_preview").core.IMAGE_EXTS,
      w.current())

w.close()
shutil.rmtree(work, ignore_errors=True)
if ini.exists():
    ini.unlink()

print()
if fails:
    print("FAILED %d: %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("ALL PASS")
"""Post-build trim: drop PySide6 DLLs picoSun never imports (photos only now)."""
import os

PY6 = "dist/picoSun/_internal/PySide6"
if not os.path.isdir(PY6):
    raise SystemExit(f"no {PY6}")

KEEP = {"Core", "Gui", "Widgets"}  # video removed: no Multimedia any more

removed = []
for f in sorted(os.listdir(PY6)):
    stem = os.path.splitext(f)[0]
    if f.startswith("Qt6") and f.endswith(".dll"):
        if stem[3:] not in KEEP:
            os.remove(os.path.join(PY6, f))
            removed.append(f)
    elif f.startswith("Qt") and f.endswith(".pyd") and f != "pyside6.abi3.dll":
        if stem.split(".")[0][2:] not in KEEP:
            os.remove(os.path.join(PY6, f))
            removed.append(f)
print(f"trim: removed {len(removed)} unused Qt modules")

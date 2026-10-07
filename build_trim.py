"""Post-build trim: drop PySide6 DLLs picoSun never imports.

PySide6's hook collects every Qt DLL regardless of `excludes`, so the only
way to keep cold start fast is to delete the dead Qt modules after build.
The app uses only QtWidgets/Gui/Core + QtMultimedia (video).
Run AFTER pyinstaller picoSun.spec:  python build_trim.py
"""
import os

PY6 = "dist/picoSun/_internal/PySide6"
if not os.path.isdir(PY6):
    raise SystemExit(f"no {PY6}")

# Qt modules this app uses (everything else is dead weight)
KEEP = {"Core", "Gui", "Widgets", "Multimedia", "MultimediaWidgets"}

removed = []
for f in sorted(os.listdir(PY6)):
    stem = os.path.splitext(f)[0]
    if f.startswith("Qt6") and f.endswith(".dll"):
        mod = stem[3:]
        if mod not in KEEP:
            os.remove(os.path.join(PY6, f))
            removed.append(f)
    elif f.startswith("Qt") and f.endswith(".pyd") and f != "pyside6.abi3.dll":
        mod = stem.split(".")[0][2:]
        if mod not in {m for m in KEEP}:
            os.remove(os.path.join(PY6, f))
            removed.append(f)
print(f"trim: removed {len(removed)} unused Qt modules: {', '.join(removed[:6])}{' …' if len(removed) > 6 else ''}")

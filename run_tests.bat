@echo off
setlocal
cd /d "%~dp0"
set PYTHONPATH=
for %%T in (test_pipeline.py test_raw.py test_zoom_anchor.py test_first_run.py test_gui.py test_navbar.py test_preview.py test_wheel_pacing.py test_titlebar.py test_target.py) do (
  echo ==== %%T
  ".venv\Scripts\python.exe" -u %%T
)

@echo off
REM picoSun reproducible build: PyInstaller + post-build trim.
REM Run from the repo root. Output: dist\picoSun\picoSun.exe (trimmed).
setlocal
cd /d "%~dp0"
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build
".venv\Scripts\pyinstaller.exe" picoSun.spec || exit /b 1
".venv\Scripts\python.exe" build_trim.py || exit /b 1
echo Build complete: dist\picoSun\picoSun.exe

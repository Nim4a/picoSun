@echo off
REM Launch picoSun. Pass a file to open it, or drag a photo onto the bat.
setlocal
set "HERE=%~dp0"
REM the onedir build starts in ~2s; the old onefile took 6s+ to unpack itself
set "EXE=%HERE%dist\picoSun\picoSun.exe"
if exist "%EXE%" (
  if "%~1"=="" (
    start "" "%EXE%"
  ) else (
    start "" "%EXE%" "%~1"
  )
  exit /b
)
"%HERE%.venv\Scripts\python.exe" "%HERE%picasa_viewer.py" %*

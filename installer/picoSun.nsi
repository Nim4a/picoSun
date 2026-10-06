; picoSun installer — portable app folder -> user-local install
; Run: makensis.exe picoSun.nsi
!define APP "picoSun"
!define VER "1.0.2"
!define PUB "Nim4a"

Name "${APP}"
OutFile "picoSun-setup-${VER}.exe"
Icon "..\picoSun.ico"
UninstallIcon "..\picoSun.ico"
InstallDir "$LOCALAPPDATA\Programs\picoSun"
RequestExecutionLevel user
Unicode true
SetCompressor lzma
CRCCheck on
XPStyle on

!include "MUI2.nsh"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "SimpChinese"

Section "Install"
  SetOutPath "$INSTDIR"
  # A fresh install is a fresh start: drop the saved window state so the app
  # comes up fullscreen on first launch instead of inheriting a windowed
  # geometry from an older build (the setting lives beside the app's own key).
  DeleteRegKey HKCU "Software\picoSun\picoSun"
  File /r "..\dist\picoSun\*.*"
  File /r "..\picoSun.ico"
  WriteUninstaller "$INSTDIR\uninstall.exe"
  SetOutPath "$INSTDIR"
  # launcher scr
  FileOpen $0 "$INSTDIR\run.cmd" w
  FileWrite $0 "@echo off$\r$\n"
  FileWrite $0 '"$INSTDIR\picoSun.exe" %*$\r$\n'
  FileClose $0
  # desktop shortcut (with icon)
  CreateShortCut "$DESKTOP\picoSun.lnk" "$INSTDIR\picoSun.exe" "" "$INSTDIR\picoSun.ico"
  # start menu shortcut
  CreateDirectory "$SMPROGRAMS\picoSun"
  CreateShortCut "$SMPROGRAMS\picoSun\picoSun.lnk" "$INSTDIR\picoSun.exe" "" "$INSTDIR\picoSun.ico"
  CreateShortCut "$SMPROGRAMS\picoSun\Uninstall.lnk" "$INSTDIR\uninstall.exe"
  # registry: silent
  WriteRegStr HKCU "Software\picoSun" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\picoSun" "DisplayName" "picoSun ${VER}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\picoSun" "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\picoSun" "Publisher" "${PUB}"
SectionEnd

Section "Uninstall"
  Delete "$INSTDIR\run.cmd"
  RMDir /r "$INSTDIR"
  Delete "$DESKTOP\picoSun.lnk"
  RMDir /r "$SMPROGRAMS\picoSun"
  DeleteRegKey HKCU "Software\picoSun"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\picoSun"
SectionEnd
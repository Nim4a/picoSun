; picoSun installer — portable app folder -> user-local install
; Run: makensis.exe picoSun.nsi
!define APP "picoSun"
!define VER "1.0.0"
!define PUB "Nim4a"

Name "${APP}"
OutFile "picoSun-setup-${VER}.exe"
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
  File /r "..\dist\picoSun\*.*"
  WriteUninstaller "$INSTDIR\uninstall.exe"
  SetOutPath "$INSTDIR"
  # launcher scr
  FileOpen $0 "$INSTDIR\run.cmd" w
  FileWrite $0 "@echo off$\r$\n"
  FileWrite $0 '"$INSTDIR\picoSun.exe" %*$\r$\n'
  FileClose $0
  # desktop shortcut
  CreateShortCut "$DESKTOP\picoSun.lnk" "$INSTDIR\picoSun.exe"
  # start menu shortcut
  CreateDirectory "$SMPROGRAMS\picoSun"
  CreateShortCut "$SMPROGRAMS\picoSun\picoSun.lnk" "$INSTDIR\picoSun.exe"
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
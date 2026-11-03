@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "EXE=%~dp0dist\PDFPrintChecker\PDFPrintChecker.exe"
set "ICON=%~dp0assets\app.ico"
set "DESKTOP=%USERPROFILE%\Desktop"
set "LNK=%DESKTOP%\PDF Print Checker.lnk"

if not exist "%EXE%" (
  echo Chua co EXE. Hay chay build_exe.bat truoc.
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\make_shortcut.ps1" -ExePath "%EXE%" -IconPath "%ICON%" -ShortcutPath "%LNK%" -WorkDir "%~dp0dist\PDFPrintChecker"
if errorlevel 1 (
  echo Tao shortcut that bai.
  exit /b 1
)

echo Da tao shortcut tren Desktop:
echo %LNK%
endlocal

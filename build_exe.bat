@echo off
chcp 65001 >nul
setlocal

echo === PDF Print Checker - Build EXE ===
cd /d "%~dp0"

python -m pip install -r requirements.txt
if errorlevel 1 (
  echo Loi cai dat dependencies.
  exit /b 1
)

if exist dist rmdir /s /q dist
if exist build rmdir /s /q build

python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --windowed ^
  --name "PDFPrintChecker" ^
  --hidden-import=win32print ^
  --hidden-import=win32api ^
  --hidden-import=win32con ^
  --hidden-import=pywintypes ^
  --hidden-import=pythoncom ^
  --hidden-import=watchdog.observers.winapi ^
  --collect-all PySide6 ^
  main.py

if errorlevel 1 (
  echo Build that bai.
  exit /b 1
)

echo.
echo OK. File EXE: dist\PDFPrintChecker\PDFPrintChecker.exe
echo Chay offline, khong can Internet/Docker/server.
endlocal

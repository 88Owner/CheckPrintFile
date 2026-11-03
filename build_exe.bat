@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo === PDF Print Checker - Dong goi EXE + Icon ===

python -m pip install -r requirements.txt >nul
if errorlevel 1 (
  echo Loi cai dat dependencies.
  exit /b 1
)

if not exist "assets\app.ico" (
  echo Tao icon...
  python -c "from PIL import Image,ImageDraw; from pathlib import Path; Path('assets').mkdir(exist_ok=True); s=256; im=Image.new('RGBA',(s,s),(0,0,0,0)); d=ImageDraw.Draw(im); d.rounded_rectangle([8,8,s-9,s-9],radius=48,fill=(37,99,235,255)); d.rounded_rectangle([55,45,155,200],radius=12,fill=(255,255,255,255)); d.ellipse([150,150,230,230],fill=(16,185,129,255)); d.line([(168,190),(185,208),(212,168)],fill=(255,255,255,255),width=8); imgs=[im.resize((n,n)) for n in (16,32,48,64,128,256)]; imgs[-1].save('assets/app.ico',format='ICO',sizes=[(n,n) for n in (16,32,48,64,128,256)]); im.save('assets/app.png'); print('icon ok')"
)

if exist dist rmdir /s /q dist
if exist build rmdir /s /q build

python -m PyInstaller --noconfirm --clean PDFPrintChecker.spec
if errorlevel 1 (
  echo Build that bai.
  exit /b 1
)

echo.
echo OK!
echo EXE: dist\PDFPrintChecker\PDFPrintChecker.exe
echo.
echo Tao shortcut Desktop? (Y/N)
set /p MAKE_SC=
if /I "%MAKE_SC%"=="Y" (
  call "%~dp0create_desktop_shortcut.bat"
)

endlocal

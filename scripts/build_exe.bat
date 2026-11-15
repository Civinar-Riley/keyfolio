@echo off
REM Keyfolio Windows exe build: onefile, static assets bundled, data lands in data\ next to the exe.
REM (Keep this file ASCII-only: cmd re-seeks batch files by decoded character offsets, which
REM misaligns for non-ASCII text when the console codepage differs from the file encoding.)
cd /d "%~dp0.."
python -m PyInstaller ^
  --onefile ^
  --name keyfolio ^
  --icon app\static\icons\icon.ico ^
  --add-data "app\static;app\static" ^
  --collect-all uvicorn ^
  --collect-submodules app ^
  --noconfirm ^
  --clean ^
  main.py
echo.
echo Output: dist\keyfolio.exe

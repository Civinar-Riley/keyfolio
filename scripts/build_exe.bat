@echo off
REM Keyfolio Windows exe 打包：onefile，静态资源打进包，数据落 exe 同目录 data\
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
echo 产物： dist\keyfolio.exe

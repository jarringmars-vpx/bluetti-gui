@echo off
setlocal
cd /d "%~dp0"

echo Building AP300 HA Live Change Monitor v0.9.3...
echo.
echo Community Library source:
echo   C:\Users\clay\bluetti-bt-lib
echo.

if not exist "C:\Users\clay\bluetti-bt-lib\bluetti_bt_lib\__init__.py" (
  echo ERROR: Standalone Community Library was not found:
  echo   C:\Users\clay\bluetti-bt-lib\bluetti_bt_lib
  echo.
  echo This build no longer uses or contains a vendor copy.
  pause
  exit /b 1
)

set "PYTHONPATH=C:\Users\clay\bluetti-bt-lib;%PYTHONPATH%"

C:\Python310\python.exe -c "import bluetti_bt_lib; print('Using bluetti_bt_lib from:', bluetti_bt_lib.__file__)"
if errorlevel 1 (
  echo.
  echo ERROR: Unable to import the standalone Community Library.
  pause
  exit /b 1
)

C:\Python310\python.exe -m PyInstaller --clean --noconfirm AP300_HA_Live_Change_Monitor_v0.9.3.spec
if errorlevel 1 (
  echo.
  echo BUILD FAILED
  pause
  exit /b 1
)

echo.
echo BUILD COMPLETE
echo EXE:
echo   "%CD%\dist\AP300 HA Live Change Monitor v0.9.3.exe"
pause

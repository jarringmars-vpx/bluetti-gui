@echo off
setlocal
cd /d "%~dp0"

set "PYTHON=C:\Python310\python.exe"
set "BLUETTI_BT_LIB_ROOT=C:\Users\clay\bluetti-bt-lib"
set "BLUETTI_COMMUNITY_RELEASE=1"

if not exist "%PYTHON%" (
  echo ERROR: Python 3.10 was not found at %PYTHON%
  exit /b 1
)

if not exist "%BLUETTI_BT_LIB_ROOT%\bluetti_bt_lib\__init__.py" (
  echo ERROR: Community library source was not found at:
  echo   %BLUETTI_BT_LIB_ROOT%\bluetti_bt_lib
  echo.
  echo This build is intentionally stopped rather than creating an incomplete release.
  exit /b 1
)

echo Community library source:
echo   %BLUETTI_BT_LIB_ROOT%\bluetti_bt_lib
"%PYTHON%" -c "import sys; sys.path.insert(0, r'%BLUETTI_BT_LIB_ROOT%'); import bluetti_bt_lib; print('Verified package:', bluetti_bt_lib.__file__)"
if errorlevel 1 (
  echo ERROR: The Community library could not be imported from the expected checkout.
  exit /b 1
)

echo.
"%PYTHON%" -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
  echo PyInstaller is not installed. Installing it now...
  "%PYTHON%" -m pip install pyinstaller
  if errorlevel 1 exit /b 1
)

if exist build rmdir /s /q build
if exist "dist\BLUETTI Monitor" rmdir /s /q "dist\BLUETTI Monitor"

"%PYTHON%" -m PyInstaller --noconfirm BLUETTI_Monitor_Community.spec
if errorlevel 1 exit /b 1

echo.
echo BUILD COMPLETE
 echo Community library bundled from:
echo   %BLUETTI_BT_LIB_ROOT%\bluetti_bt_lib
echo Test executable:
echo   "%CD%\dist\BLUETTI Monitor\BLUETTI Monitor.exe"
endlocal

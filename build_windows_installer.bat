@echo off
setlocal
cd /d "%~dp0"

call build_community_release.bat
if errorlevel 1 (
  echo.
  echo ERROR: Community application build failed. Installer was not created.
  exit /b 1
)

set "ISCC="
if exist "%ProgramFiles%\Inno Setup 7\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 7\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 7\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 7\ISCC.exe"
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"

if not defined ISCC (
  echo.
  echo ERROR: Inno Setup compiler ISCC.exe was not found.
  echo Install Inno Setup 7 x64 on this development PC, then run this script again.
  echo The application build itself completed successfully.
  exit /b 2
)

if exist installer_output rmdir /s /q installer_output
mkdir installer_output

echo.
echo Inno Setup compiler:
echo   %ISCC%
"%ISCC%" "packaging\BLUETTI_Monitor_Community.iss"
if errorlevel 1 (
  echo.
  echo ERROR: Installer compilation failed.
  exit /b 1
)

echo.
echo INSTALLER BUILD COMPLETE
echo Installer:
echo   "%CD%\installer_output\BLUETTI_Monitor_v0.2.58_Setup.exe"
endlocal

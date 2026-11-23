@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

set "PY=%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if not exist "%PY%" set "PY=python"

echo [1/4] Installing PyInstaller ...
"%PY%" -m pip install -q pyinstaller
if errorlevel 1 goto fail

echo [2/4] Building cupdrive.exe ...
"%PY%" -m PyInstaller --noconfirm --noconsole --name cupdrive ^
  --add-data "ui;ui" ^
  --add-data "web;web" ^
  --add-data "examples;examples" ^
  --collect-all bleak ^
  --collect-submodules winrt ^
  webapp.py
if errorlevel 1 goto fail

echo [3/4] Adding docs ...
copy /y README.md dist\cupdrive\ >nul
copy /y LICENSE dist\cupdrive\ >nul

echo [4/4] Zipping ...
if not exist release mkdir release
rem shutil.make_archive writes standard forward-slash zip entries;
rem PowerShell Compress-Archive uses backslashes, which some tools reject.
"%PY%" -c "import shutil; shutil.make_archive(r'release\cupdrive-win64', 'zip', r'dist\cupdrive')"
if errorlevel 1 goto fail

echo.
echo Done: release\cupdrive-win64.zip
echo Upload it to GitHub Releases:
echo   gh release create v0.3.1 release\cupdrive-win64.zip --title "cupdrive v0.3.1" --notes-file docs\release-notes.md
pause
exit /b 0

:fail
echo.
echo Build failed. See the messages above.
pause
exit /b 1

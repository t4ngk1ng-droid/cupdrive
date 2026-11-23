@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

rem Prefer the dsh runtime. System python may be the Store stub.
set "PY=%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"

if exist "%PY%" goto run

python -c "import sys" >nul 2>nul
if errorlevel 1 (
  echo.
  echo Python not found.
  echo Install Python 3.9+ or set PY in this file to your python.exe.
  echo.
  pause
  exit /b 1
)
set "PY=python"

:run
"%PY%" webapp.py %*
if errorlevel 1 pause

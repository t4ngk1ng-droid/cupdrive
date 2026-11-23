@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist ".git" (
  echo [i] .git already exists, skip init
  goto stage
)
rem Do not run "git branch -M main" on an empty repo: it fails with
rem "Not a valid object name". Use init -b, or symbolic-ref on old git.
git init -b main 2>nul
if errorlevel 1 (
  git init
  git symbolic-ref HEAD refs/heads/main
)
:stage
git add -A
git status --short
echo.
echo Next:
echo   git commit -m "initial commit"
echo   git remote add origin https://github.com/USER/cupdrive.git
echo   git push -u origin main
pause

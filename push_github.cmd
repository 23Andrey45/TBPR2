@echo off
setlocal EnableExtensions

set "BRANCH=main"
set "REMOTE=origin"
set "REPO_URL=https://github.com/23Andrey45/TBPR2.git"

cd /d "%~dp0"

where git >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Git not found. Install Git for Windows.
  pause
  exit /b 1
)

git rev-parse --is-inside-work-tree >nul 2>nul
if errorlevel 1 (
  echo [INFO] Initializing git repository...
  git init || goto :fail
)

git remote get-url %REMOTE% >nul 2>nul
if errorlevel 1 goto :add_remote
goto :set_remote

:add_remote
echo [INFO] Adding remote %REMOTE%...
git remote add %REMOTE% %REPO_URL% || goto :fail
goto :after_remote

:set_remote
echo [INFO] Updating remote %REMOTE% URL...
git remote set-url %REMOTE% %REPO_URL% || goto :fail

:after_remote
git add -A || goto :fail

git diff --cached --quiet
if errorlevel 1 goto :commit_changes
goto :no_changes

:commit_changes
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HH-mm-ss"') do set "TS=%%i"
git commit -m "auto sync %TS%" || goto :fail
goto :push

:no_changes
echo [INFO] No local changes to commit.

:push
git branch -M %BRANCH% || goto :fail
git push -u %REMOTE% %BRANCH% --force || goto :fail

echo [OK] Synced to GitHub.
pause
exit /b 0

:fail
echo [ERROR] Script failed.
pause
exit /b 1
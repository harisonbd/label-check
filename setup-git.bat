@echo off
rem (20 Oct 2026) ONE TIME ONLY: links this folder to GitHub (harisonbd/label-check). Your files stay as they are.
rem After this, use push.bat to send a new build. Everything git says is also written to push-log.txt.
cd /d "%~dp0"
echo setup-git.bat %date% %time% > push-log.txt
if exist .git (
  echo This folder is already linked to GitHub. Nothing to do. Use push.bat.
  pause
  exit /b
)
git init -b main >> push-log.txt 2>&1
git remote add origin https://harisonbd@github.com/harisonbd/label-check.git >> push-log.txt 2>&1
git fetch origin >> push-log.txt 2>&1
if errorlevel 1 (
  type push-log.txt
  echo.
  echo Could not reach GitHub. Tell Claude: "setup failed" - Claude reads push-log.txt.
  pause
  exit /b
)
rem Take GitHub's history, keep the files in this folder as they are.
git reset --mixed origin/main >> push-log.txt 2>&1
git branch --set-upstream-to=origin/main main >> push-log.txt 2>&1
git config user.name >nul 2>&1 || git config user.name "harisonbd"
git config user.email >nul 2>&1 || git config user.email "harisonbd@users.noreply.github.com"
echo Files that differ from GitHub: >> push-log.txt
git status --short >> push-log.txt 2>&1
type push-log.txt
echo.
echo Done: this folder is now linked to GitHub. Now double-click push.bat.
pause

@echo off
rem (20 Oct 2026) Double-click to send a new build to GitHub (harisonbd/label-check). GitHub Pages then shows it live.
rem Claude writes the new files into this folder plus .commit-msg.txt (what changed). This file commits them and pushes.
rem Everything git says is also written to push-log.txt (not in git), so Claude can read it if something goes wrong.
cd /d "%~dp0"
echo push.bat %date% %time% > push-log.txt
if not exist .git (
  echo This folder is not linked to GitHub yet. Double-click setup-git.bat first.
  echo No .git >> push-log.txt
  pause
  exit /b
)
if not exist .commit-msg.txt (
  echo No new build waiting: .commit-msg.txt is missing.
  echo No .commit-msg.txt >> push-log.txt
  pause
  exit /b
)
git config user.name >nul 2>&1 || git config user.name "harisonbd"
git config user.email >nul 2>&1 || git config user.email "harisonbd@users.noreply.github.com"
git add -A >> push-log.txt 2>&1
git commit -F .commit-msg.txt >> push-log.txt 2>&1
if errorlevel 1 (
  type push-log.txt
  echo.
  echo Commit did not work. Tell Claude: "push failed" - Claude reads push-log.txt.
  pause
  exit /b
)
rem The monthly database update on GitHub may have added a commit: take it first.
git pull --rebase >> push-log.txt 2>&1
if errorlevel 1 (
  git rebase --abort >nul 2>&1
  type push-log.txt
  echo.
  echo GitHub has newer files that clash with this build. Tell Claude: "push failed".
  pause
  exit /b
)
echo Commit done. Sending to GitHub...
git push >> push-log.txt 2>&1
if errorlevel 1 (
  type push-log.txt
  echo.
  echo Push did not work. If a sign-in window opened, sign in as harisonbd and double-click push.bat again. Otherwise tell Claude: "push failed".
  pause
  exit /b
)
del .commit-msg.txt
type push-log.txt
echo.
echo Done: the new build is on GitHub. The live app updates in about 1 minute.
pause

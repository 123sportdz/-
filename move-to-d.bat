@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"
call "%~dp0_env_local.bat"

rem ---------------------------------------------------------------
rem move-to-d.bat - run this ONCE after copying the project to D:.
rem The old .venv from drive C: is not portable (it stores absolute
rem paths), so it must be rebuilt in the new location.
rem Usage: copy the whole project folder to D:\elhadath-reels,
rem then double-click this file. It rebuilds .venv on D: and runs
rem the doctor. Afterwards ALWAYS start via start.bat / start_bot.bat
rem from the D: copy.
rem ---------------------------------------------------------------

echo ==========================================
echo  elhadath-reels - relocate to this drive
echo  Folder: %CD%
echo ==========================================
echo.

if /i "%CD:~0,2%"=="C:" (
  echo [!] You are running this from drive C:.
  echo     Copy the project folder to D: first, then run this file
  echo     from the D: copy.
  pause
  exit /b 1
)

if exist .venv\Scripts\python.exe (
  echo [i] Deleting the old non-portable .venv ...
  rmdir /s /q .venv
)

echo [i] Rebuilding the environment in place ...
call install.bat --auto
if errorlevel 1 (
  echo [X] Install failed - see messages above.
  pause
  exit /b 1
)

echo.
echo [OK] Done. Caches now live in .cache\ inside this folder,
echo      so nothing is written to drive C:.
echo      Start the app with start.bat ^(dashboard^) or
echo      start_bot.bat ^(Telegram bot^) from THIS folder.
echo      You may now delete the old copy on drive C:.
pause

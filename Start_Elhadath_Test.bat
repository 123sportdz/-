@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title elhadath-reels - Start and Test

echo Starting elhadath-reels on this computer...
curl.exe -fsS --max-time 2 http://127.0.0.1:8000/ >nul 2>&1
if errorlevel 1 (
  start "elhadath-reels dashboard" cmd.exe /k "cd /d ""%~dp0"" && call start.bat"
)

set /a attempts=0
:wait_for_dashboard
curl.exe -fsS --max-time 3 http://127.0.0.1:8000/ >nul 2>&1
if not errorlevel 1 goto dashboard_ready
set /a attempts+=1
if %attempts% GEQ 360 goto dashboard_timeout
timeout /t 5 /nobreak >nul
goto wait_for_dashboard

:dashboard_ready
echo The dashboard is responding at http://127.0.0.1:8000
echo Starting the isolated Zo browser window...
call Start_Browser_Test.bat
exit /b %errorlevel%

:dashboard_timeout
echo The dashboard did not start within 30 minutes.
echo Check the separate elhadath-reels dashboard window for an installation or startup error.
pause
exit /b 1

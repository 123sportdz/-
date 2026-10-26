@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"
call "%~dp0_env_local.bat"

rem ---------------------------------------------------------------
rem Telegram control bot - starts (or attaches to) the dashboard,
rem then listens for your commands from your phone. Long Polling:
rem no open ports / static IP needed. All ASCII to keep codepages safe.
rem ---------------------------------------------------------------
if not exist .venv\Scripts\python.exe (
  echo [!] .venv missing - running automatic install
  call install.bat --auto
)
if not exist .venv\Scripts\python.exe (
  echo [X] Install failed - run install.bat manually.
  pause
  exit /b 1
)

call .venv\Scripts\activate.bat

python -c "import json,os,sys;f='config.json';c=json.load(open(f,encoding='utf-8')) if os.path.exists(f) else {};t=os.environ.get('REEL_BOT_TOKEN') or c.get('bot_token') or '';sys.exit(0 if str(t).strip() else 1)" >nul 2>nul
if errorlevel 1 (
  echo [X] No bot token found.
  echo     1^) Telegram -^> @BotFather -^> /newbot -^> copy the token
  echo     2^) python reelbot.py --setup --token ^<TOKEN^>
  echo     3^) start_bot.bat  then send /id to the bot and run:
  echo        python reelbot.py --allow ^<chat_id^>
  pause
  exit /b 1
)

echo ======================================
echo  elhadath-reels - Telegram bot
echo  open your bot chat on the phone
echo  close this window to stop
echo ======================================
python reelbot.py --port 8000
pause

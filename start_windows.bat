@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Creating Python virtual environment...
  python -m venv .venv
  if errorlevel 1 goto error
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
if errorlevel 1 goto error
pip install -r requirements.txt
if errorlevel 1 goto error

if not exist ".env" (
  copy .env.example .env >nul
  echo.
  echo Created .env. Fill in BOT_TOKEN and CHANNEL_URL, then run this file again.
  notepad .env
  pause
  exit /b 0
)

python bot.py
pause
exit /b 0

:error
echo.
echo An error occurred. Take a screenshot of this window and send it for help.
pause
exit /b 1

@echo off
setlocal
cd /d "%~dp0"
title LAGGAM IPHOTOO - Local Event Server
set PHOTOO_DATA=%~dp0data
set PHOTOO_MODEL_DIR=%~dp0models
if not exist "%PHOTOO_DATA%" mkdir "%PHOTOO_DATA%"
echo ================================================
echo LAGGAM IPHOTOO - FREE LOCAL EVENT SERVER
echo ================================================
where py >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.10 or 3.11 from python.org.
  echo During setup, tick "Add Python to PATH".
  pause
  exit /b 1
)
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
if errorlevel 1 (
  echo Package installation failed. Check Internet and available disk space.
  pause
  exit /b 1
)
echo.
echo Starting local server. Keep this window open during the event.
echo Your photos and event records are stored in: %PHOTOO_DATA%
start "" http://127.0.0.1:8000
py -m uvicorn app:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1
pause

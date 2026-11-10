@echo off
setlocal
cd /d "%~dp0"
title LAGGAM IPHOTOO - Laptop Setup

echo ============================================================
echo LAGGAM IPHOTOO - ONE-TIME LAPTOP SETUP
echo ============================================================

where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher was not found.
  echo Install Python 3.11 or 3.12 x64 from https://www.python.org/downloads/windows/
  echo During installation, enable "Add python.exe to PATH".
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating Python virtual environment...
  py -3.11 -m venv .venv
  if errorlevel 1 py -3.12 -m venv .venv
  if errorlevel 1 (
    echo Could not create the virtual environment. Install Python 3.11 or 3.12 x64.
    pause
    exit /b 1
  )
)

echo Installing app and local AI packages...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements-laptop.txt
if errorlevel 1 (
  echo Package installation failed. Check Internet access and retry this setup.
  pause
  exit /b 1
)

if not exist "cloudflared.exe" (
  echo Downloading Cloudflare tunnel client...
  curl.exe -L --fail --retry 3 -o cloudflared.exe "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
  if errorlevel 1 (
    echo cloudflared download failed.
    echo Download the 64-bit Windows executable from:
    echo https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/
    pause
    exit /b 1
  )
)

echo Checking cloudflared...
cloudflared.exe --version
if errorlevel 1 (
  echo cloudflared.exe could not run. Download the latest 64-bit Windows executable again.
  pause
  exit /b 1
)

echo.
echo Setup complete. Run start_event.bat for each event day.
echo The first face-AI use downloads about 37 MB of model files.
pause

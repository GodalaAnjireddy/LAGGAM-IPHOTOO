@echo off
title LAGGAM IPHOTOO Nikon Auto Uploader
cd /d "%~dp0"
echo ================================================
echo LAGGAM IPHOTOO - Nikon folder auto uploader
echo ================================================
where py >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.10 or newer from python.org.
  echo During setup, tick "Add Python to PATH".
  pause
  exit /b 1
)
if not exist config.json (
  echo config.json not found.
  echo Copy config.example.json to config.json and fill in the event details.
  pause
  exit /b 1
)
py -m pip install --upgrade requests
if errorlevel 1 (
  echo Could not install requests. Check your internet connection.
  pause
  exit /b 1
)
py uploader.py
pause

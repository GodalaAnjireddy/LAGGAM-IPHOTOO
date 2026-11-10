@echo off
setlocal
cd /d "%~dp0"
title LAGGAM IPHOTOO - Event Server
if not exist ".venv\Scripts\python.exe" (
  echo Run setup_laptop.bat once before starting.
  pause
  exit /b 1
)
if not exist "cloudflared.exe" (
  echo cloudflared.exe is missing. Run setup_laptop.bat.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" launcher.py
pause
